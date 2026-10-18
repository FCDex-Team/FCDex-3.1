"""Feature detection so FCDex runs on BallsDex 3.0.x-3.2.x and on the v3 branch (events and hooks)."""

from __future__ import annotations

import importlib
import logging
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import discord

log = logging.getLogger("fcdex_3_1.compat")


def _import(name: str) -> ModuleType | None:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


# `ballsdex.core.hooks` and `ballsdex.core.events` only exist on BallsDex builds newer than 3.2.0.
HOOKS: ModuleType | None = _import("ballsdex.core.hooks")
EVENTS: ModuleType | None = _import("ballsdex.core.events")


def has_hooks(bot: Any) -> bool:
    return HOOKS is not None and getattr(bot, "hooks", None) is not None


async def run_hook(bot: Any, context_name: str, **fields: Any) -> Any | None:
    """Run the hooks registered for `context_name` (e.g. "PreCatchContext") and return the context.

    Returns `None` when this BallsDex has no hooks, so callers can simply skip the step.
    """
    if not has_hooks(bot):
        return None
    context_cls = getattr(HOOKS, context_name, None)
    if context_cls is None:
        return None
    try:
        return await bot.hooks.run(context_cls(**fields))
    except Exception:
        log.warning("Could not run the %s hooks, continuing without them.", context_name, exc_info=True)
        return None


async def spawn_cancelled_by_hooks(
    bot: Any, *, guild: discord.Guild, channel: discord.abc.GuildChannel, message: discord.Message, algo: str
) -> bool:
    """Whether another package's `spawn_check` hook cancelled this spawn (always False without hooks)."""
    context = await run_hook(bot, "SpawnCheckContext", guild=guild, channel=channel, message=message, algo=algo)
    return bool(context is not None and context.cancelled)


def dispatch_ball_spawned(bot: Any, view: Any, channel: Any) -> None:
    """Tell other packages a countryball spawned (only on BallsDex builds that have the events API)."""
    if EVENTS is None:
        return
    try:
        EVENTS.dispatch(bot, EVENTS.BallSpawnedEvent(view=view, channel=channel))
    except Exception:
        log.warning("Could not dispatch the ball spawned event.", exc_info=True)
