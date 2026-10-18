from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fcdex_3_1.fcdex_ext import compat


class FakeContext:
    def __init__(self, **fields):
        self.__dict__.update(fields)
        self.cancelled = False
        self.reason = None


def bot_with_hooks(run) -> SimpleNamespace:
    return SimpleNamespace(hooks=SimpleNamespace(run=run))


def test_without_hooks_nothing_is_run(monkeypatch):
    monkeypatch.setattr(compat, "HOOKS", None)
    bot = bot_with_hooks(AsyncMock())
    assert compat.has_hooks(bot) is False
    assert asyncio.run(compat.run_hook(bot, "PreCatchContext", view=1)) is None
    assert asyncio.run(compat.spawn_cancelled_by_hooks(bot, guild=1, channel=2, message=3, algo="x")) is False


def test_a_bot_without_a_registry_is_treated_as_hookless(monkeypatch):
    monkeypatch.setattr(compat, "HOOKS", SimpleNamespace(PreCatchContext=FakeContext))
    assert compat.has_hooks(SimpleNamespace()) is False


def test_run_hook_builds_the_named_context_and_returns_it(monkeypatch):
    monkeypatch.setattr(compat, "HOOKS", SimpleNamespace(PreCatchContext=FakeContext))
    run = AsyncMock(side_effect=lambda ctx: ctx)
    context = asyncio.run(compat.run_hook(bot_with_hooks(run), "PreCatchContext", view="v", guess="g"))
    assert isinstance(context, FakeContext)
    assert (context.view, context.guess) == ("v", "g")
    run.assert_awaited_once_with(context)


def test_unknown_context_names_are_skipped(monkeypatch):
    monkeypatch.setattr(compat, "HOOKS", SimpleNamespace())
    assert asyncio.run(compat.run_hook(bot_with_hooks(AsyncMock()), "FutureContext")) is None


def test_a_context_signature_change_does_not_break_the_caller(monkeypatch):
    class Strict:
        def __init__(self, *, only: int):
            self.only = only

    monkeypatch.setattr(compat, "HOOKS", SimpleNamespace(PreCatchContext=Strict))
    assert asyncio.run(compat.run_hook(bot_with_hooks(AsyncMock()), "PreCatchContext", view=1)) is None


def test_spawn_check_cancellation_is_reported(monkeypatch):
    monkeypatch.setattr(compat, "HOOKS", SimpleNamespace(SpawnCheckContext=FakeContext))

    async def cancel(ctx):
        ctx.cancelled = True
        return ctx

    bot = bot_with_hooks(cancel)
    assert asyncio.run(compat.spawn_cancelled_by_hooks(bot, guild=1, channel=2, message=3, algo="x")) is True
    allow = bot_with_hooks(AsyncMock(side_effect=lambda ctx: ctx))
    assert asyncio.run(compat.spawn_cancelled_by_hooks(allow, guild=1, channel=2, message=3, algo="x")) is False


def test_spawn_event_is_dispatched_only_when_the_events_api_exists(monkeypatch):
    event_cls = MagicMock(side_effect=lambda **kw: SimpleNamespace(**kw))
    dispatch = MagicMock()
    monkeypatch.setattr(compat, "EVENTS", SimpleNamespace(BallSpawnedEvent=event_cls, dispatch=dispatch))
    compat.dispatch_ball_spawned("bot", "view", "channel")
    dispatch.assert_called_once()
    assert dispatch.call_args.args[0] == "bot"
    assert dispatch.call_args.args[1].view == "view"

    monkeypatch.setattr(compat, "EVENTS", None)
    compat.dispatch_ball_spawned("bot", "view", "channel")  # must not raise


def test_a_failing_event_listener_setup_is_swallowed(monkeypatch):
    def explode(*args, **kwargs):
        raise TypeError("signature changed")

    monkeypatch.setattr(compat, "EVENTS", SimpleNamespace(BallSpawnedEvent=explode, dispatch=explode))
    compat.dispatch_ball_spawned("bot", "view", "channel")
