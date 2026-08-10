from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Ball
from fcdex_3_1.fcdex_ext.achievement_admin_views import build_achievement_admin_layout
from fcdex_3_1.fcdex_ext.bd_resolve import resolve_ball_for_lookup
from fcdex_3_1.fcdex_ext.boss_views import build_boss_admin_layout
from fcdex_3_1.fcdex_ext.craft_admin_views import build_craft_admin_layout
from fcdex_3_1.fcdex_ext.interaction_context import admin_context
from fcdex_3_1.fcdex_ext.merge_admin_views import build_merge_admin_layout
from fcdex_3_1.fcdex_ext.pack_admin_views import build_pack_admin_layout
from fcdex_3_1.fcdex_ext.quest_admin_views import build_quest_admin_layout
from fcdex_3_1.fcdex_ext.shop_admin_views import build_shop_admin_layout
from fcdex_3_1.fcdex_ext.tournament_admin_views import build_tournament_admin_layout
from fcdex_3_1.fcdex_ext.views import build_panel_layout, truncate_text

if TYPE_CHECKING:
    from discord import Interaction


class AdminHubControls(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="Shop", style=discord.ButtonStyle.primary, emoji="🛒")
    async def shop(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_shop_admin_layout(self.owner_id, ctx, notice="")
        await interaction.response.edit_message(view=layout)

    @button(label="Craft", style=discord.ButtonStyle.primary, emoji="🧪")
    async def craft(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_craft_admin_layout(self.owner_id, ctx, notice="")
        await interaction.response.edit_message(view=layout)

    @button(label="Boss", style=discord.ButtonStyle.danger, emoji="👑")
    async def boss(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_boss_admin_layout(ctx, self.owner_id)
        await interaction.response.edit_message(view=layout)

    @button(label="Quests", style=discord.ButtonStyle.primary, emoji="📜")
    async def quests(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_quest_admin_layout(self.owner_id, ctx, notice="")
        await interaction.response.edit_message(view=layout)

    @button(label="Achievements", style=discord.ButtonStyle.primary, emoji="🏅")
    async def achievements(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_achievement_admin_layout(self.owner_id, ctx, notice="")
        await interaction.response.edit_message(view=layout)


class AdminHubControlsRow2(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="Merge", style=discord.ButtonStyle.primary, emoji="✨")
    async def merge(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_merge_admin_layout(self.owner_id, ctx, notice="")
        await interaction.response.edit_message(view=layout)

    @button(label="Packs", style=discord.ButtonStyle.primary, emoji="📦")
    async def packs(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = build_pack_admin_layout(self.owner_id, ctx.guild_id)
        await interaction.response.edit_message(view=layout)

    @button(label="Tournament", style=discord.ButtonStyle.primary, emoji="🏟️")
    async def tournament(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_tournament_admin_layout(self.owner_id, ctx)
        await interaction.response.edit_message(view=layout)

    @button(label="Owners", style=discord.ButtonStyle.secondary, emoji="🔍")
    async def owners(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(OwnersLookupModal(self.owner_id))


class OwnersLookupModal(Modal, title="Clubball owners"):
    clubball = TextInput(label="Clubball", placeholder="Country name or PK (e.g. 42)", max_length=128)

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        ball = await resolve_ball_for_lookup(self.clubball.value)
        if ball is None:
            await interaction.response.send_message("Clubball not found.", ephemeral=True)
            return
        await open_owners_panel(interaction, ball)


def build_admin_hub_layout(owner_id: int, guild_id: int | None, channel_id: int) -> LayoutView:
    layout = LayoutView(timeout=600)
    container = Container()
    container.add_item(
        TextDisplay(
            truncate_text(
                "# 🛡️ FCDex admin\n"
                "-# Manage Server · all panels are ephemeral.\n"
                "-# **Shop** — bundles & optional specials per item.\n"
                "-# **Craft** — SBC recipes without the web panel.\n"
                "-# **Quests** — daily quest targets, rewards & hooks.\n"
                "-# **Achievements** — goals, rewards & visibility for `/achievement menu`.\n"
                "-# **Merge** — global quota, premium bonus & per-player overrides.\n"
                "-# **Packs** — grant **Exclusive Pack** (admin-only; daily/weekly are `/pack`).\n"
                "-# **Boss** — start raids here or in any channel/DM.\n"
                "-# **Tournament** — set global caps for `/tournament manage`."
            )
        )
    )
    container.add_item(Separator())
    container.add_item(AdminHubControls(owner_id))
    container.add_item(AdminHubControlsRow2(owner_id))
    layout.add_item(container)
    return layout


async def open_owners_panel(interaction: Interaction, clubball: Ball) -> None:
    from bd_models.models import BallInstance, Player

    count = await BallInstance.objects.filter(ball_id=clubball.pk, deleted=False).acount()
    if count == 0:
        await interaction.response.send_message(f"Nobody owns **{clubball.country}** right now.", ephemeral=True)
        return
    lines: list[str] = []
    async for inst in BallInstance.objects.filter(ball_id=clubball.pk, deleted=False).order_by("-pk")[:25]:
        player = await Player.objects.aget(pk=inst.player_id)
        lines.append(f"• <@{player.discord_id}> · card `#{inst.pk}`")
    extra = f"-# Showing 25/{count} owners." if count > 25 else ""
    layout = build_panel_layout(
        title=f"Owners of {clubball.country}",
        subtitle=f"{count} owner{'s' if count != 1 else ''}",
        sections=["\n".join(lines)],
        footer=extra,
    )
    await interaction.response.send_message(view=layout, ephemeral=True)  # pyright: ignore[reportArgumentType]
