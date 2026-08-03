from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fcdex_3_1.fcdex_ext.merge_levels import (
    MAX_MERGE_LEVEL,
    MERGE_LEVELS,
    detect_target_level,
    get_merge_level_config,
    resolve_merge_level_from_bonuses,
)
from fcdex_3_1.fcdex_ext.merge_limits import (
    MERGE_WEEKLY_LIMIT,
    calendar_week_bounds,
    merge_special_blocked_message,
    weekly_merge_limit_message,
    weekly_merge_limit_reached,
)
from fcdex_3_1.fcdex_ext.merge_quota import merge_quota_limit_message, merge_quota_limit_reached

ROOT = Path(__file__).resolve().parents[1]


class _MergeValidationError(Exception):
    message: str


class _MergeLogicTestModule:
    """Typing stub for dynamically loaded merge_logic used in validation tests."""

    get_merge_special: Any
    get_ball: Any
    MergeValidationError: type[_MergeValidationError]
    validate_merge_batch: Any
    get_merge_level_config: Any


class _BdModelsModelsStub(ModuleType):
    Ball: type
    BallInstance: type
    Player: type
    Special: Any
    balls: dict[int, Any]
    specials: dict[Any, Any]


class _BdModelsStub(ModuleType):
    models: _BdModelsModelsStub


class _SettingsModelsStub(ModuleType):
    settings: SimpleNamespace


class _SettingsStub(ModuleType):
    models: _SettingsModelsStub


class _DiscordStub(ModuleType):
    File: type


class _FcdexModelsMergeStub(ModuleType):
    MergeLog: Any
    MergeQuotaSettings: Any
    PlayerMergeQuota: Any


class _MergeQuotaStub(ModuleType):
    get_merge_quota_snapshot: Any
    get_merge_quota_settings: Any
    merge_quota_limit_reached: Any
    merge_quota_limit_message: Any


class _BdHelpersStub(ModuleType):
    format_instance: Any
    get_ball: Any
    instance_attack: Callable[..., Any]
    instance_health: Callable[..., Any]


class _ServicesStub(ModuleType):
    increment_stat: Any


def test_calendar_week_bounds_starts_on_monday():
    wednesday = datetime(2026, 5, 27, 15, 30, tzinfo=dt_timezone.utc)
    week_start, week_end = calendar_week_bounds(wednesday)
    assert week_start.weekday() == 0
    assert week_start == datetime(2026, 5, 25, 0, 0, tzinfo=dt_timezone.utc)
    assert week_end == week_start + timedelta(days=7)


def test_weekly_merge_limit_reached_at_five():
    assert not weekly_merge_limit_reached(4)
    assert weekly_merge_limit_reached(5)
    assert weekly_merge_limit_reached(6)


def test_weekly_merge_limit_message_mentions_limit():
    message = weekly_merge_limit_message(limit=MERGE_WEEKLY_LIMIT)
    assert str(MERGE_WEEKLY_LIMIT) in message
    assert "Monday" in message


def test_merge_special_blocked_message_mentions_special_name():
    message = merge_special_blocked_message("FCDex Merge")
    assert "FCDex Merge" in message
    assert "cannot be merged" in message


def test_merge_special_blocked_message_for_max_tier():
    message = merge_special_blocked_message("FCDex Merge", max_level=7)
    assert "level 7" in message
    assert "max tier" in message


def test_merge_level_table_has_seven_tiers_with_expected_counts():
    assert len(MERGE_LEVELS) == 7
    assert [MERGE_LEVELS[level].input_count for level in range(1, 8)] == [10, 9, 7, 5, 4, 3, 2]


def test_merge_level_bonuses_increase_each_tier():
    previous_attack = 0
    for level in range(1, MAX_MERGE_LEVEL + 1):
        cfg = get_merge_level_config(level)
        assert cfg.attack_bonus > previous_attack
        assert cfg.health_bonus == cfg.attack_bonus
        previous_attack = cfg.attack_bonus


def test_detect_target_level_from_card_count():
    assert detect_target_level(10) == 1
    assert detect_target_level(9) == 2
    assert detect_target_level(7) == 3
    assert detect_target_level(8) is None
    assert detect_target_level(2) == 7
    assert detect_target_level(6) is None


def test_resolve_merge_level_from_bonuses():
    cfg = get_merge_level_config(4)
    assert resolve_merge_level_from_bonuses(cfg.attack_bonus, cfg.health_bonus) == 4
    assert resolve_merge_level_from_bonuses(0, 0) is None


def _load_merge_logic_for_validation_tests():
    """Load merge_logic with lightweight stubs so validate_merge_batch can be tested."""
    bd_models_models = _BdModelsModelsStub("bd_models.models")
    bd_models_models.Ball = object
    bd_models_models.BallInstance = object
    bd_models_models.Player = object
    bd_models_models.balls = {1: SimpleNamespace(pk=1, enabled=True, rarity=10, attack=100, health=80)}
    bd_models_models.specials = {42: SimpleNamespace(pk=42, name="FCDex Merge")}

    special_manager = MagicMock()
    special_manager.filter.return_value.afirst = AsyncMock(return_value=None)
    bd_models_models.Special = SimpleNamespace(objects=special_manager)

    bd_models = _BdModelsStub("bd_models")
    bd_models.models = bd_models_models

    settings_models = _SettingsModelsStub("settings.models")
    settings_models.settings = SimpleNamespace(
        plural_collectible_name="clubballs", max_attack_bonus=10, max_health_bonus=10
    )
    settings_mod = _SettingsStub("settings")
    settings_mod.models = settings_models

    discord_mod = _DiscordStub("discord")
    discord_mod.File = object

    merge_log_manager = MagicMock()
    merge_log_filter = MagicMock()
    merge_log_filter.acount = AsyncMock(return_value=0)
    merge_log_filter.aexists = AsyncMock(return_value=False)
    merge_log_manager.filter.return_value = merge_log_filter
    fcdex_models = _FcdexModelsMergeStub("fcdex_3_1.models")
    fcdex_models.MergeLog = SimpleNamespace(objects=merge_log_manager)
    fcdex_models.MergeQuotaSettings = SimpleNamespace(objects=MagicMock())
    fcdex_models.PlayerMergeQuota = SimpleNamespace(objects=MagicMock())

    merge_quota = _MergeQuotaStub("fcdex_3_1.fcdex_ext.merge_quota")

    async def _fake_snapshot(player):
        used = await merge_log_manager.filter.return_value.acount()
        return SimpleNamespace(
            used=used,
            cap=MERGE_WEEKLY_LIMIT,
            period_start=datetime(2026, 5, 25, tzinfo=dt_timezone.utc),
            period_end=datetime(2026, 6, 1, tzinfo=dt_timezone.utc),
            premium_bonus=0,
            cap_override=None,
        )

    merge_quota.get_merge_quota_snapshot = _fake_snapshot
    merge_quota.get_merge_quota_settings = AsyncMock(
        return_value=SimpleNamespace(weekly_cap=MERGE_WEEKLY_LIMIT, period_days=7)
    )
    merge_quota.merge_quota_limit_reached = merge_quota_limit_reached
    merge_quota.merge_quota_limit_message = merge_quota_limit_message

    bd_helpers = _BdHelpersStub("fcdex_3_1.fcdex_ext.bd_helpers")
    bd_helpers.format_instance = AsyncMock(return_value="label")
    bd_helpers.get_ball = AsyncMock(
        return_value=SimpleNamespace(pk=1, rarity=10, attack=100, health=80, country="Test Club")
    )
    bd_helpers.instance_attack = lambda instance, ball: ball.attack
    bd_helpers.instance_health = lambda instance, ball: ball.health

    services = _ServicesStub("fcdex_3_1.fcdex_ext.services")
    services.increment_stat = AsyncMock()

    stubs: dict[str, ModuleType] = {
        "bd_models": bd_models,
        "bd_models.models": bd_models_models,
        "settings": settings_mod,
        "settings.models": settings_models,
        "discord": discord_mod,
        "fcdex_3_1.models": fcdex_models,
        "fcdex_3_1.fcdex_ext.bd_helpers": bd_helpers,
        "fcdex_3_1.fcdex_ext.services": services,
        "fcdex_3_1.fcdex_ext.merge_levels": importlib.import_module("fcdex_3_1.fcdex_ext.merge_levels"),
        "fcdex_3_1.fcdex_ext.merge_config": importlib.import_module("fcdex_3_1.fcdex_ext.merge_config"),
        "fcdex_3_1.fcdex_ext.merge_quota": merge_quota,
    }

    saved: dict[str, ModuleType | None] = {}
    for name, module in stubs.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module

    sys.modules.pop("fcdex_3_1.fcdex_ext.merge_logic", None)

    path = ROOT / "fcdex_3_1" / "fcdex_ext" / "merge_logic.py"
    spec = importlib.util.spec_from_file_location("fcdex_merge_logic_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    _restore_modules(saved)

    return cast(_MergeLogicTestModule, module), merge_log_manager


def _restore_modules(saved: dict[str, ModuleType | None]) -> None:
    for name, previous in saved.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def _make_instance(
    *,
    pk: int,
    player_id: int,
    ball_id: int = 1,
    special_id: int | None = None,
    attack_bonus: int = 0,
    health_bonus: int = 0,
) -> SimpleNamespace:
    instance = SimpleNamespace(
        pk=pk,
        player_id=player_id,
        deleted=False,
        special_id=special_id,
        ball_id=ball_id,
        attack_bonus=attack_bonus,
        health_bonus=health_bonus,
    )
    instance.is_locked = AsyncMock(return_value=False)
    return instance


def test_validate_merge_batch_two_commons_suggests_forge_l1_not_l7():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    instances = [_make_instance(pk=1, player_id=1, ball_id=1), _make_instance(pk=2, player_id=1, ball_id=1)]

    with pytest.raises(merge_logic.MergeValidationError) as exc:
        asyncio.run(merge_logic.validate_merge_batch(player, instances))

    message = exc.value.message.lower()
    assert "forge l1" in message or "l1" in message
    assert "level 7" not in message
    assert "level 6" not in message
    assert "10" in exc.value.message


def test_validate_merge_batch_blocks_different_clubballs():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    instances = [_make_instance(pk=i, player_id=1, ball_id=1 if i <= 5 else 2) for i in range(1, 11)]
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))

    with pytest.raises(merge_logic.MergeValidationError) as exc:
        asyncio.run(merge_logic.validate_merge_batch(player, instances))

    assert "same clubball" in exc.value.message


def test_validate_merge_batch_two_commons_hint_forge_l1_not_l7():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    instances = [_make_instance(pk=1, player_id=1, ball_id=1), _make_instance(pk=2, player_id=1, ball_id=1)]
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))

    with pytest.raises(merge_logic.MergeValidationError) as exc:
        asyncio.run(merge_logic.validate_merge_batch(player, instances))

    message = exc.value.message.lower()
    assert "forge l1" in message or "forge **l1**" in exc.value.message.lower()
    assert "level 6" not in message
    assert "level 7" not in message


def test_validate_merge_batch_level_one_requires_ten_commons():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    instances = [_make_instance(pk=i, player_id=1, ball_id=1) for i in range(1, 11)]

    assert asyncio.run(merge_logic.validate_merge_batch(player, instances)) == 1


def test_validate_merge_batch_level_one_accepts_rare_ball():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    merge_logic.get_ball = AsyncMock(return_value=SimpleNamespace(pk=1, rarity=99, enabled=True, attack=100, health=80))
    instances = [_make_instance(pk=i, player_id=1, ball_id=1) for i in range(1, 11)]

    assert asyncio.run(merge_logic.validate_merge_batch(player, instances)) == 1


def test_validate_merge_batch_level_two_requires_nine_level_one_forge_cards():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    cfg = merge_logic.get_merge_level_config(1)
    instances = [
        _make_instance(
            pk=i, player_id=1, ball_id=1, special_id=42, attack_bonus=cfg.attack_bonus, health_bonus=cfg.health_bonus
        )
        for i in range(1, 10)
    ]

    assert asyncio.run(merge_logic.validate_merge_batch(player, instances)) == 2


def test_forge_bucket_level_includes_any_enabled_without_special():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    merge_logic.get_ball = AsyncMock(return_value=SimpleNamespace(pk=1, rarity=99, enabled=True, attack=100, health=80))
    instance = _make_instance(pk=1, player_id=1, ball_id=1, special_id=None)

    assert asyncio.run(merge_logic.forge_bucket_level_for_instance(instance)) == 0


def test_forge_bucket_level_excludes_disabled_without_special():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    merge_logic.get_ball = AsyncMock(
        return_value=SimpleNamespace(pk=1, rarity=99, enabled=False, attack=100, health=80)
    )
    instance = _make_instance(pk=1, player_id=1, ball_id=1, special_id=None)

    assert asyncio.run(merge_logic.forge_bucket_level_for_instance(instance)) is None


def test_validate_merge_batch_level_one_rejects_special_common():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    instances = [_make_instance(pk=i, player_id=1, ball_id=1, special_id=99) for i in range(1, 11)]

    with pytest.raises(merge_logic.MergeValidationError) as exc:
        asyncio.run(merge_logic.validate_merge_batch(player, instances))

    assert "without any special" in exc.value.message.lower()


def test_validate_merge_batch_blocks_max_tier_inputs():
    merge_logic, _ = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    cfg = merge_logic.get_merge_level_config(MAX_MERGE_LEVEL)
    instances = [
        _make_instance(
            pk=i, player_id=1, ball_id=1, special_id=42, attack_bonus=cfg.attack_bonus, health_bonus=cfg.health_bonus
        )
        for i in range(1, 3)
    ]

    with pytest.raises(merge_logic.MergeValidationError) as exc:
        asyncio.run(merge_logic.validate_merge_batch(player, instances))

    assert "max tier" in exc.value.message


def test_validate_merge_batch_allows_fifth_weekly_merge():
    merge_logic, merge_log_manager = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    merge_log_manager.filter.return_value.acount = AsyncMock(return_value=4)
    cfg = merge_logic.get_merge_level_config(6)
    instances = [
        _make_instance(
            pk=i, player_id=1, ball_id=1, special_id=42, attack_bonus=cfg.attack_bonus, health_bonus=cfg.health_bonus
        )
        for i in range(1, 3)
    ]

    assert asyncio.run(merge_logic.validate_merge_batch(player, instances)) == 7


def test_validate_merge_batch_blocks_sixth_weekly_merge():
    merge_logic, merge_log_manager = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    merge_log_manager.filter.return_value.acount = AsyncMock(return_value=5)
    cfg = merge_logic.get_merge_level_config(6)
    instances = [
        _make_instance(
            pk=i, player_id=1, ball_id=1, special_id=42, attack_bonus=cfg.attack_bonus, health_bonus=cfg.health_bonus
        )
        for i in range(1, 3)
    ]

    quota_settings = AsyncMock(return_value=SimpleNamespace(weekly_cap=MERGE_WEEKLY_LIMIT, period_days=7))
    with (
        patch("fcdex_3_1.fcdex_ext.merge_quota.get_merge_quota_settings", quota_settings),
        pytest.raises(merge_logic.MergeValidationError) as exc,
    ):
        asyncio.run(merge_logic.validate_merge_batch(player, instances))

    assert str(MERGE_WEEKLY_LIMIT) in exc.value.message
    assert "merge quota" in exc.value.message


def test_validate_merge_batch_blocks_already_merged_instance():
    merge_logic, merge_log_manager = _load_merge_logic_for_validation_tests()
    player = SimpleNamespace(pk=1)
    merge_logic.get_merge_special = AsyncMock(return_value=SimpleNamespace(pk=42, name="FCDex Merge"))
    merge_log_manager.filter.return_value.acount = AsyncMock(return_value=0)
    merge_log_manager.filter.return_value.aexists = AsyncMock(return_value=True)
    instances = [_make_instance(pk=i, player_id=1, ball_id=1) for i in range(1, 11)]

    with pytest.raises(merge_logic.MergeValidationError) as exc:
        asyncio.run(merge_logic.validate_merge_batch(player, instances))

    assert "already used in a merge" in exc.value.message
