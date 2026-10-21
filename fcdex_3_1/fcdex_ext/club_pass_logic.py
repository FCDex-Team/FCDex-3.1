"""Club pass: seasons, xp tables, level rewards and atomic reward claims.

Public API for other features:

- `await grant_pass_xp(player, amount)` -> `PassXpResult` (a no-op with `active=False` when no season is running)
- `await get_pass_progress(player)` -> `PassProgress | None`
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone

from bd_models.models import Ball, BallInstance, Player
from fcdex_3_1.fcdex_ext.currency import format_money
from fcdex_3_1.fcdex_ext.rarity_logic import fetch_all_balls, pick_common_ball
from fcdex_3_1.models import (
    PassLevelReward,
    PassRewardClaim,
    PassRewardType,
    PassSeason,
    PassSeasonClub,
    PassTrack,
    PlayerPass,
)

log = logging.getLogger("fcdex_3_1.club_pass")

MAX_LEVEL = 50

# xp needed to go from level N-1 to level N, as (first level, last level, xp) bands.
PREMIUM_XP_BANDS: tuple[tuple[int, int, int], ...] = (
    (1, 10, 100),
    (11, 19, 250),
    (20, 29, 400),
    (30, 39, 650),
    (40, 45, 900),
    (46, 49, 1600),
    (50, 50, 2000),
)
NORMAL_XP_BANDS: tuple[tuple[int, int, int], ...] = (
    (1, 10, 350),
    (11, 29, 650),
    (30, 39, 900),
    (40, 45, 1600),
    (46, 49, 2100),
    (50, 50, 2500),
)

CATCH_XP_MIN = 25
CATCH_XP_MAX = 300
CATCH_XP_FALLBACK = 15
SEASON_CLUB_BONUS_PERCENT = 50

DERBY_XP_WIN = 25
DERBY_XP_LOSS = 10

SEEDED_NORMAL_COINS = 1_000
SEEDED_PREMIUM_COINS = 3_000


def _bands(track: str) -> tuple[tuple[int, int, int], ...]:
    return PREMIUM_XP_BANDS if track == PassTrack.PREMIUM else NORMAL_XP_BANDS


def _level_costs(track: str) -> list[int]:
    costs: list[int] = []
    for first, last, xp in _bands(track):
        costs.extend([xp] * (last - first + 1))
    return costs


def _cumulative(track: str) -> list[int]:
    total = 0
    out = [0]
    for cost in _level_costs(track):
        total += cost
        out.append(total)
    return out


_CUMULATIVE = {PassTrack.NORMAL.value: _cumulative(PassTrack.NORMAL), PassTrack.PREMIUM.value: _cumulative("premium")}


def xp_for_level(level: int, track: str) -> int:
    """Total xp at which `level` is reached (level 0 = 0 xp)."""
    table = _CUMULATIVE[PassTrack.PREMIUM.value if track == PassTrack.PREMIUM else PassTrack.NORMAL.value]
    return table[max(0, min(level, MAX_LEVEL))]


def xp_for_next(level: int, track: str) -> int:
    """xp needed to go from `level` to `level + 1`, 0 once the pass is maxed."""
    if level >= MAX_LEVEL:
        return 0
    return xp_for_level(level + 1, track) - xp_for_level(max(level, 0), track)


def level_for_xp(xp: int, track: str) -> int:
    table = _CUMULATIVE[PassTrack.PREMIUM.value if track == PassTrack.PREMIUM else PassTrack.NORMAL.value]
    level = 0
    for candidate in range(1, MAX_LEVEL + 1):
        if xp >= table[candidate]:
            level = candidate
        else:
            break
    return level


def track_of(premium: bool) -> str:
    return PassTrack.PREMIUM.value if premium else PassTrack.NORMAL.value


def xp_bar(xp: int, level: int, track: str, *, width: int = 12) -> str:
    if level >= MAX_LEVEL:
        return "▰" * width
    into = xp - xp_for_level(level, track)
    need = xp_for_next(level, track)
    filled = int(width * into / need) if need else width
    filled = max(0, min(width, filled))
    return "▰" * filled + "▱" * (width - filled)


# catch xp ----------------------------------------------------------------------------------------------------


def catch_xp_for_rarity(rarity: float | None, min_rarity: float, max_rarity: float) -> int:
    """25 xp for the commonest clubball up to 300 for the rarest (lower rarity value = rarer)."""
    if rarity is None or max_rarity <= min_rarity:
        return CATCH_XP_FALLBACK
    ratio = max(0.0, min(1.0, (max_rarity - rarity) / (max_rarity - min_rarity)))
    return int(round(CATCH_XP_MIN + ratio * (CATCH_XP_MAX - CATCH_XP_MIN)))


def apply_club_bonus(xp: int, is_season_club: bool) -> int:
    if not is_season_club:
        return xp
    return xp + xp * SEASON_CLUB_BONUS_PERCENT // 100


# seasons -----------------------------------------------------------------------------------------------------


def add_months(moment: datetime, months: int) -> datetime:
    """`moment` plus whole calendar months, clamping the day (31 Jan + 1 month = 28/29 Feb)."""
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


@dataclass(frozen=True, slots=True)
class SeedReward:
    level: int
    track: str
    reward_type: str
    coins: int = 0


def default_rewards() -> list[SeedReward]:
    """Editable starter rewards: a prize every 5 levels, none in between.

    Level 1 is a random common clubball, level 6 is 1,000 coins (3,000 premium), then every 5 levels more coins
    (+250 normal / +750 premium per step), and level 50 is a random common clubball again.
    """
    rewards: list[SeedReward] = []
    for track, base in ((PassTrack.NORMAL.value, SEEDED_NORMAL_COINS), (PassTrack.PREMIUM.value, SEEDED_PREMIUM_COINS)):
        step = base // 4
        rewards.append(SeedReward(1, track, PassRewardType.RANDOM_COMMON.value))
        for level in range(6, MAX_LEVEL, 5):
            rewards.append(SeedReward(level, track, PassRewardType.COINS.value, base + step * ((level - 6) // 5)))
        rewards.append(SeedReward(MAX_LEVEL, track, PassRewardType.RANDOM_COMMON.value))
    return rewards


MAX_SEASON_MONTHS = 24


def parse_months(raw: str) -> int:
    try:
        months = int(raw.strip())
    except ValueError:
        raise ValueError(f"Months must be a whole number between 1 and {MAX_SEASON_MONTHS}.") from None
    if not 1 <= months <= MAX_SEASON_MONTHS:
        raise ValueError(f"Months must be a whole number between 1 and {MAX_SEASON_MONTHS}.")
    return months


@dataclass(frozen=True, slots=True)
class RewardSpec:
    level: int
    track: str
    reward_type: str
    coins: int = 0
    ball_query: str = ""


def parse_reward_spec(level_raw: str, track_raw: str, type_raw: str, value_raw: str) -> RewardSpec:
    """Validate the admin's level reward form. Raises ValueError with a message meant for the admin."""
    try:
        level = int(level_raw.strip())
    except ValueError:
        raise ValueError(f"Level must be a number from 1 to {MAX_LEVEL}.") from None
    if not 1 <= level <= MAX_LEVEL:
        raise ValueError(f"Level must be a number from 1 to {MAX_LEVEL}.")
    track = track_raw.strip().lower()
    if track not in (PassTrack.NORMAL.value, PassTrack.PREMIUM.value):
        raise ValueError("Track must be `normal` or `premium`.")
    kind = type_raw.strip().lower().replace(" ", "_").replace("-", "_")
    if kind not in {choice.value for choice in PassRewardType}:
        raise ValueError("Type must be `none`, `coins`, `ball` or `random_common`.")
    value = value_raw.strip()
    if kind == PassRewardType.COINS:
        try:
            coins = int(value.replace(",", ""))
        except ValueError:
            raise ValueError("Coins needs a whole number in the amount field.") from None
        if coins < 1:
            raise ValueError("Coins must be at least 1.")
        return RewardSpec(level, track, kind, coins=coins)
    if kind == PassRewardType.BALL:
        if not value:
            raise ValueError("Ball needs a clubball name or id in the amount field.")
        return RewardSpec(level, track, kind, ball_query=value)
    return RewardSpec(level, track, kind)


_season_cache: tuple[float, PassSeason | None] | None = None
SEASON_CACHE_SECONDS = 15.0


def invalidate_season_cache() -> None:
    global _season_cache
    _season_cache = None


async def get_active_season(*, use_cache: bool = True) -> PassSeason | None:
    global _season_cache
    if use_cache and _season_cache is not None and time.monotonic() - _season_cache[0] < SEASON_CACHE_SECONDS:
        season = _season_cache[1]
        if season is None or season.ends_at > timezone.now():
            return season
    now = timezone.now()
    season = (
        await PassSeason.objects.filter(active=True, starts_at__lte=now, ends_at__gt=now)
        .order_by("-starts_at")
        .afirst()
    )
    _season_cache = (time.monotonic(), season)
    return season


async def create_season(name: str, months: int, *, now: datetime | None = None) -> PassSeason:
    start = now or timezone.now()
    season = await PassSeason.objects.acreate(name=name, starts_at=start, ends_at=add_months(start, months))
    await PassLevelReward.objects.abulk_create(
        [
            PassLevelReward(
                season=season, level=seed.level, track=seed.track, reward_type=seed.reward_type, coins=seed.coins
            )
            for seed in default_rewards()
        ]
    )
    invalidate_season_cache()
    return season


async def end_season(season: PassSeason) -> None:
    await PassSeason.objects.filter(pk=season.pk).aupdate(active=False)
    invalidate_season_cache()


# progress ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PassXpResult:
    levels_gained: int
    level: int
    xp_total: int
    active: bool


@dataclass(frozen=True, slots=True)
class PassProgress:
    season: PassSeason
    xp_total: int
    level: int
    premium: bool

    @property
    def track(self) -> str:
        return track_of(self.premium)

    @property
    def xp_into_level(self) -> int:
        return self.xp_total - xp_for_level(self.level, self.track)

    @property
    def xp_needed(self) -> int:
        return xp_for_next(self.level, self.track)

    @property
    def maxed(self) -> bool:
        return self.level >= MAX_LEVEL


async def grant_pass_xp(player: Player, amount: int) -> PassXpResult:
    """Add club pass xp. Returns `active=False` (and changes nothing) when no season is running."""
    if amount <= 0:
        return PassXpResult(0, 0, 0, False)
    season = await get_active_season()
    if season is None:
        return PassXpResult(0, 0, 0, False)
    row, _ = await PlayerPass.objects.aget_or_create(player=player, season=season)
    await PlayerPass.objects.filter(pk=row.pk).aupdate(xp_total=F("xp_total") + amount)
    row = await PlayerPass.objects.aget(pk=row.pk)
    track = track_of(row.premium)
    level = level_for_xp(row.xp_total, track)
    before = level_for_xp(max(0, row.xp_total - amount), track)
    return PassXpResult(levels_gained=level - before, level=level, xp_total=row.xp_total, active=True)


async def get_pass_progress(player: Player) -> PassProgress | None:
    season = await get_active_season()
    if season is None:
        return None
    row = await PlayerPass.objects.filter(player=player, season=season).afirst()
    xp = row.xp_total if row else 0
    premium = bool(row and row.premium)
    return PassProgress(season=season, xp_total=xp, level=level_for_xp(xp, track_of(premium)), premium=premium)


async def set_premium(player: Player, premium: bool) -> bool:
    """Grant or remove premium for the running season. False when no season is running."""
    season = await get_active_season()
    if season is None:
        return False
    row, _ = await PlayerPass.objects.aget_or_create(player=player, season=season)
    await PlayerPass.objects.filter(pk=row.pk).aupdate(premium=premium)
    return True


# catch xp hook -----------------------------------------------------------------------------------------------

_awarded_instances: OrderedDict[int, None] = OrderedDict()
_AWARDED_LIMIT = 4096


def mark_awarded(instance_id: int) -> bool:
    """True the first time an instance id is seen. Used so one catch is never paid twice by different hooks."""
    if instance_id in _awarded_instances:
        return False
    _awarded_instances[instance_id] = None
    while len(_awarded_instances) > _AWARDED_LIMIT:
        _awarded_instances.popitem(last=False)
    return True


def reset_awarded() -> None:
    _awarded_instances.clear()


async def catch_xp_for_ball(ball_id: int) -> int:
    all_balls = [b for b in await fetch_all_balls() if b.enabled]
    target = next((b for b in all_balls if b.pk == ball_id), None)
    if target is None or not all_balls:
        return CATCH_XP_FALLBACK
    rarities = [b.rarity for b in all_balls]
    return catch_xp_for_rarity(target.rarity, min(rarities), max(rarities))


async def award_catch_xp(instance: Any, player: Player | None = None) -> PassXpResult | None:
    """Pay pass xp for a caught clubball instance, once per instance. Never raises."""
    try:
        instance_id = getattr(instance, "pk", None)
        if instance_id is None or not mark_awarded(instance_id):
            return None
        season = await get_active_season()
        if season is None:
            return None
        if player is None:
            player = await Player.objects.aget(pk=instance.player_id)
        xp = await catch_xp_for_ball(instance.ball_id)
        is_club = await PassSeasonClub.objects.filter(season=season, ball_id=instance.ball_id).aexists()
        return await grant_pass_xp(player, apply_club_bonus(xp, is_club))
    except Exception:
        log.warning("Could not award club pass xp for a catch.", exc_info=True)
        return None


_background: set[asyncio.Task[Any]] = set()


def schedule_catch_xp(instance: Any, player: Player | None = None) -> None:
    """Pay catch xp in the background so the catch itself is never slowed down or broken."""
    try:
        task = asyncio.get_running_loop().create_task(award_catch_xp(instance, player))
    except RuntimeError:
        return
    _background.add(task)
    task.add_done_callback(_background.discard)


# rewards -----------------------------------------------------------------------------------------------------


def reward_text(reward: Any, ball_name: str | None = None) -> str:
    kind = reward.reward_type
    if kind == PassRewardType.COINS:
        return format_money(reward.coins)
    if kind == PassRewardType.BALL:
        return f"**{ball_name or 'a clubball'}**"
    if kind == PassRewardType.RANDOM_COMMON:
        return "a random common clubball"
    return "nothing"


def unlocked_rewards(rewards: Iterable[Any], level: int, premium: bool, claimed: set[tuple[int, str]]) -> list[Any]:
    """Rewards the player reached, may take (premium track needs premium) and has not claimed yet."""
    out = []
    for reward in rewards:
        if reward.reward_type == PassRewardType.NONE or reward.level > level:
            continue
        if reward.track == PassTrack.PREMIUM and not premium:
            continue
        if (reward.level, reward.track) in claimed:
            continue
        out.append(reward)
    return sorted(out, key=lambda r: (r.level, r.track))


@dataclass(slots=True)
class ClaimOutcome:
    lines: list[str]
    claimed: int
    failed: int = 0


async def run_claims(
    rewards: Sequence[Any],
    try_claim: Callable[[Any], Awaitable[bool]],
    grant: Callable[[Any], Awaitable[str]],
    release: Callable[[Any], Awaitable[None]],
) -> ClaimOutcome:
    """Claim-first: record the claim (unique row, so only one caller wins), then grant, undo the claim on failure."""
    outcome = ClaimOutcome(lines=[], claimed=0)
    for reward in rewards:
        if not await try_claim(reward):
            continue  # somebody else (a double click) already took it
        try:
            text = await grant(reward)
        except Exception:
            log.exception("Could not grant club pass reward L%s %s", reward.level, reward.track)
            await release(reward)
            outcome.failed += 1
            continue
        outcome.claimed += 1
        outcome.lines.append(f"Level **{reward.level}** · {text}")
    return outcome


async def grant_reward(player: Player, reward: PassLevelReward, *, guild_id: int | None = None) -> str:
    if reward.reward_type == PassRewardType.COINS:
        if reward.coins > 0:
            await player.add_money(reward.coins)
        return format_money(reward.coins)
    if reward.reward_type == PassRewardType.BALL and reward.ball_id:
        await BallInstance.objects.acreate(
            ball_id=reward.ball_id, player=player, attack_bonus=0, health_bonus=0, server_id=guild_id
        )
        ball = await Ball.objects.filter(pk=reward.ball_id).afirst()
        return reward_text(reward, ball.country if ball else None)
    if reward.reward_type == PassRewardType.RANDOM_COMMON:
        ball = pick_common_ball(await fetch_all_balls())
        if ball is None:
            raise RuntimeError("no clubball available for random_common")
        await BallInstance.objects.acreate(ball=ball, player=player, attack_bonus=0, health_bonus=0, server_id=guild_id)
        return f"**{ball.country}** (random common)"
    return "nothing"


async def claim_pass_rewards(player: Player, *, guild_id: int | None = None) -> ClaimOutcome | None:
    """Claim every unlocked, unclaimed reward. None when no season is running."""
    progress = await get_pass_progress(player)
    if progress is None:
        return None
    season = progress.season
    rewards = [r async for r in PassLevelReward.objects.filter(season=season, level__lte=progress.level)]
    claimed = {
        (level, track)
        async for level, track in PassRewardClaim.objects.filter(player=player, season=season).values_list(
            "level", "track"
        )
    }
    todo = unlocked_rewards(rewards, progress.level, progress.premium, claimed)

    async def try_claim(reward: PassLevelReward) -> bool:
        try:
            await PassRewardClaim.objects.acreate(player=player, season=season, level=reward.level, track=reward.track)
        except IntegrityError:
            return False
        return True

    async def grant(reward: PassLevelReward) -> str:
        return await grant_reward(player, reward, guild_id=guild_id)

    async def release(reward: PassLevelReward) -> None:
        await PassRewardClaim.objects.filter(
            player=player, season=season, level=reward.level, track=reward.track
        ).adelete()

    return await run_claims(todo, try_claim, grant, release)
