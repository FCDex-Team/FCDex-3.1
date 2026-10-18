from __future__ import annotations

import asyncio
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fcdex_3_1.fcdex_ext import compat, spawn_cog
from fcdex_3_1.fcdex_ext.spawn_cog import SpawnEventsCog, algo_of


class FixedRandom(random.Random):
    def __init__(self, value: float):
        super().__init__(0)
        self.value = value

    def random(self) -> float:
        return self.value


class FakeManager:
    """Shaped like BallsDex's SpawnManager: a plain object with an async handle_message."""

    def __init__(self, result=True):
        self.result = result
        self.calls = 0

    async def handle_message(self, message):
        self.calls += 1
        return self.result

    async def admin_explain(self, ctx, guild):
        return "explained"


class FakeBot:
    def __init__(self, spawner):
        self.spawner = spawner

    def get_cog(self, name):
        return self.spawner if name == "CountryBallsSpawner" else None


GUILD = SimpleNamespace(id=1, get_channel=lambda channel_id: SimpleNamespace(id=channel_id) if channel_id else None)
MESSAGE = SimpleNamespace(guild=GUILD)


def make(result=True, *, roll: float = 0.05, cache=None):
    manager = FakeManager(result)
    spawner = SimpleNamespace(spawn_manager=manager, cache={1: 55} if cache is None else cache)
    cog = SpawnEventsCog(FakeBot(spawner), rng=FixedRandom(roll))  # type: ignore[arg-type]
    return cog, manager, spawner


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    # twin 10% + match 2%: a roll of 0.05 is a twin, 0.01 a match, 0.5 a normal spawn
    config = SimpleNamespace(
        twin_enabled=True, twin_chance=10.0, match_enabled=True, match_chance=2.0, match_difficulty=110
    )
    monkeypatch.setattr(spawn_cog, "get_spawn_config", AsyncMock(return_value=config))
    monkeypatch.setattr(spawn_cog, "spawn_twin", AsyncMock(return_value=True))
    monkeypatch.setattr(spawn_cog, "spawn_match", AsyncMock(return_value=True))
    monkeypatch.setattr(compat, "spawn_cancelled_by_hooks", AsyncMock(return_value=False))


def test_algo_is_read_from_the_manager_result():
    assert algo_of((True, "ab_test_b")) == "ab_test_b"
    assert algo_of(True) == "fcdex"


def test_install_wraps_the_live_spawn_manager():
    cog, manager, _ = make()
    original = manager.handle_message
    assert cog.install() is True
    assert manager.handle_message is not original
    assert vars(manager)["handle_message"].__fcdex_special_spawns__ is True
    # everything else on the manager keeps working
    assert asyncio.run(manager.admin_explain(None, None)) == "explained"


def test_install_is_idempotent():
    cog, manager, _ = make()
    cog.install()
    wrapped = manager.handle_message
    assert cog.install() is True
    assert manager.handle_message is wrapped
    assert len(cog._wrapped) == 1


def test_install_reports_a_missing_spawner():
    cog = SpawnEventsCog(FakeBot(None))  # type: ignore[arg-type]
    assert cog.install() is False


def test_install_survives_a_manager_that_cannot_be_patched():
    class Slotted:
        __slots__ = ()

        async def handle_message(self, message):
            return True

    spawner = SimpleNamespace(spawn_manager=Slotted(), cache={})
    assert SpawnEventsCog(FakeBot(spawner)).install() is False  # type: ignore[arg-type]


def test_uninstall_restores_the_original_method():
    cog, manager, _ = make()
    cog.install()
    cog.uninstall()
    assert "handle_message" not in vars(manager)
    assert asyncio.run(manager.handle_message(MESSAGE)) is True
    assert manager.calls == 1


def test_uninstall_puts_back_a_method_that_was_already_patched():
    cog, manager, _ = make()

    async def earlier(message):
        return "earlier"

    manager.handle_message = earlier  # type: ignore[method-assign]
    cog.install()
    cog.uninstall()
    assert manager.handle_message is earlier


def test_no_spawn_is_passed_through_untouched():
    cog, manager, _ = make(result=False)
    cog.install()
    assert asyncio.run(manager.handle_message(MESSAGE)) is False
    spawn_cog.spawn_twin.assert_not_awaited()


def test_a_normal_roll_keeps_the_normal_spawn():
    cog, manager, _ = make(result=(True, "algo"), roll=0.5)
    cog.install()
    assert asyncio.run(manager.handle_message(MESSAGE)) == (True, "algo")
    spawn_cog.spawn_twin.assert_not_awaited()
    spawn_cog.spawn_match.assert_not_awaited()


def test_a_twin_roll_posts_a_twin_and_suppresses_the_normal_spawn():
    cog, manager, _ = make(result=(True, "algo"), roll=0.05)
    cog.install()
    assert asyncio.run(manager.handle_message(MESSAGE)) is False
    spawn_cog.spawn_twin.assert_awaited_once()
    args, kwargs = spawn_cog.spawn_twin.await_args
    assert args[1].id == 55  # the configured spawn channel
    assert kwargs["algo"] == "algo"
    spawn_cog.spawn_match.assert_not_awaited()


def test_a_match_roll_posts_a_match_spawn():
    cog, manager, _ = make(roll=0.01)
    cog.install()
    assert asyncio.run(manager.handle_message(MESSAGE)) is False
    spawn_cog.spawn_match.assert_awaited_once()
    spawn_cog.spawn_twin.assert_not_awaited()


def test_a_failed_post_falls_back_to_the_normal_spawn(monkeypatch):
    monkeypatch.setattr(spawn_cog, "spawn_twin", AsyncMock(return_value=False))
    cog, manager, _ = make(result=True, roll=0.05)
    cog.install()
    assert asyncio.run(manager.handle_message(MESSAGE)) is True


def test_a_crash_while_posting_falls_back_to_the_normal_spawn(monkeypatch):
    monkeypatch.setattr(spawn_cog, "spawn_twin", AsyncMock(side_effect=RuntimeError("boom")))
    cog, manager, _ = make(result=(True, "algo"), roll=0.05)
    cog.install()
    assert asyncio.run(manager.handle_message(MESSAGE)) == (True, "algo")


def test_a_config_read_failure_falls_back_to_the_normal_spawn(monkeypatch):
    monkeypatch.setattr(spawn_cog, "get_spawn_config", AsyncMock(side_effect=RuntimeError("db down")))
    cog, manager, _ = make(roll=0.05)
    cog.install()
    assert asyncio.run(manager.handle_message(MESSAGE)) is True


def test_a_missing_spawn_channel_is_left_to_the_host():
    cog, manager, _ = make(roll=0.05, cache={})
    cog.install()
    assert asyncio.run(manager.handle_message(MESSAGE)) is True
    spawn_cog.spawn_twin.assert_not_awaited()


def test_another_packages_spawn_veto_cancels_the_replacement_and_the_normal_spawn(monkeypatch):
    monkeypatch.setattr(compat, "spawn_cancelled_by_hooks", AsyncMock(return_value=True))
    cog, manager, _ = make(roll=0.05)
    cog.install()
    assert asyncio.run(manager.handle_message(MESSAGE)) is False
    spawn_cog.spawn_twin.assert_not_awaited()


def test_a_message_outside_a_guild_is_ignored():
    cog, manager, _ = make(roll=0.05)
    cog.install()
    assert asyncio.run(manager.handle_message(SimpleNamespace(guild=None))) is True
    spawn_cog.spawn_twin.assert_not_awaited()


def test_a_reloaded_spawner_gets_wrapped_again():
    cog, manager, spawner = make()
    cog.install()
    fresh = FakeManager()
    spawner.spawn_manager = fresh  # what the host does when its spawner cog is reloaded
    assert cog.install() is True
    assert getattr(fresh.handle_message, "__fcdex_special_spawns__", False) is True


def test_load_and_unload_start_and_stop_the_rewrap_loop():
    async def run():
        cog, manager, _ = make()
        await cog.cog_load()
        assert cog.rewrap.is_running()
        assert getattr(manager.handle_message, "__fcdex_special_spawns__", False) is True
        await cog.cog_unload()
        await asyncio.sleep(0)
        assert "handle_message" not in vars(manager)
        assert not cog.rewrap.is_running()

    asyncio.run(run())
