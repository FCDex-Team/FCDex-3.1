from __future__ import annotations

from types import SimpleNamespace

from fcdex_3_1.fcdex_ext.merge_levels import MERGE_LEVELS, format_merge_count_mismatch, get_merge_level_config


def _preview_attack(base_attack: int, bonus: int) -> int:
    return base_attack + int(base_attack * bonus * 0.01)


def _preview_health(base_health: int, bonus: int) -> int:
    return base_health + int(base_health * bonus * 0.01)


def test_merge_level_config_values():
    assert MERGE_LEVELS[1].input_count == 10
    assert MERGE_LEVELS[7].input_count == 2
    assert MERGE_LEVELS[1].requires_common_inputs is False
    assert MERGE_LEVELS[2].requires_common_inputs is False


def test_preview_merge_stats_level_seven_is_much_stronger_than_level_one():
    ball = SimpleNamespace(attack=120, health=100, pk=1)
    level_one = get_merge_level_config(1)
    level_seven = get_merge_level_config(7)
    level_one_attack = _preview_attack(ball.attack, level_one.attack_bonus)
    level_one_health = _preview_health(ball.health, level_one.health_bonus)
    level_seven_attack = _preview_attack(ball.attack, level_seven.attack_bonus)
    level_seven_health = _preview_health(ball.health, level_seven.health_bonus)
    assert level_seven_attack > level_one_attack * 2
    assert level_seven_health > level_one_health * 2


def test_level_seven_bonus_values():
    cfg = get_merge_level_config(7)
    assert cfg.attack_bonus == 170
    assert cfg.health_bonus == 170


def test_format_merge_count_mismatch_for_commons():
    message = format_merge_count_mismatch(0, 1, 2)
    assert "10" in message
    assert "L1" in message
    assert "level 7" not in message.lower()
