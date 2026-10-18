"""Turns some natural spawns into twin or match spawns.

BallsDex 3.2 and older have no spawn hook, so this wraps the `handle_message` of the live spawn manager. When the
manager decides a countryball should spawn, one roll can swap it for a twin or match spawn, in which case
`handle_message` returns `False` and the normal spawn is skipped. On BallsDex builds that have hooks, other
packages' `spawn_check` hooks still run (and can cancel) before the replacement is posted. If anything goes
wrong the original result is returned, so a normal spawn still happens.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands, tasks

from fcdex_3_1.fcdex_ext import compat
from fcdex_3_1.fcdex_ext.match_spawn import spawn_match
from fcdex_3_1.fcdex_ext.spawn_events import SpawnKind, get_spawn_config, roll_spawn_kind, spawn_rates
from fcdex_3_1.fcdex_ext.twin_spawn import spawn_twin

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.spawn")

SPAWNER_COG_NAME = "CountryBallsSpawner"
WRAPPED_MARKER = "__fcdex_special_spawns__"
# The spawner cog builds a fresh spawn manager whenever it is reloaded, so the wrapper is re-applied regularly.
REWRAP_INTERVAL_SECONDS = 60

HandleMessage = Callable[[discord.Message], Awaitable[Any]]


def algo_of(result: Any) -> str:
    """The spawn algorithm named by a `handle_message` result, `(True, "algo")` or plain `True`."""
    if isinstance(result, tuple) and len(result) > 1:
        return str(result[1])
    return "fcdex"


class SpawnEventsCog(commands.Cog):
    """Owns the wrapper around the spawn manager and removes it again when unloaded."""

    def __init__(self, bot: BallsDexBot, rng: random.Random | None = None):
        self.bot = bot
        self.rng = rng
        self._wrapped: list[tuple[Any, HandleMessage | None, HandleMessage]] = []

    async def cog_load(self) -> None:
        if not self.install():
            log.warning("Spawn manager not found yet, twin and match spawns will start once it is available.")
        self.rewrap.start()

    async def cog_unload(self) -> None:
        self.rewrap.cancel()
        self.uninstall()

    @tasks.loop(seconds=REWRAP_INTERVAL_SECONDS)
    async def rewrap(self) -> None:
        self.install()

    # wrapping -----------------------------------------------------------------------------------------------

    def install(self) -> bool:
        spawner = self.bot.get_cog(SPAWNER_COG_NAME)
        manager = getattr(spawner, "spawn_manager", None)
        if spawner is None or manager is None:
            return False
        current: HandleMessage = manager.handle_message
        if getattr(current, WRAPPED_MARKER, False):
            return True  # an earlier copy of this cog is still wrapping it

        async def handle_message(message: discord.Message) -> Any:
            result = await current(message)
            if result is False:
                return result
            try:
                if await self.replace_spawn(spawner, message, result):
                    return False
            except Exception:
                log.exception("Special spawn failed, falling back to the normal spawn.")
            return result

        setattr(handle_message, WRAPPED_MARKER, True)
        try:
            previous = vars(manager).get("handle_message")
            manager.handle_message = handle_message
        except (AttributeError, TypeError):
            log.warning("The spawn manager %r cannot be wrapped, twin and match spawns are disabled.", manager)
            return False
        self._wrapped.append((manager, previous, handle_message))
        log.info("Twin and match spawns are active.")
        return True

    def uninstall(self) -> None:
        for manager, previous, wrapper in self._wrapped:
            if vars(manager).get("handle_message") is not wrapper:
                continue
            if previous is None:
                del vars(manager)["handle_message"]
            else:
                manager.handle_message = previous
        self._wrapped.clear()

    # deciding -----------------------------------------------------------------------------------------------

    def spawn_channel(self, spawner: Any, guild: discord.Guild) -> discord.abc.GuildChannel | None:
        channel_id = getattr(spawner, "cache", {}).get(guild.id)
        return guild.get_channel(channel_id) if channel_id else None

    async def replace_spawn(self, spawner: Any, message: discord.Message, result: Any) -> bool:
        """Possibly post a twin or match spawn instead of the normal one. True means the normal spawn is skipped."""
        guild = message.guild
        if guild is None:
            return False
        kind = roll_spawn_kind(spawn_rates(await get_spawn_config()), self.rng)
        if kind is SpawnKind.NORMAL:
            return False
        channel = self.spawn_channel(spawner, guild)
        if channel is None:
            return False  # let the host report the missing channel

        algo = algo_of(result)
        if await compat.spawn_cancelled_by_hooks(self.bot, guild=guild, channel=channel, message=message, algo=algo):
            return True  # another package vetoed this spawn, same as it would for a normal one
        if kind is SpawnKind.TWIN:
            return await spawn_twin(self.bot, channel, algo=algo, rng=self.rng)
        return await spawn_match(self.bot, channel, algo=algo, rng=self.rng)
