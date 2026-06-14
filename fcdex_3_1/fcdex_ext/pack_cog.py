from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bd_models.models import Player
from fcdex_3_1.fcdex_ext.pack_logic import PACK_TYPE_LABELS, PackOpenSuccess, grant_player_pack, pack_status_entries
from fcdex_3_1.fcdex_ext.pack_views import build_pack_menu_layout, build_pack_open_layout
from fcdex_3_1.models import PackType

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.pack.cog")


class PackCog(commands.GroupCog, group_name="pack"):
    """Daily and weekly reward packs (exclusive is admin-only)."""

    def __init__(self, bot: BallsDexBot):
        self.bot = bot

    async def _open(self, interaction: discord.Interaction, pack_type: str) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException as exc:
            log.warning("Pack defer failed for user %s: %s", interaction.user.id, exc)
            try:
                await interaction.response.send_message(
                    "❌ Could not open the pack. Try again in a moment.", ephemeral=True
                )
            except discord.HTTPException:
                pass
            return

        try:
            player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
            guild_id = interaction.guild_id if interaction.guild else None
            ok, result = await grant_player_pack(player, pack_type, guild_id=guild_id)
            if not ok:
                await interaction.followup.send(str(result), ephemeral=True)
                return

            success: PackOpenSuccess = result  # type: ignore[assignment]
            layout, pack_files = build_pack_open_layout(pack_type=pack_type, body=success.message)
            kwargs: dict = {"view": layout, "ephemeral": True}
            if pack_files:
                kwargs["files"] = pack_files
            await interaction.followup.send(**kwargs)  # pyright: ignore[reportArgumentType]
        except Exception as exc:
            log.exception("Pack open failed for user %s type %s", interaction.user.id, pack_type)
            label = PACK_TYPE_LABELS[pack_type]
            await interaction.followup.send(
                f"❌ Could not open **{label}**: **{type(exc).__name__}** — {str(exc)[:200]}", ephemeral=True
            )

    @app_commands.command(name="menu", description="View all packs — rewards, cooldowns, and claim status")
    async def menu(self, interaction: discord.Interaction):
        try:
            player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
            entries = await pack_status_entries(player)
            layout = build_pack_menu_layout(entries)
            await interaction.response.send_message(view=layout, ephemeral=True)  # pyright: ignore[reportArgumentType]
        except Exception as exc:
            log.exception("Pack menu failed for user %s", interaction.user.id)
            await interaction.response.send_message(
                f"❌ Could not load pack status: **{type(exc).__name__}** — {str(exc)[:200]}", ephemeral=True
            )

    @app_commands.command(name="daily", description="Open Daily Pack — 3 clubballs with stat rolls (24h cooldown)")
    async def daily(self, interaction: discord.Interaction):
        await self._open(interaction, PackType.DAILY)

    @app_commands.command(name="weekly", description="Open Weekly Pack — 5 clubballs with stat rolls (7d cooldown)")
    async def weekly(self, interaction: discord.Interaction):
        await self._open(interaction, PackType.WEEKLY)
