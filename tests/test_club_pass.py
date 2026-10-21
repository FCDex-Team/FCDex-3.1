from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from fcdex_3_1.fcdex_ext import club_pass_logic as cp


def test_xp_tables_match_spec():
    assert [cp.xp_for_next(level - 1, "premium") for level in (1, 10, 11, 19, 20, 29, 30, 39, 40, 45, 46, 49, 50)] == [
        100, 100, 250, 250, 400, 400, 650, 650, 900, 900, 1600, 1600, 2000
    ]  # fmt: skip
    assert [cp.xp_for_next(level - 1, "normal") for level in (1, 10, 11, 29, 30, 39, 40, 45, 46, 49, 50)] == [
        350, 350, 650, 650, 900, 900, 1600, 1600, 2100, 2100, 2500
    ]  # fmt: skip


def test_total_xp_to_max():
    assert cp.xp_for_level(50, "premium") == 1000 + 9 * 250 + 10 * 400 + 10 * 650 + 6 * 900 + 4 * 1600 + 2000
    assert cp.xp_for_level(50, "normal") == 3500 + 19 * 650 + 10 * 900 + 6 * 1600 + 4 * 2100 + 2500


@pytest.mark.parametrize("track", ["normal", "premium"])
def test_level_for_xp_boundaries(track):
    assert cp.level_for_xp(0, track) == 0
    first = cp.xp_for_level(1, track)
    assert cp.level_for_xp(first - 1, track) == 0
    assert cp.level_for_xp(first, track) == 1
    top = cp.xp_for_level(50, track)
    assert cp.level_for_xp(top - 1, track) == 49
    assert cp.level_for_xp(top, track) == 50
    assert cp.level_for_xp(top * 10, track) == 50  # capped
    assert cp.xp_for_next(50, track) == 0


def test_premium_levels_faster():
    assert cp.level_for_xp(1000, "premium") == 10
    assert cp.level_for_xp(1000, "normal") == 2


def test_catch_xp_interpolates_on_rarity():
    assert cp.catch_xp_for_rarity(1.0, 1.0, 100.0) == cp.CATCH_XP_MAX
    assert cp.catch_xp_for_rarity(100.0, 1.0, 100.0) == cp.CATCH_XP_MIN
    mid = cp.catch_xp_for_rarity(50.5, 1.0, 100.0)
    assert cp.CATCH_XP_MIN < mid < cp.CATCH_XP_MAX
    assert cp.catch_xp_for_rarity(None, 1.0, 100.0) == cp.CATCH_XP_FALLBACK
    assert cp.catch_xp_for_rarity(5.0, 7.0, 7.0) == cp.CATCH_XP_FALLBACK


def test_season_club_bonus():
    assert cp.apply_club_bonus(100, False) == 100
    assert cp.apply_club_bonus(100, True) == 150


def test_default_rewards_shape():
    rewards = cp.default_rewards()
    normal = {r.level: r for r in rewards if r.track == "normal"}
    premium = {r.level: r for r in rewards if r.track == "premium"}
    assert normal[1].reward_type == "random_common"
    assert all(level not in normal for level in (2, 3, 4, 5, 7, 8, 9, 10))
    assert normal[6].reward_type == "coins" and normal[6].coins == 1000
    assert normal[50].reward_type == "random_common"
    assert premium[6].coins > normal[6].coins
    assert all(1 <= r.level <= 50 for r in rewards)
    assert len({(r.level, r.track) for r in rewards}) == len(rewards)


def test_add_months_clamps_day():
    assert cp.add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert cp.add_months(datetime(2026, 11, 15, tzinfo=UTC), 3) == datetime(2027, 2, 15, tzinfo=UTC)


def test_parse_months():
    assert cp.parse_months(" 3 ") == 3
    for bad in ("0", "25", "x"):
        with pytest.raises(ValueError):
            cp.parse_months(bad)


def test_parse_reward_spec():
    assert cp.parse_reward_spec("6", "Normal", "coins", "1,500") == cp.RewardSpec(6, "normal", "coins", coins=1500)
    assert cp.parse_reward_spec("50", "premium", "ball", "Arsenal").ball_query == "Arsenal"
    assert cp.parse_reward_spec("2", "normal", "random common", "").reward_type == "random_common"
    for args in (("0", "normal", "none", ""), ("5", "gold", "none", ""), ("5", "normal", "coins", "abc"),
                 ("5", "normal", "ball", ""), ("5", "normal", "cake", "")):  # fmt: skip
        with pytest.raises(ValueError):
            cp.parse_reward_spec(*args)


def _reward(level, track="normal", kind="coins", coins=100):
    return SimpleNamespace(level=level, track=track, reward_type=kind, coins=coins)


def test_unlocked_rewards_filters():
    rewards = [_reward(1), _reward(2, kind="none"), _reward(3), _reward(4, "premium"), _reward(9)]
    got = cp.unlocked_rewards(rewards, 5, False, {(1, "normal")})
    assert [(r.level, r.track) for r in got] == [(3, "normal")]
    got = cp.unlocked_rewards(rewards, 5, True, set())
    assert [(r.level, r.track) for r in got] == [(1, "normal"), (3, "normal"), (4, "premium")]


def test_run_claims_is_idempotent():
    rewards = [_reward(1), _reward(6)]
    taken: set[tuple[int, str]] = set()
    paid: list[int] = []

    async def try_claim(r):
        key = (r.level, r.track)
        if key in taken:
            return False
        taken.add(key)
        return True

    async def grant(r):
        paid.append(r.level)
        return "ok"

    async def release(r):
        taken.discard((r.level, r.track))

    async def twice():
        return await asyncio.gather(
            cp.run_claims(rewards, try_claim, grant, release), cp.run_claims(rewards, try_claim, grant, release)
        )

    first, second = asyncio.run(twice())
    assert first.claimed + second.claimed == 2
    assert sorted(paid) == [1, 6]


def test_run_claims_releases_on_failure():
    taken: set[tuple[int, str]] = set()

    async def try_claim(r):
        taken.add((r.level, r.track))
        return True

    async def grant(r):
        raise RuntimeError("boom")

    async def release(r):
        taken.discard((r.level, r.track))

    outcome = asyncio.run(cp.run_claims([_reward(1)], try_claim, grant, release))
    assert outcome.failed == 1 and outcome.claimed == 0 and not taken


def test_mark_awarded_dedupes():
    cp.reset_awarded()
    assert cp.mark_awarded(7) is True
    assert cp.mark_awarded(7) is False
    assert cp.mark_awarded(8) is True
