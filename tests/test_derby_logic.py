from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime

import pytest

from fcdex_3_1.fcdex_ext.derby_logic import (
    DEFAULT_DAILY_LIMIT,
    DEFAULT_FORMATION,
    FORMATION_ORDER,
    FORMATIONS,
    POSITIONS,
    SQUAD_SIZE,
    ActiveDerbies,
    DerbyRanges,
    LayoutPicker,
    check_add,
    daily_limit_message,
    daily_limit_reached,
    derby_highlights,
    format_missing,
    get_formation,
    is_complete,
    next_reset_delta,
    normalize_position,
    ranges_from_config,
    roll_rewards,
    slots_outside,
    squad_size,
    utc_day_start,
    validate_challenge,
    winner_side,
)


class _Config:
    winner_coins_min = 150
    winner_coins_max = 300
    loser_coins = 50
    winner_xp_min = 20
    winner_xp_max = 30
    loser_xp = 10
    daily_limit = 12


# -- formations ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", FORMATION_ORDER)
def test_every_formation_has_eleven_players_and_one_keeper(key):
    formation = FORMATIONS[key]
    assert formation.total == SQUAD_SIZE
    assert formation.count("GK") == 1
    assert sum(formation.count(p) for p in POSITIONS) == SQUAD_SIZE
    assert len(formation.slot_keys()) == SQUAD_SIZE


def test_slot_counts_follow_the_formation_name():
    assert (
        get_formation("4-3-3").count("DF"),
        get_formation("4-3-3").count("MF"),
        get_formation("4-3-3").count("ST"),
    ) == (4, 3, 3)
    assert get_formation("3-5-2").count("MF") == 5
    assert get_formation("5-3-2").count("DF") == 5
    wide = get_formation("4-2-3-1")
    assert (wide.count("MF"), wide.count("ST")) == (5, 1)


def test_layout_has_a_unique_coordinate_per_slot_inside_the_pitch():
    for formation in FORMATIONS.values():
        points = formation.layout()
        assert {(p, s) for p, s, _, _ in points} == set(formation.slot_keys())
        assert len({(round(x, 3), round(y, 3)) for _, _, x, y in points}) == SQUAD_SIZE
        assert all(0 < x < 1 and 0 < y < 1 for _, _, x, y in points)


def test_goalkeeper_is_at_the_back_and_strikers_up_front():
    points = {(p, s): y for p, s, _, y in get_formation("4-4-2").layout()}
    assert points[("GK", 0)] > points[("DF", 0)] > points[("MF", 0)] > points[("ST", 0)]


def test_unknown_formation_falls_back_to_default():
    assert get_formation("9-9-9").key == DEFAULT_FORMATION
    assert get_formation(None).key == DEFAULT_FORMATION


def test_normalize_position():
    assert normalize_position(" gk ") == "GK"
    assert normalize_position("wing") is None


# -- squad and duplicates --------------------------------------------------------------------------------------


def test_add_fills_first_free_slot():
    formation = get_formation("4-3-3")
    squad = {("DF", 0): 10, ("DF", 1): 11}
    verdict = check_add(formation, squad, "DF", 12)
    assert verdict.ok and verdict.slot == 2 and not verdict.replaces


def test_same_club_cannot_be_added_twice_even_in_another_position():
    formation = get_formation("4-3-3")
    squad = {("DF", 0): 10}
    verdict = check_add(formation, squad, "ST", 10)
    assert not verdict.ok
    assert "once" in verdict.reason
    assert not check_add(formation, squad, "DF", 10, slot=1).ok


def test_full_position_needs_an_explicit_slot_to_replace():
    formation = get_formation("5-3-2")
    squad = {("ST", 0): 1, ("ST", 1): 2}
    assert not check_add(formation, squad, "ST", 3).ok
    replace = check_add(formation, squad, "ST", 3, slot=2)
    assert replace.ok and replace.replaces and replace.slot == 1


def test_slot_must_exist_in_the_formation():
    formation = get_formation("4-3-3")
    assert not check_add(formation, {}, "GK", 1, slot=2).ok
    assert not check_add(formation, {}, "MF", 1, slot=4).ok
    assert not check_add(formation, {}, "XX", 1).ok


def test_squad_completeness():
    formation = get_formation("4-4-2")
    squad = {key: i for i, key in enumerate(formation.slot_keys())}
    assert is_complete(formation, squad)
    del squad[("MF", 3)]
    assert not is_complete(formation, squad)
    assert squad_size(formation, squad) == 10
    assert format_missing(formation, squad) == "MF4"


def test_slots_outside_new_formation_are_reported():
    old = get_formation("5-3-2")
    squad = {key: i for i, key in enumerate(old.slot_keys())}
    new = get_formation("4-4-2")
    assert sorted(slots_outside(new, squad)) == [("DF", 4)]
    assert squad_size(new, squad) == 10


# -- layout picker ---------------------------------------------------------------------------------------------


def test_picker_cycles_and_accepts_the_shown_formation():
    picker = LayoutPicker()
    assert picker.current == FORMATION_ORDER[0]
    assert picker.next() == FORMATION_ORDER[1]
    assert picker.position_text == f"2/{len(FORMATION_ORDER)}"
    assert picker.accepted is None
    assert picker.accept() == FORMATION_ORDER[1]
    assert picker.accepted == FORMATION_ORDER[1]


def test_picker_wraps_around():
    picker = LayoutPicker()
    for _ in range(len(FORMATION_ORDER)):
        picker.next()
    assert picker.current == FORMATION_ORDER[0]


def test_picker_starts_at_the_saved_formation():
    assert LayoutPicker.starting_at("3-5-2").current == "3-5-2"
    assert LayoutPicker.starting_at("nope").current == FORMATION_ORDER[0]


# -- rewards ---------------------------------------------------------------------------------------------------


def test_winner_rolls_stay_inside_the_ranges():
    ranges = ranges_from_config(_Config())
    rng = random.Random(7)
    for _ in range(200):
        reward = roll_rewards(ranges, won=True, rng=rng)
        assert 150 <= reward.coins <= 300
        assert 20 <= reward.xp <= 30


def test_winner_xp_roll_reaches_both_ends():
    ranges = DerbyRanges(winner_xp=(20, 30))
    seen = {roll_rewards(ranges, won=True, rng=random.Random(seed)).xp for seed in range(300)}
    assert min(seen) == 20 and max(seen) == 30


def test_loser_gets_flat_amounts():
    reward = roll_rewards(ranges_from_config(_Config()), won=False)
    assert (reward.coins, reward.xp) == (50, 10)


def test_ranges_fix_swapped_or_negative_values():
    config = _Config()
    config.winner_coins_min, config.winner_coins_max = 300, 150
    config.daily_limit = 0
    ranges = ranges_from_config(config)
    assert ranges.winner_coins == (150, 300)
    assert ranges.daily_limit == 1


# -- daily cap -------------------------------------------------------------------------------------------------


def test_cap_defaults_to_twelve():
    assert DEFAULT_DAILY_LIMIT == 12
    assert not daily_limit_reached(11)
    assert daily_limit_reached(12)
    assert daily_limit_reached(13)
    assert daily_limit_reached(3, limit=3)


def test_utc_day_start_ignores_local_offsets():
    moment = datetime(2026, 5, 6, 23, 59, tzinfo=UTC)
    assert utc_day_start(moment) == datetime(2026, 5, 6, tzinfo=UTC)
    assert next_reset_delta(moment).total_seconds() == 60


def test_limit_message_mentions_limit_reset_and_who():
    message = daily_limit_message(datetime(2026, 5, 6, 12, 0, tzinfo=UTC), limit=12, who="**Sam** has")
    assert "12" in message and "12h 0m" in message and "Sam" in message


# -- challenge rules -------------------------------------------------------------------------------------------


def test_no_self_challenge_and_no_bots():
    assert validate_challenge(1, 1, opponent_is_bot=False)
    assert validate_challenge(1, 2, opponent_is_bot=True)
    assert validate_challenge(1, 2, opponent_is_bot=False) is None


def test_one_active_derby_per_player():
    active = ActiveDerbies()
    assert active.start(1, 2)
    assert active.busy(2)
    assert not active.start(2, 3)
    assert not active.busy(3)
    active.finish(1, 2)
    assert active.start(2, 3)


def test_winner_side():
    assert winner_side(3, 0) == 1
    assert winner_side(0, 2) == 2
    assert winner_side(0, 0) is None
    assert winner_side(1, 1) is None


def test_highlights_keep_the_latest_eliminations():
    lines = [f"Turn {i}: A's x has eliminated B's y{i}!" if i % 2 else f"Turn {i}: missed" for i in range(1, 60)]
    shown = derby_highlights(lines, limit=5)
    assert len(shown) == 5
    assert all("eliminated" in line for line in shown)
    assert shown[-1] == lines[-2] or shown[-1] == lines[-1]


# -- bridge and admin parsing ----------------------------------------------------------------------------------


def test_pass_bridge_degrades_without_club_pass(monkeypatch):
    from fcdex_3_1.fcdex_ext import derby_pass_bridge

    monkeypatch.setattr(derby_pass_bridge, "_load", lambda: None)
    outcome = asyncio.run(derby_pass_bridge.grant_derby_xp(object(), 25))
    assert not outcome.available
    assert outcome.text == derby_pass_bridge.UNAVAILABLE
    status = asyncio.run(derby_pass_bridge.club_pass_status(object()))
    assert not status.available and status.milestones == []


def test_pass_bridge_reads_a_club_pass_module(monkeypatch):
    from types import SimpleNamespace

    from fcdex_3_1.fcdex_ext import derby_pass_bridge

    async def grant(player, amount):
        return SimpleNamespace(level=4, levels_gained=1)

    async def progress(player):
        return SimpleNamespace(level=4, xp=120, xp_to_next=30, upcoming=[SimpleNamespace(level=5, label="Pack")])

    module = SimpleNamespace(grant_pass_xp=grant, get_pass_progress=progress)
    monkeypatch.setattr(derby_pass_bridge, "_load", lambda: module)
    outcome = asyncio.run(derby_pass_bridge.grant_derby_xp(object(), 25))
    assert outcome.available and outcome.level == 4 and outcome.levels_gained == 1
    assert "+25 XP" in outcome.text
    status = asyncio.run(derby_pass_bridge.club_pass_status(object()))
    assert status.level == 4 and status.milestones[0].label == "Pack"


def test_admin_range_parsing():
    from fcdex_3_1.fcdex_ext.derby_admin_views import parse_amount, parse_range

    assert parse_range("150-300", "x") == (150, 300)
    assert parse_range(" 40 ", "x") == (40, 40)
    for bad in ("", "a-b", "300-150", "-5", "1-2-3"):
        with pytest.raises(ValueError):
            parse_range(bad, "x")
    assert parse_amount("12", "x", minimum=1) == 12
    with pytest.raises(ValueError):
        parse_amount("0", "x", minimum=1)


def test_leaderboard_has_a_derby_metric():
    from fcdex_3_1.fcdex_ext.leaderboard_logic import LeaderboardMetric, stat_lookup

    assert LeaderboardMetric("derby_wins") == LeaderboardMetric.DERBY_WINS
    assert stat_lookup(LeaderboardMetric.DERBY_WINS) == "derby_stats__wins"
    assert stat_lookup(LeaderboardMetric.BATTLES_WON) == "fcdex_stats__battles_won"
