"""FC Derby rules: formations, squad checks, reward rolls and the daily cap.

Everything here is plain logic with no Discord or database objects, so it can be tested without a bot.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

# Positions in pitch order, goalkeeper at the back.
POSITIONS: tuple[str, ...] = ("GK", "DF", "MF", "ST")
POSITION_LABELS: dict[str, str] = {"GK": "Goalkeeper", "DF": "Defender", "MF": "Midfielder", "ST": "Striker"}

SQUAD_SIZE = 11
# A derby needs a full squad, there is no partial lineup.
MIN_SQUAD_SIZE = SQUAD_SIZE
DEFAULT_FORMATION = "4-3-3"
DEFAULT_DAILY_LIMIT = 12

DEFAULT_WINNER_COINS = (150, 300)
DEFAULT_LOSER_COINS = 50
DEFAULT_WINNER_XP = (20, 30)
DEFAULT_LOSER_XP = 10

# Challenge button lifetime, in seconds.
CHALLENGE_TIMEOUT_SECONDS = 120

SlotKey = tuple[str, int]


@dataclass(frozen=True, slots=True)
class Formation:
    """A formation as rows of the pitch from the goalkeeper up, each row `(position, players)`."""

    key: str
    rows: tuple[tuple[str, int], ...]

    def count(self, position: str) -> int:
        return sum(size for pos, size in self.rows if pos == position)

    @property
    def total(self) -> int:
        return sum(size for _, size in self.rows)

    def slot_keys(self) -> list[SlotKey]:
        return [(position, slot) for position in POSITIONS for slot in range(self.count(position))]

    def layout(self) -> list[tuple[str, int, float, float]]:
        """`(position, slot, x, y)` for every slot, x and y in 0..1 with y = 0 at the attacking end."""
        out: list[tuple[str, int, float, float]] = []
        used: dict[str, int] = {}
        row_count = len(self.rows)
        for row_index, (position, size) in enumerate(self.rows):
            y = 0.92 - (0.84 * row_index / max(row_count - 1, 1))
            for i in range(size):
                x = (i + 0.5) / size
                slot = used.get(position, 0)
                used[position] = slot + 1
                out.append((position, slot, x, y))
        return out

    def summary(self) -> str:
        return " · ".join(f"{self.count(position)} {position}" for position in POSITIONS)


def _formation(key: str, *rows: tuple[str, int]) -> Formation:
    return Formation(key=key, rows=(("GK", 1), *rows))


FORMATIONS: dict[str, Formation] = {
    f.key: f
    for f in (
        _formation("4-3-3", ("DF", 4), ("MF", 3), ("ST", 3)),
        _formation("4-4-2", ("DF", 4), ("MF", 4), ("ST", 2)),
        _formation("3-5-2", ("DF", 3), ("MF", 5), ("ST", 2)),
        _formation("4-2-3-1", ("DF", 4), ("MF", 2), ("MF", 3), ("ST", 1)),
        _formation("5-3-2", ("DF", 5), ("MF", 3), ("ST", 2)),
    )
}
FORMATION_ORDER: tuple[str, ...] = tuple(FORMATIONS)


def get_formation(key: str | None) -> Formation:
    """The formation for `key`, falling back to the default for unknown or missing keys."""
    return FORMATIONS.get(key or "", FORMATIONS[DEFAULT_FORMATION])


# A squad maps a slot to the ball (clubball type) standing there. Each ball may appear only once.
Squad = Mapping[SlotKey, int]


def normalize_position(raw: str) -> str | None:
    value = raw.strip().upper()
    return value if value in POSITIONS else None


@dataclass(frozen=True, slots=True)
class AddCheck:
    ok: bool
    slot: int = 0
    reason: str = ""
    replaces: bool = False


def check_add(formation: Formation, squad: Squad, position: str, ball_id: int, *, slot: int | None = None) -> AddCheck:
    """Can `ball_id` go to `position`? `slot` is 1-based like the command, omitted = first free slot.

    A club may stand in only one slot, putting the very same club back into the slot it already holds is
    refused too, so there is nothing to replace with itself.
    """
    if position not in POSITIONS:
        return AddCheck(False, reason="Pick a position: GK, DF, MF or ST.")
    capacity = formation.count(position)
    if capacity <= 0:
        return AddCheck(False, reason=f"The {formation.key} formation has no {position} slot.")

    existing = next((key for key, value in squad.items() if value == ball_id), None)
    if existing is not None:
        where = f"{existing[0]}{existing[1] + 1}"
        return AddCheck(False, reason=f"That club is already in your squad ({where}). A club can only appear once.")

    if slot is None:
        free = next((i for i in range(capacity) if (position, i) not in squad), None)
        if free is None:
            return AddCheck(False, reason=f"All {capacity} {position} slots are full. Pass `slot` to replace one.")
        return AddCheck(True, slot=free)

    if not 1 <= slot <= capacity:
        return AddCheck(False, reason=f"{formation.key} has {capacity} {position} slot(s), pick 1-{capacity}.")
    index = slot - 1
    return AddCheck(True, slot=index, replaces=(position, index) in squad)


def squad_size(formation: Formation, squad: Squad) -> int:
    valid = set(formation.slot_keys())
    return sum(1 for key in squad if key in valid)


def is_complete(formation: Formation, squad: Squad) -> bool:
    return squad_size(formation, squad) >= max(MIN_SQUAD_SIZE, formation.total)


def missing_slots(formation: Formation, squad: Squad) -> list[SlotKey]:
    return [key for key in formation.slot_keys() if key not in squad]


def format_missing(formation: Formation, squad: Squad) -> str:
    missing = missing_slots(formation, squad)
    if not missing:
        return ""
    return ", ".join(f"{position}{slot + 1}" for position, slot in missing)


def slots_outside(formation: Formation, squad: Squad) -> list[SlotKey]:
    """Slots a squad fills that the formation no longer has (after switching formation)."""
    valid = set(formation.slot_keys())
    return [key for key in squad if key not in valid]


# -- layout picker ---------------------------------------------------------------------------------------------


@dataclass
class LayoutPicker:
    """Which formation `/fc derby layouts` is showing. Next cycles, Accept takes the current one."""

    keys: tuple[str, ...] = FORMATION_ORDER
    index: int = 0
    accepted: str | None = None

    @classmethod
    def starting_at(cls, key: str | None) -> LayoutPicker:
        picker = cls()
        if key in picker.keys:
            picker.index = picker.keys.index(key)  # type: ignore[arg-type]
        return picker

    @property
    def current(self) -> str:
        return self.keys[self.index % len(self.keys)]

    @property
    def position_text(self) -> str:
        return f"{self.index % len(self.keys) + 1}/{len(self.keys)}"

    def next(self) -> str:
        self.index = (self.index + 1) % len(self.keys)
        return self.current

    def accept(self) -> str:
        self.accepted = self.current
        return self.accepted


# -- rewards ---------------------------------------------------------------------------------------------------


class _ConfigLike(Protocol):
    winner_coins_min: int
    winner_coins_max: int
    loser_coins: int
    winner_xp_min: int
    winner_xp_max: int
    loser_xp: int
    daily_limit: int


@dataclass(frozen=True, slots=True)
class DerbyRanges:
    winner_coins: tuple[int, int] = DEFAULT_WINNER_COINS
    loser_coins: int = DEFAULT_LOSER_COINS
    winner_xp: tuple[int, int] = DEFAULT_WINNER_XP
    loser_xp: int = DEFAULT_LOSER_XP
    daily_limit: int = DEFAULT_DAILY_LIMIT


def _range(low: int, high: int) -> tuple[int, int]:
    low, high = max(int(low), 0), max(int(high), 0)
    return (low, high) if low <= high else (high, low)


def ranges_from_config(config: _ConfigLike) -> DerbyRanges:
    return DerbyRanges(
        winner_coins=_range(config.winner_coins_min, config.winner_coins_max),
        loser_coins=max(int(config.loser_coins), 0),
        winner_xp=_range(config.winner_xp_min, config.winner_xp_max),
        loser_xp=max(int(config.loser_xp), 0),
        daily_limit=max(int(config.daily_limit), 1),
    )


@dataclass(frozen=True, slots=True)
class DerbyRewards:
    coins: int
    xp: int


def roll_rewards(ranges: DerbyRanges, *, won: bool, rng: random.Random | None = None) -> DerbyRewards:
    """Coins and Club Pass XP for one side. The winner rolls inside the ranges, the loser gets the flat amounts."""
    source = rng or random
    if won:
        return DerbyRewards(coins=source.randint(*ranges.winner_coins), xp=source.randint(*ranges.winner_xp))
    return DerbyRewards(coins=ranges.loser_coins, xp=ranges.loser_xp)


# -- daily cap -------------------------------------------------------------------------------------------------


def utc_day_start(now: datetime) -> datetime:
    moment = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def next_reset_delta(now: datetime) -> timedelta:
    return utc_day_start(now) + timedelta(days=1) - (now if now.tzinfo else now.replace(tzinfo=UTC))


def daily_limit_reached(used: int, limit: int = DEFAULT_DAILY_LIMIT) -> bool:
    return used >= limit


def daily_limit_message(now: datetime, *, limit: int = DEFAULT_DAILY_LIMIT, who: str = "You've") -> str:
    hours, rem = divmod(int(next_reset_delta(now).total_seconds()), 3600)
    return (
        f"{who} reached today's derby limit (**{limit}** per day). Resets in **{hours}h {rem // 60}m** (UTC midnight)."
    )


# -- challenge flow --------------------------------------------------------------------------------------------


@dataclass
class ActiveDerbies:
    """Players currently in a derby (waiting for an answer or playing). One derby per player at a time."""

    players: set[int] = field(default_factory=set)

    def busy(self, *discord_ids: int) -> bool:
        return any(i in self.players for i in discord_ids)

    def start(self, *discord_ids: int) -> bool:
        if self.busy(*discord_ids):
            return False
        self.players.update(discord_ids)
        return True

    def finish(self, *discord_ids: int) -> None:
        self.players.difference_update(discord_ids)


def validate_challenge(challenger_id: int, opponent_id: int, *, opponent_is_bot: bool) -> str | None:
    """A reason the challenge is not allowed, or None."""
    if opponent_is_bot:
        return "You can't play a derby against a bot."
    if challenger_id == opponent_id:
        return "You can't play a derby against yourself."
    return None


def winner_side(alive_p1: int, alive_p2: int) -> int | None:
    """1 or 2 for the side with players left, None for a draw (both or neither)."""
    if alive_p1 > 0 and alive_p2 == 0:
        return 1
    if alive_p2 > 0 and alive_p1 == 0:
        return 2
    return None


def derby_highlights(log_lines: Iterable[str], *, limit: int = 14) -> list[str]:
    """The commentary worth showing: eliminations (the last `limit` of them)."""
    key_lines = [line for line in log_lines if "eliminated" in line or "nobody wins" in line]
    return key_lines[-limit:]


def format_xp_level_text(xp: int, levels_gained: int, level: int | None) -> str:
    text = f"+{xp} XP"
    if levels_gained > 0:
        text += f" · level up x{levels_gained}" if levels_gained > 1 else " · level up"
    if level is not None:
        text += f" · level {level}"
    return text
