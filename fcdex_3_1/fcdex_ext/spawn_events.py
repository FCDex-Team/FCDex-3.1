"""Rare spawn variants (twin and match spawns): rolling, picking and tuning.

Everything here is plain logic with no Discord objects, so it can be tested without a bot.
"""

from __future__ import annotations

import random
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from fcdex_3_1.fcdex_ext.match_logic import card_power
from fcdex_3_1.models import SpawnEventConfig

if TYPE_CHECKING:
    from bd_models.models import Ball

TWIN_TIMEOUT_SECONDS = 180
MATCH_TIMEOUT_SECONDS = 300
# A match reward is drawn from the closest rarer rarity tiers until at least this many clubballs are available.
MATCH_REWARD_MIN_POOL = 6
# The spawn settings are read when a spawn happens, so a short cache is plenty fresh.
CONFIG_TTL_SECONDS = 30.0


class SpawnKind(StrEnum):
    NORMAL = "normal"
    TWIN = "twin"
    MATCH = "match"


@dataclass(frozen=True, slots=True)
class SpawnRates:
    """Percent chance, per natural spawn, that it becomes a twin or a match spawn."""

    twin: float = 0.0
    match: float = 0.0


def _clamp_percent(value: float | int | None) -> float:
    try:
        number = float(value if value is not None else 0)
    except (TypeError, ValueError):
        return 0.0
    if number != number:  # NaN
        return 0.0
    return max(0.0, min(100.0, number))


def spawn_rates(config: SpawnEventConfig) -> SpawnRates:
    """Effective rates for a config row. Disabled kinds count as 0 and the total never exceeds 100."""
    twin = _clamp_percent(config.twin_chance) if config.twin_enabled else 0.0
    match = _clamp_percent(config.match_chance) if config.match_enabled else 0.0
    total = twin + match
    if total > 100.0:
        twin, match = twin * 100.0 / total, match * 100.0 / total
    return SpawnRates(twin=twin, match=match)


def roll_spawn_kind(rates: SpawnRates, rng: random.Random | None = None) -> SpawnKind:
    """One roll decides what a natural spawn becomes: the rare match first, then twin, otherwise normal."""
    roll = (rng or random).random() * 100.0
    if roll < rates.match:
        return SpawnKind.MATCH
    if roll < rates.match + rates.twin:
        return SpawnKind.TWIN
    return SpawnKind.NORMAL


def _weighted_choice(items: Sequence[Ball], rng: random.Random | None) -> Ball:
    source = rng or random
    weights = [max(float(item.rarity), 0.0) for item in items]
    if sum(weights) <= 0:
        return source.choice(list(items))
    return source.choices(list(items), weights=weights, k=1)[0]


def pick_match_original(population: Sequence[Ball], rng: random.Random | None = None, *, attempts: int = 8) -> Ball:
    """The clubball a match spawn is played against, drawn like a normal spawn.

    The draw is repeated a few times to avoid the rare case of an original with nothing rarer to give.
    """
    spawnable = [ball for ball in population if ball.enabled]
    if not spawnable:
        raise ValueError("A match spawn needs at least one spawnable clubball.")
    original = _weighted_choice(spawnable, rng)
    for _ in range(attempts):
        if rarer_reward_pool(original, spawnable):
            break
        original = _weighted_choice(spawnable, rng)
    return original


def pick_distinct_pair(population: Sequence[Ball], rng: random.Random | None = None) -> tuple[Ball, Ball]:
    """Two different spawnable clubballs, each drawn with the usual rarity weighting."""
    spawnable = [ball for ball in population if ball.enabled]
    if len(spawnable) < 2:
        raise ValueError("A twin spawn needs at least two spawnable clubballs.")
    first = _weighted_choice(spawnable, rng)
    second = _weighted_choice([ball for ball in spawnable if ball.pk != first.pk], rng)
    return first, second


def rarer_reward_pool(
    original: Ball, population: Sequence[Ball], *, min_size: int = MATCH_REWARD_MIN_POOL
) -> list[Ball]:
    """Clubballs rarer than `original`, closest rarity tiers first.

    A lower `rarity` value means a rarer clubball (it is the spawn weight). Whole tiers are kept together so
    clubballs sharing a rarity have the same odds, and tiers are added until the pool holds `min_size` clubballs.
    """
    tiers: dict[float, list[Ball]] = {}
    for ball in population:
        if ball.enabled and ball.pk != original.pk and ball.rarity < original.rarity:
            tiers.setdefault(ball.rarity, []).append(ball)
    pool: list[Ball] = []
    for rarity in sorted(tiers, reverse=True):
        pool.extend(tiers[rarity])
        if len(pool) >= min_size:
            break
    return pool


def pick_match_reward(original: Ball, population: Sequence[Ball], rng: random.Random | None = None) -> Ball:
    """The prize for winning a match spawn: a rarer clubball, or `original` when nothing is rarer."""
    pool = rarer_reward_pool(original, population)
    return (rng or random).choice(pool) if pool else original


def match_target_power(attack: int, health: int, difficulty_percent: int) -> int:
    """Opponent strength: the spawned clubball's base power scaled by the configured difficulty."""
    return int(card_power(attack, health) * max(int(difficulty_percent), 1) / 100)


_config_cache: tuple[float, SpawnEventConfig] | None = None


async def get_spawn_config(*, max_age: float = CONFIG_TTL_SECONDS) -> SpawnEventConfig:
    """The singleton SpawnEventConfig row (created on first use), cached briefly."""
    global _config_cache
    now = time.monotonic()
    if _config_cache is not None and now - _config_cache[0] < max_age:
        return _config_cache[1]
    config, _ = await SpawnEventConfig.objects.aget_or_create(pk=1)
    _config_cache = (now, config)
    return config


def invalidate_spawn_config() -> None:
    global _config_cache
    _config_cache = None
