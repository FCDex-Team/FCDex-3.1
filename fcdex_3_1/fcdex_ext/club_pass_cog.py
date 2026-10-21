"""`/club pass` and the catch hooks that pay club pass xp.

Normal catches are paid in two ways, whichever fires first wins (one payment per clubball instance):

- the `on_ballsdex_ball_caught` event, on BallsDex builds that have the events API;
- a wrapper around `BallSpawnView.catch_ball`, installed once on the countryball class and removed when this cog
  unloads. It only reads the result, and any error inside it is swallowed so a catch is never affected.

Twin spawns and match spawns also call `award_catch_xp` themselves. Limits: a host that renames the countryball
view or its `catch_ball` method and has no events API simply pays no catch xp (everything else keeps working).
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from fcdex_3_1.fcdex_ext.club_pass_logic import schedule_catch_xp
from fcdex_3_1.fcdex_ext.club_pass_views import build_pass_layout

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.club_pass")

WRAPPED_MARKER = "__fcdex_club_pass__"
SPAWN_VIEW_MODULE = "ballsdex.packages.countryballs.countryball"
SPAWN_VIEW_CLASS = "BallSpawnView"


class ClubPassCog(commands.GroupCog, group_name="club"):
    """Level up the club pass to earn coins and clubballs."""

    def __init__(self, bot: BallsDexBot):
        self.bot = bot
        self._patched: tuple[type, Any, Any] | None = None

    async def cog_load(self) -> None:
        self.install_catch_wrapper()

    async def cog_unload(self) -> None:
        self.uninstall_catch_wrapper()

    @app_commands.command(name="pass", description="Your club pass: level, xp and rewards")
    async def club_pass(self, interaction: discord.Interaction):
        layout = await build_pass_layout(interaction.user.id)
        await interaction.response.send_message(view=layout, ephemeral=True)  # pyright: ignore[reportArgumentType]

    # events -------------------------------------------------------------------------------------------------

    @commands.Cog.listener("on_ballsdex_ball_caught")
    async def on_ball_caught(self, event: Any) -> None:
        instance = None
        for attr in ("ball_instance", "instance", "ball"):
            instance = getattr(event, attr, None)
            if instance is not None and hasattr(instance, "ball_id"):
                break
            instance = None
        if instance is not None:
            schedule_catch_xp(instance, getattr(event, "player", None))

    # catch wrapper ------------------------------------------------------------------------------------------

    def install_catch_wrapper(self) -> bool:
        try:
            view_cls = getattr(importlib.import_module(SPAWN_VIEW_MODULE), SPAWN_VIEW_CLASS)
            current = view_cls.catch_ball
        except Exception:
            log.info("Countryball view not found, club pass catch xp relies on the events API.")
            return False
        if getattr(current, WRAPPED_MARKER, False):
            return True

        async def catch_ball(view: Any, *args: Any, **kwargs: Any) -> Any:
            result = await current(view, *args, **kwargs)
            try:
                instance = result[0]
                if hasattr(instance, "ball_id"):
                    schedule_catch_xp(instance, kwargs.get("player"))
            except Exception:
                log.debug("Could not read the catch result for club pass xp.", exc_info=True)
            return result

        setattr(catch_ball, WRAPPED_MARKER, True)
        try:
            view_cls.catch_ball = catch_ball
        except (AttributeError, TypeError):
            log.warning("The countryball view cannot be wrapped, club pass catch xp relies on events.")
            return False
        self._patched = (view_cls, current, catch_ball)
        return True

    def uninstall_catch_wrapper(self) -> None:
        if self._patched is None:
            return
        view_cls, original, wrapper = self._patched
        if view_cls.__dict__.get("catch_ball") is wrapper:
            view_cls.catch_ball = original
        self._patched = None
