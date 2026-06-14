from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from discord import PartialEmoji

_CUSTOM_EMOJI_RE = re.compile(r"^<(?P<animated>a)?:(?P<name>[a-zA-Z0-9_]+):(?P<id>\d+)>$")

_TYPE_VALUES = frozenset({"battles_won", "merges", "tournament_win", "tournament_participate", "balls_owned", "custom"})

_TYPE_LABELS = {
    "battles_won": "Battles Won",
    "merges": "Merges Completed",
    "tournament_win": "Tournament Wins",
    "tournament_participate": "Tournament Participation",
    "balls_owned": "Clubballs Owned",
    "custom": "Custom (manual)",
}


def normalize_achievement_type(raw: str) -> str:
    return raw.strip().lower().replace("-", "_").replace(" ", "_")


def parse_bool_field(raw: str | None, *, default: bool = False) -> bool:
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class AchievementExtras:
    reward_money: int
    emoji: str
    reward_ball_raw: str
    hidden: bool
    enabled: bool


def format_achievement_extras(
    *, reward_money: int, emoji: str, reward_ball_id: int | None, hidden: bool, enabled: bool
) -> str:
    lines = [f"coins={reward_money}", f"emoji={emoji}", f"hidden={'yes' if hidden else 'no'}"]
    if reward_ball_id is not None:
        lines.append(f"ball={reward_ball_id}")
    lines.append(f"enabled={'yes' if enabled else 'no'}")
    return "\n".join(lines)


def parse_achievement_extras(
    raw: str | None,
    *,
    default_hidden: bool = False,
    default_enabled: bool = True,
    default_emoji: str = "🏆",
    default_coins: int = 0,
) -> tuple[AchievementExtras | None, str | None]:
    """Parse combined extras field for achievement modals (Discord allows max 5 inputs)."""
    text = (raw or "").strip()
    coins = default_coins
    emoji = default_emoji
    ball_raw = ""
    hidden = default_hidden
    enabled = default_enabled

    if not text:
        return (
            AchievementExtras(
                reward_money=coins, emoji=emoji[:32], reward_ball_raw=ball_raw, hidden=hidden, enabled=enabled
            ),
            None,
        )

    for chunk in re.split(r"[\n,;]+", text):
        piece = chunk.strip()
        if not piece or "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in ("coins", "coin", "money", "reward_money"):
            try:
                coins = int(value.replace(",", ""))
                if coins < 0:
                    raise ValueError
            except ValueError:
                return None, "Coin reward must be a non-negative number."
        elif key in ("ball", "clubball", "reward_ball"):
            ball_raw = value
        elif key == "emoji":
            emoji = value or default_emoji
        elif key == "hidden":
            hidden = parse_bool_field(value, default=default_hidden)
        elif key == "enabled":
            enabled = parse_bool_field(value, default=default_enabled)
        else:
            return None, f"Unknown extras key `{key}` — use coins, ball, emoji, hidden, enabled."

    return (
        AchievementExtras(
            reward_money=coins, emoji=emoji[:32], reward_ball_raw=ball_raw, hidden=hidden, enabled=enabled
        ),
        None,
    )


def _is_unicode_emoji(text: str) -> bool:
    """True when *text* is a single Discord-valid Unicode emoji (not plain words)."""
    if not text or len(text) > 32:
        return False
    compact = "".join(ch for ch in text if not ch.isspace())
    if not compact:
        return False
    if compact.isascii() and compact.isalnum():
        return False
    has_emoji = False
    for ch in text:
        code = ord(ch)
        if ch in "\u200d\u20e3\ufe0f":
            continue
        if unicodedata.category(ch) in ("Mn", "Me"):
            continue
        if 0x1F1E6 <= code <= 0x1F1FF:
            has_emoji = True
            continue
        if 0x1F300 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF or 0x2300 <= code <= 0x23FF:
            has_emoji = True
            continue
        if unicodedata.category(ch) == "So" and code > 0xFFFF:
            has_emoji = True
            continue
        if "0" <= ch <= "9" and "\u20e3" in text:
            has_emoji = True
            continue
        return False
    return has_emoji


def _select_emoji(raw: str | None) -> str | PartialEmoji | None:
    """Return a value safe for discord.SelectOption(emoji=...), or None to omit."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    match = _CUSTOM_EMOJI_RE.match(text)
    if match:
        return PartialEmoji(
            name=match.group("name"), id=int(match.group("id")), animated=match.group("animated") is not None
        )
    if _is_unicode_emoji(text):
        return text
    return None
