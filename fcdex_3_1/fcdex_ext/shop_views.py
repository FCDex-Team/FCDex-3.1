from __future__ import annotations

import logging
from math import ceil
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Select, Separator, TextDisplay, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.discord_emoji import option_label_with_emoji
from fcdex_3_1.fcdex_ext.shop_logic import format_bundle_line_async, list_shop_bundles, purchase_bundle
from fcdex_3_1.fcdex_ext.views import truncate_text
from fcdex_3_1.models import ShopBundle

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.shop.views")

BUNDLES_PER_PAGE = 8


def _clamp_page(page: int, total_pages: int) -> int:
    return max(0, min(page, total_pages - 1))


def _page_slice(page: int, page_size: int) -> tuple[int, int]:
    start = page * page_size
    end = start + page_size
    return start, end


class ShopBundleSelect(Select):
    def __init__(self, owner_id: int, bundles: list[ShopBundle], *, page: int):
        self.owner_id = owner_id
        self.page = page
        options: list[discord.SelectOption] = []
        for bundle in bundles[:25]:
            desc = f"{bundle.price:,} coins"[:100]
            options.append(
                discord.SelectOption(
                    label=option_label_with_emoji(bundle.name, bundle.emoji, default="🛒"),
                    value=str(bundle.pk),
                    description=desc,
                )
            )
        super().__init__(placeholder="Choose a bundle to buy…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This shop panel is private to you.", ephemeral=True)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        guild_id = interaction.guild_id if interaction.guild else None
        _ok, message = await purchase_bundle(player, int(self.values[0]), guild_id=guild_id)
        layout = await build_shop_layout(interaction.user.id, notice=message, page=self.page)
        await interaction.response.edit_message(view=layout)


class ShopPageControls(ActionRow):
    def __init__(self, owner_id: int, *, page: int, total_pages: int):
        super().__init__()
        self.owner_id = owner_id
        self.page = page
        self.total_pages = total_pages
        self.previous_button.disabled = page <= 0
        self.next_button.disabled = page >= total_pages - 1

    async def _go(self, interaction: Interaction, target_page: int) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This shop panel is private to you.", ephemeral=True)
            return
        layout = await build_shop_layout(self.owner_id, page=target_page)
        await interaction.response.edit_message(view=layout)

    @button(label="Previous", style=discord.ButtonStyle.secondary, emoji="◀️")
    async def previous_button(self, interaction: Interaction, button: Button):
        await self._go(interaction, self.page - 1)

    @button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶️")
    async def next_button(self, interaction: Interaction, button: Button):
        await self._go(interaction, self.page + 1)


async def build_shop_layout(owner_id: int, *, notice: str = "", page: int = 0) -> LayoutView:
    player, _ = await Player.objects.aget_or_create(discord_id=owner_id)
    player = await Player.objects.aget(pk=player.pk)
    bundles = await list_shop_bundles(enabled_only=True)
    total_pages = max(1, ceil(len(bundles) / BUNDLES_PER_PAGE))
    page = _clamp_page(page, total_pages)
    start, end = _page_slice(page, BUNDLES_PER_PAGE)
    page_bundles = bundles[start:end]

    layout = LayoutView(timeout=300)
    container = Container()
    header = f"# 🛒 FCDex shop\n-# Your balance: **{player.money:,}** coins"
    if bundles:
        page_range = f"{start + 1}-{min(end, len(bundles))}"
        header += f"\n-# Page **{page + 1}/{total_pages}** · Bundles **{page_range}** of **{len(bundles)}**"
    if notice:
        header += f"\n\n{notice}"
    container.add_item(TextDisplay(truncate_text(header)))

    if bundles:
        lines: list[str] = []
        for bundle in page_bundles:
            lines.append(await format_bundle_line_async(bundle))
        container.add_item(Separator())
        container.add_item(TextDisplay(truncate_text("\n\n".join(lines))))
        container.add_item(Separator())
        row = ActionRow()
        row.add_item(ShopBundleSelect(owner_id, page_bundles, page=page))
        container.add_item(row)
        if total_pages > 1:
            container.add_item(ShopPageControls(owner_id, page=page, total_pages=total_pages))
    else:
        container.add_item(Separator())
        container.add_item(TextDisplay("*No bundles in the shop yet — admins can add them in `/fcdex admin` → Shop.*"))

    layout.add_item(container)
    return layout
