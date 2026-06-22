from __future__ import annotations

from fcdex_3_1.fcdex_ext.achievement_admin_util import (
    _TYPE_VALUES,
    normalize_achievement_type,
    parse_achievement_extras,
    parse_bool_field,
)


def test_normalize_type_accepts_aliases() -> None:
    assert normalize_achievement_type("Battles Won") == "battles_won"
    assert normalize_achievement_type("tournament-win") == "tournament_win"


def test_parse_bool() -> None:
    assert parse_bool_field("yes") is True
    assert parse_bool_field("NO") is False
    assert parse_bool_field(None, default=True) is True
    assert parse_bool_field("", default=False) is False


def test_achievement_type_values_cover_admin_hints() -> None:
    expected = {"battles_won", "merges", "tournament_win", "tournament_participate", "balls_owned", "custom"}
    assert _TYPE_VALUES == expected


def test_parse_achievement_extras_combined() -> None:
    extras, err = parse_achievement_extras("coins=1000, ball=42, emoji=🏆, hidden=yes, enabled=no")
    assert err is None
    assert extras is not None
    assert extras.reward_money == 1000
    assert extras.reward_ball_raw == "42"
    assert extras.hidden is True
    assert extras.enabled is False


def test_parse_achievement_extras_rejects_bad_coins() -> None:
    extras, err = parse_achievement_extras("coins=-1")
    assert extras is None
    assert err is not None
