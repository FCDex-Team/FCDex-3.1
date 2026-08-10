from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from fcdex_3_1.fcdex_ext.merge_views import build_merge_picker_view

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.merge")


class MergeCog(commands.Cog):
    """Forge matching clubballs through seven merge tiers."""

    def __init__(self, bot: BallsDexBot):
        self.bot = bot

    @app_commands.command(name="merge", description="Pick one clubball and forge it through the FCDex merge ladder")
    async def merge(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.HTTPException as exc:
            log.warning("Merge slash defer failed for user %s: %s", interaction.user.id, exc)
            try:
                await interaction.response.send_message(
                    "❌ Could not open the forge panel. Try again in a moment.", ephemeral=True
                )
            except discord.HTTPException:
                pass
            return
        try:
            layout = await build_merge_picker_view(self.bot, interaction.user.id)
            await interaction.edit_original_response(view=layout)  # pyright: ignore[reportArgumentType]
        except Exception as exc:
            log.exception("Failed to open merge panel for user %s", interaction.user.id)
            error_text = f"❌ Could not open merge forge: **{type(exc).__name__}** — {str(exc)[:200]}"
            try:
                await interaction.edit_original_response(content=error_text)
            except discord.HTTPException:
                try:
                    await interaction.followup.send(error_text, ephemeral=True)
                except discord.HTTPException:
                    pass
