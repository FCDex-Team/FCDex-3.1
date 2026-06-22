from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Container, Select, Separator, TextDisplay

from ballsdex.core.discord import LayoutView
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.discord_emoji import option_label_with_emoji
from fcdex_3_1.fcdex_ext.shop_logic import format_bundle_line_async, list_shop_bundles, purchase_bundle
from fcdex_3_1.fcdex_ext.views import truncate_text
from fcdex_3_1.models import ShopBundle

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.shop.views")


class ShopBundleSelect(Select):
    def __init__(self, owner_id: int, bundles: list[ShopBundle]):
        self.owner_id = owner_id
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
        layout = await build_shop_layout(interaction.user.id, notice=message)
        await interaction.response.edit_message(view=layout)


async def build_shop_layout(owner_id: int, *, notice: str = "") -> LayoutView:
    player, _ = await Player.objects.aget_or_create(discord_id=owner_id)
    player = await Player.objects.aget(pk=player.pk)
    bundles = await list_shop_bundles(enabled_only=True)

    layout = LayoutView(timeout=300)
    container = Container()
    header = f"# 🛒 FCDex shop\n-# Your balance: **{player.money:,}** coins"
    if notice:
        header += f"\n\n{notice}"
    container.add_item(TextDisplay(truncate_text(header)))

    if bundles:
        lines: list[str] = []
        for bundle in bundles:
            lines.append(await format_bundle_line_async(bundle))
        container.add_item(Separator())
        container.add_item(TextDisplay(truncate_text("\n\n".join(lines))))
        container.add_item(Separator())
        row = ActionRow()
        row.add_item(ShopBundleSelect(owner_id, bundles))
        container.add_item(row)
    else:
        container.add_item(Separator())
        container.add_item(TextDisplay("*No bundles in the shop yet — admins can add them in `/fcdex admin` → Shop.*"))

    layout.add_item(container)
    return layout
