from __future__ import annotations

import asyncio
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from fcdex_3_1.fcdex_ext import spawn_events
from fcdex_3_1.fcdex_ext.spawn_events import (
    MATCH_REWARD_MIN_POOL,
    SpawnKind,
    SpawnRates,
    get_spawn_config,
    invalidate_spawn_config,
    match_target_power,
    pick_distinct_pair,
    pick_match_original,
    pick_match_reward,
    rarer_reward_pool,
    roll_spawn_kind,
    spawn_rates,
)


def ball(pk: int, rarity: float, *, enabled: bool = True, attack: int = 100, health: int = 100) -> SimpleNamespace:
    return SimpleNamespace(pk=pk, rarity=rarity, enabled=enabled, attack=attack, health=health, country=f"Club {pk}")


def config(**overrides) -> SimpleNamespace:
    values = {
        "twin_enabled": True,
        "twin_chance": 10.0,
        "match_enabled": True,
        "match_chance": 2.0,
        "match_difficulty": 110,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FixedRandom(random.Random):
    """A Random whose `random()` replays the given values."""

    def __init__(self, *values: float):
        super().__init__(0)
        self.values = list(values)

    def random(self) -> float:
        return self.values.pop(0)


# --- rates and rolling --------------------------------------------------------------------------------------


def test_disabled_kinds_have_no_chance():
    rates = spawn_rates(config(twin_enabled=False, match_enabled=False))
    assert rates == SpawnRates(twin=0.0, match=0.0)
    assert spawn_rates(config(twin_enabled=False)).match == 2.0


def test_rates_are_clamped_to_a_valid_percentage():
    rates = spawn_rates(config(twin_chance=-5, match_chance=250))
    assert rates.twin == 0.0
    assert rates.match == 100.0
    assert spawn_rates(config(twin_chance=None, match_chance="oops")) == SpawnRates(0.0, 0.0)


def test_rates_scale_down_when_they_exceed_a_hundred_percent():
    rates = spawn_rates(config(twin_chance=90, match_chance=60))
    assert rates.twin + rates.match == pytest.approx(100.0)
    assert rates.twin / rates.match == pytest.approx(1.5)


def test_roll_splits_the_range_into_match_twin_and_normal():
    rates = SpawnRates(twin=10.0, match=2.0)
    assert roll_spawn_kind(rates, FixedRandom(0.0)) is SpawnKind.MATCH
    assert roll_spawn_kind(rates, FixedRandom(0.0199)) is SpawnKind.MATCH
    assert roll_spawn_kind(rates, FixedRandom(0.05)) is SpawnKind.TWIN
    assert roll_spawn_kind(rates, FixedRandom(0.1199)) is SpawnKind.TWIN
    assert roll_spawn_kind(rates, FixedRandom(0.12)) is SpawnKind.NORMAL
    assert roll_spawn_kind(rates, FixedRandom(0.999)) is SpawnKind.NORMAL


def test_zero_rates_never_replace_a_spawn():
    rng = random.Random(1)
    assert {roll_spawn_kind(SpawnRates(), rng) for _ in range(500)} == {SpawnKind.NORMAL}


def test_roll_frequency_follows_the_configured_rates():
    rng = random.Random(1234)
    rolls = [roll_spawn_kind(SpawnRates(twin=10.0, match=2.0), rng) for _ in range(20_000)]
    assert rolls.count(SpawnKind.TWIN) / len(rolls) == pytest.approx(0.10, abs=0.015)
    assert rolls.count(SpawnKind.MATCH) / len(rolls) == pytest.approx(0.02, abs=0.007)


def test_a_full_hundred_percent_twin_rate_always_twins():
    rng = random.Random(3)
    assert {roll_spawn_kind(SpawnRates(twin=100.0), rng) for _ in range(300)} == {SpawnKind.TWIN}


# --- picking the pair ---------------------------------------------------------------------------------------


def test_pair_is_two_different_spawnable_clubballs():
    population = [ball(1, 10), ball(2, 5), ball(3, 1), ball(4, 50, enabled=False)]
    rng = random.Random(7)
    for _ in range(200):
        first, second = pick_distinct_pair(population, rng)
        assert first.pk != second.pk
        assert first.enabled and second.enabled


def test_pair_needs_two_spawnable_clubballs():
    with pytest.raises(ValueError):
        pick_distinct_pair([ball(1, 10)])
    with pytest.raises(ValueError):
        pick_distinct_pair([ball(1, 10), ball(2, 10, enabled=False)])


def test_pair_falls_back_to_uniform_when_every_weight_is_zero():
    first, second = pick_distinct_pair([ball(1, 0), ball(2, 0), ball(3, 0)], random.Random(2))
    assert first.pk != second.pk


def test_pair_follows_rarity_weights():
    population = [ball(1, 1000), ball(2, 1)]
    rng = random.Random(5)
    firsts = [pick_distinct_pair(population, rng)[0].pk for _ in range(300)]
    assert firsts.count(1) > 280


# --- match reward -------------------------------------------------------------------------------------------


def test_reward_pool_only_holds_rarer_clubballs():
    original = ball(1, 10)
    population = [original, ball(2, 10), ball(3, 12), ball(4, 6), ball(5, 3, enabled=False), ball(6, 2)]
    pool = rarer_reward_pool(original, population, min_size=1)
    assert [b.pk for b in pool] == [4]


def test_reward_pool_widens_tier_by_tier_until_it_is_big_enough():
    original = ball(1, 100)
    tier_a = [ball(10 + i, 50) for i in range(2)]
    tier_b = [ball(20 + i, 20) for i in range(3)]
    tier_c = [ball(30 + i, 5) for i in range(4)]
    pool = rarer_reward_pool(original, [original, *tier_c, *tier_b, *tier_a], min_size=MATCH_REWARD_MIN_POOL)
    # 2 + 3 = 5 is not enough, so the whole next tier joins, but nothing rarer than that
    assert sorted(b.pk for b in pool) == sorted(b.pk for b in [*tier_a, *tier_b, *tier_c])
    smaller = rarer_reward_pool(original, [original, *tier_c, *tier_b, *tier_a], min_size=3)
    assert sorted(b.pk for b in smaller) == sorted(b.pk for b in [*tier_a, *tier_b])


def test_reward_pool_keeps_clubballs_of_one_tier_together():
    original = ball(1, 100)
    big_tier = [ball(10 + i, 40) for i in range(30)]
    far_tier = [ball(100, 1)]
    pool = rarer_reward_pool(original, [original, *big_tier, *far_tier], min_size=3)
    assert len(pool) == 30
    assert all(b.rarity == 40 for b in pool)


def test_reward_is_always_rarer_than_the_original():
    original = ball(1, 60)
    population = [original] + [ball(i, float(i)) for i in range(2, 200)]
    rng = random.Random(11)
    for _ in range(300):
        reward = pick_match_reward(original, population, rng)
        assert reward.rarity < original.rarity


def test_reward_falls_back_to_the_original_when_nothing_is_rarer():
    rarest = ball(1, 0.1)
    assert pick_match_reward(rarest, [rarest, ball(2, 5), ball(3, 9)], random.Random(1)) is rarest


class ScriptedChoices(random.Random):
    """Returns the scripted items from `choices`, in order."""

    def __init__(self, *items):
        super().__init__(0)
        self.items = list(items)

    def choices(self, population, weights=None, *, cum_weights=None, k=1):
        return [self.items.pop(0)]


def test_match_original_rerolls_when_it_has_nothing_rarer_to_give():
    rarest, common = ball(1, 0.1), ball(2, 50)
    population = [rarest, common, ball(3, 20)]
    assert pick_match_original(population, ScriptedChoices(rarest, common)) is common


def test_match_original_accepts_the_rarest_if_nothing_else_works():
    rarest = ball(1, 0.1)
    assert pick_match_original([rarest], random.Random(1)) is rarest


def test_match_original_needs_a_spawnable_clubball():
    with pytest.raises(ValueError):
        pick_match_original([ball(1, 5, enabled=False)])


def test_target_power_scales_base_stats_by_difficulty():
    assert match_target_power(100, 50, 100) == 250
    assert match_target_power(100, 50, 110) == 275
    assert match_target_power(100, 50, 200) == 500
    assert match_target_power(0, 0, 110) == 0


# --- config cache -------------------------------------------------------------------------------------------


def test_spawn_config_is_cached_until_it_expires(monkeypatch):
    invalidate_spawn_config()
    manager = MagicMock()
    manager.aget_or_create = AsyncMock(side_effect=[(config(twin_chance=1.0), False), (config(twin_chance=2.0), False)])
    monkeypatch.setattr(spawn_events, "SpawnEventConfig", SimpleNamespace(objects=manager))
    clock = iter([100.0, 110.0, 200.0])
    monkeypatch.setattr(spawn_events, "time", SimpleNamespace(monotonic=lambda: next(clock)))

    async def run():
        first = await get_spawn_config()
        cached = await get_spawn_config()
        expired = await get_spawn_config()
        return first, cached, expired

    first, cached, expired = asyncio.run(run())
    assert cached is first
    assert expired.twin_chance == 2.0
    assert manager.aget_or_create.await_count == 2
    manager.aget_or_create.assert_awaited_with(pk=1)
    invalidate_spawn_config()


def test_spawn_config_can_be_forced_fresh(monkeypatch):
    invalidate_spawn_config()
    manager = MagicMock()
    manager.aget_or_create = AsyncMock(side_effect=[(config(twin_chance=1.0), False), (config(twin_chance=9.0), False)])
    monkeypatch.setattr(spawn_events, "SpawnEventConfig", SimpleNamespace(objects=manager))

    async def run():
        await get_spawn_config()
        return await get_spawn_config(max_age=0)

    assert asyncio.run(run()).twin_chance == 9.0
    invalidate_spawn_config()
