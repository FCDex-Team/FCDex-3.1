from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Modal, TextInput, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.pack_logic import grant_exclusive_pack
from fcdex_3_1.fcdex_ext.pack_views import build_pack_open_layout
from fcdex_3_1.models import PackType

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.pack.admin")


class GrantExclusivePackModal(Modal, title="Grant Exclusive Pack"):
    player_id = TextInput(label="Discord user ID", placeholder="123456789012345678", max_length=24)

    def __init__(self, owner_id: int, guild_id: int | None):
        super().__init__()
        self.owner_id = owner_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: Interaction) -> None:
        raw = self.player_id.value.strip()
        if not raw.isdigit():
            await interaction.response.send_message("Enter a numeric Discord user ID.", ephemeral=True)
            return
        target_id = int(raw)
        await interaction.response.defer(ephemeral=True)
        try:
            player, _ = await Player.objects.aget_or_create(discord_id=target_id)
            success = await grant_exclusive_pack(player, guild_id=self.guild_id)
            notice = f"✅ Granted **Exclusive Pack** to <@{target_id}>.\n\n{success.message}"
            layout, pack_files = build_pack_open_layout(pack_type=PackType.EXCLUSIVE, body=notice)
            kwargs: dict = {"view": layout, "ephemeral": True}
            if pack_files:
                kwargs["files"] = pack_files
            await interaction.followup.send(**kwargs)  # pyright: ignore[reportArgumentType]
        except Exception as exc:
            log.exception("Admin exclusive pack grant failed for target %s", raw)
            await interaction.followup.send(
                f"❌ Grant failed: **{type(exc).__name__}** — {str(exc)[:200]}", ephemeral=True
            )


class PackAdminControls(ActionRow):
    def __init__(self, owner_id: int, guild_id: int | None):
        super().__init__()
        self.owner_id = owner_id
        self.guild_id = guild_id

    @button(label="Grant Exclusive", style=discord.ButtonStyle.success, emoji="📦")
    async def grant_exclusive(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(GrantExclusivePackModal(self.owner_id, self.guild_id))

    @button(label="Back", style=discord.ButtonStyle.secondary, emoji="◀️")
    async def back(self, interaction: Interaction, button: Button):
        if interaction.channel_id is None:
            await interaction.response.send_message("Missing channel context.", ephemeral=True)
            return
        from fcdex_3_1.fcdex_ext.admin_hub_views import build_admin_hub_layout

        layout = build_admin_hub_layout(self.owner_id, self.guild_id, interaction.channel_id)
        await interaction.response.edit_message(view=layout)


def build_pack_admin_layout(owner_id: int, guild_id: int | None, *, notice: str = "") -> LayoutView:
    layout = LayoutView(timeout=600)
    container = discord.ui.Container()
    header = "# 📦 Pack admin"
    if notice:
        header = f"{notice}\n\n{header}"
    container.add_item(
        discord.ui.TextDisplay(
            f"{header}\n"
            "-# **Daily Pack** — `/pack daily` · once per calendar day · 3 clubballs + coins + stat rolls.\n"
            "-# **Weekly Pack** — `/pack weekly` · 7d cooldown · 5 clubballs + coins + stat rolls.\n"
            "-# **Exclusive Pack** — admin-only · rare clubballs, high stat boosts, specials, big coins."
        )
    )
    container.add_item(discord.ui.Separator())
    container.add_item(PackAdminControls(owner_id, guild_id))
    layout.add_item(container)
    return layout
