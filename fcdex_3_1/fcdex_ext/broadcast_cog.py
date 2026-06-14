from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View, button

from fcdex_3_1.fcdex_ext.broadcast_logic import (
    DISCORD_MESSAGE_MAX,
    count_dm_recipients,
    count_server_broadcast_targets,
    preview_broadcast_message,
    run_dm_broadcast,
    run_server_broadcast,
    validate_broadcast_message,
)

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.broadcast.cog")

BroadcastKind = Literal["dm", "server"]


def broadcast_admin_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is not None:
            return bool(interaction.user.guild_permissions.manage_guild)
        return await interaction.client.is_owner(interaction.user)

    return app_commands.check(predicate)


class BroadcastConfirmView(View):
    def __init__(self, *, owner_id: int, kind: BroadcastKind, message: str, recipient_label: str):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.kind = kind
        self.message = message
        self.recipient_label = recipient_label
        self._started = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This confirmation is not yours.", ephemeral=True)
            return False
        return True

    @button(label="Confirm broadcast", style=discord.ButtonStyle.danger, emoji="📣")
    async def confirm(self, interaction: discord.Interaction, button: Button) -> None:
        if self._started:
            await interaction.response.send_message("Broadcast already started.", ephemeral=True)
            return
        self._started = True
        for child in self.children:
            child.disabled = True  # type: ignore[union-attr]
        await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(content="Broadcast started…", embed=None, view=self)
        bot: BallsDexBot = interaction.client  # type: ignore[assignment]
        if self.kind == "dm":
            await _run_dm_broadcast(interaction, bot, self.message)
        else:
            await _run_server_broadcast(interaction, bot, self.message)

    @button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[union-attr]
        await interaction.response.edit_message(content="Broadcast cancelled.", embed=None, view=self)


async def _edit_status(interaction: discord.Interaction, text: str) -> None:
    try:
        await interaction.edit_original_response(content=text)
    except discord.HTTPException:
        log.debug("Could not edit broadcast status message", exc_info=True)


async def _run_dm_broadcast(interaction: discord.Interaction, bot: BallsDexBot, message: str) -> None:
    total = await count_dm_recipients()
    await _edit_status(interaction, f"Starting DM broadcast to **{total:,}** players…")
    tally, _ = await run_dm_broadcast(bot, message)
    await _edit_status(interaction, tally.format_dm_summary(total=total))


async def _run_server_broadcast(interaction: discord.Interaction, bot: BallsDexBot, message: str) -> None:
    total = await count_server_broadcast_targets(bot)
    await _edit_status(interaction, f"Starting server broadcast across **{total:,}** postable servers…")
    tally, guilds, skipped = await run_server_broadcast(bot, message)
    await _edit_status(interaction, tally.format_server_summary(guilds=guilds, skipped=skipped))


async def _prompt_broadcast(interaction: discord.Interaction, *, kind: BroadcastKind, message: str) -> None:
    ok, result = validate_broadcast_message(message)
    if not ok:
        await interaction.response.send_message(result, ephemeral=True)
        return

    cleaned = result
    if kind == "dm":
        count = await count_dm_recipients()
        recipient_label = f"**{count:,}** players with at least one clubball (non-deleted)"
        title = "DM broadcast"
        warning = (
            "This will DM every eligible player. Rate-limited batches reduce 429 risk; "
            "large sends may take several minutes."
        )
    else:
        count = await count_server_broadcast_targets(interaction.client)
        recipient_label = f"**{count:,}** servers with a writable channel (one message each)"
        title = "Server broadcast"
        warning = "This posts your message publicly in each target server channel."

    embed = discord.Embed(
        title=f"Confirm · {title}",
        description=(f"{recipient_label}\n\n**Preview**\n{preview_broadcast_message(cleaned)}\n\n-# {warning}"),
        color=discord.Color.orange(),
    )
    view = BroadcastConfirmView(
        owner_id=interaction.user.id, kind=kind, message=cleaned, recipient_label=recipient_label
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class BroadcastCog(commands.GroupCog, group_name="broadcast"):
    """Mass announcements — admin-only with confirmation."""

    def __init__(self, bot: BallsDexBot):
        self.bot = bot

    @app_commands.command(
        name="dm", description="DM every player who has caught at least one clubball (admin · confirmation required)"
    )
    @app_commands.describe(message=f"Announcement text (max {DISCORD_MESSAGE_MAX} characters)")
    @broadcast_admin_check()
    async def dm(self, interaction: discord.Interaction, message: str):
        await _prompt_broadcast(interaction, kind="dm", message=message)

    @app_commands.command(
        name="dm_announcement", description="Alias for /broadcast dm — DM players with at least one clubball"
    )
    @app_commands.describe(message=f"Announcement text (max {DISCORD_MESSAGE_MAX} characters)")
    @broadcast_admin_check()
    async def dm_announcement(self, interaction: discord.Interaction, message: str):
        await _prompt_broadcast(interaction, kind="dm", message=message)

    @app_commands.command(
        name="server", description="Post an announcement in every server the bot is in (admin · confirmation required)"
    )
    @app_commands.describe(message=f"Announcement text (max {DISCORD_MESSAGE_MAX} characters)")
    @broadcast_admin_check()
    async def server(self, interaction: discord.Interaction, message: str):
        await _prompt_broadcast(interaction, kind="server", message=message)

    @app_commands.command(
        name="server_announcement", description="Alias for /broadcast server — announce in all guilds"
    )
    @app_commands.describe(message=f"Announcement text (max {DISCORD_MESSAGE_MAX} characters)")
    @broadcast_admin_check()
    async def server_announcement(self, interaction: discord.Interaction, message: str):
        await _prompt_broadcast(interaction, kind="server", message=message)
