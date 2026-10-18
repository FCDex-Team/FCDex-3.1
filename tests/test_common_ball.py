from __future__ import annotations

import random
from types import SimpleNamespace

from fcdex_3_1.fcdex_ext.rarity_logic import pick_common_ball


def ball(pk: int, rarity: float, *, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(pk=pk, country=f"Club {pk}", rarity=rarity, enabled=enabled)


def test_a_common_prize_never_comes_from_the_rarest_half_of_the_dex():
    dex = [ball(1, 0.5), ball(2, 1.0), ball(3, 5.0), ball(4, 40.0), ball(5, 80.0), ball(6, 100.0)]
    rng = random.Random(3)
    picks = {pick_common_ball(dex, rng).pk for _ in range(500)}  # type: ignore[union-attr]
    assert picks <= {4, 5, 6}
    assert {1, 2, 3}.isdisjoint(picks)


def test_the_prize_is_not_always_the_same_clubball():
    dex = [ball(1, 1.0), ball(2, 50.0), ball(3, 60.0), ball(4, 70.0)]
    rng = random.Random(8)
    picks = {pick_common_ball(dex, rng).pk for _ in range(300)}  # type: ignore[union-attr]
    assert len(picks) > 1


def test_commoner_clubballs_are_handed_out_more_often():
    dex = [ball(1, 1.0), ball(2, 10.0), ball(3, 100.0)]
    rng = random.Random(5)
    picks = [pick_common_ball(dex, rng).pk for _ in range(2_000)]  # type: ignore[union-attr]
    assert picks.count(3) > picks.count(2) * 5


def test_disabled_clubballs_are_never_handed_out():
    dex = [ball(1, 100.0, enabled=False), ball(2, 10.0), ball(3, 20.0)]
    rng = random.Random(1)
    assert {pick_common_ball(dex, rng).pk for _ in range(200)} <= {2, 3}  # type: ignore[union-attr]


def test_an_empty_or_fully_disabled_dex_has_no_prize():
    assert pick_common_ball([]) is None
    assert pick_common_ball([ball(1, 5.0, enabled=False)]) is None


def test_a_dex_with_a_single_tier_still_works():
    dex = [ball(1, 7.0), ball(2, 7.0), ball(3, 7.0)]
    rng = random.Random(2)
    assert {pick_common_ball(dex, rng).pk for _ in range(200)} == {1, 2, 3}  # type: ignore[union-attr]


def test_zero_weights_fall_back_to_a_uniform_pick():
    dex = [ball(1, 0.0), ball(2, 0.0)]
    assert pick_common_ball(dex, random.Random(4)) is not None
