from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Special
from fcdex_3_1.fcdex_ext.bd_resolve import resolve_ball_input
from fcdex_3_1.fcdex_ext.discord_emoji import option_label_with_emoji
from fcdex_3_1.fcdex_ext.interaction_context import AdminContext, admin_context
from fcdex_3_1.fcdex_ext.shop_logic import format_bundle_line_async, list_shop_bundles
from fcdex_3_1.fcdex_ext.views import AdminHubBackRow, truncate_text
from fcdex_3_1.models import ShopBundle, ShopBundleItem

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.shop.admin")


class CreateBundleModal(Modal, title="New shop bundle"):
    name = TextInput(label="Bundle name", max_length=64)
    price = TextInput(label="Coin price", placeholder="1000", max_length=12)
    emoji = TextInput(label="Emoji (optional)", required=False, max_length=8, default="🛒")

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        try:
            price = int(self.price.value.strip().replace(",", ""))
            if price < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Price must be a positive integer.", ephemeral=True)
            return
        name = self.name.value.strip()
        if await ShopBundle.objects.filter(name__iexact=name).aexists():
            await interaction.response.send_message(f"A bundle named **{name}** already exists.", ephemeral=True)
            return
        bundle = await ShopBundle.objects.acreate(
            name=name, price=price, description="", emoji=(self.emoji.value or "🛒")[:32]
        )
        ctx = admin_context(interaction)
        layout = await build_shop_admin_layout(
            self.owner_id, ctx, notice=f"Created **{bundle.name}** (`#{bundle.pk}`)."
        )
        await interaction.response.edit_message(view=layout)


class AddBundleItemModal(Modal, title="Add clubball to bundle"):
    bundle_name = TextInput(label="Bundle name", max_length=64)
    clubball_name = TextInput(label="Clubball", placeholder="Country name or PK (e.g. 42)", max_length=128)
    quantity = TextInput(label="Quantity", placeholder="1", max_length=3, default="1")
    special_name = TextInput(
        label="Special name (optional)",
        required=False,
        placeholder="e.g. Boss — leave empty for normal cards",
        max_length=64,
    )

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        try:
            quantity = int(self.quantity.value.strip())
            if quantity < 1 or quantity > 25:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Quantity must be between 1 and 25.", ephemeral=True)
            return
        try:
            bundle = await ShopBundle.objects.aget(name__iexact=self.bundle_name.value.strip())
        except ShopBundle.DoesNotExist:
            await interaction.response.send_message("Bundle not found.", ephemeral=True)
            return
        ball = await resolve_ball_input(self.clubball_name.value)
        if ball is None:
            await interaction.response.send_message("Clubball not found in the dex.", ephemeral=True)
            return
        special = None
        raw_special = (self.special_name.value or "").strip()
        if raw_special:
            special = await Special.objects.filter(name__iexact=raw_special).afirst()
            if special is None:
                await interaction.response.send_message(f"No special named **{raw_special}**.", ephemeral=True)
                return
        await ShopBundleItem.objects.acreate(bundle=bundle, ball=ball, quantity=quantity, special=special)
        tag = f" with **{special.name}**" if special else ""
        ctx = admin_context(interaction)
        layout = await build_shop_admin_layout(
            self.owner_id, ctx, notice=f"Added **{quantity}×** {ball.country}{tag} to **{bundle.name}**."
        )
        await interaction.response.edit_message(view=layout)


class ShopAdminControls(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="New bundle", style=discord.ButtonStyle.success, emoji="➕")
    async def new_bundle(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(CreateBundleModal(self.owner_id))

    @button(label="Add item", style=discord.ButtonStyle.primary, emoji="🎴")
    async def add_item(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(AddBundleItemModal(self.owner_id))

    @button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_shop_admin_layout(self.owner_id, ctx)
        await interaction.response.edit_message(view=layout)


class ShopBundleToggleSelect(discord.ui.Select):
    def __init__(self, owner_id: int, bundles: list[ShopBundle]):
        self.owner_id = owner_id
        options = [
            discord.SelectOption(
                label=option_label_with_emoji(b.name, b.emoji, default="🛒"),
                value=str(b.pk),
                description=f"{'On' if b.enabled else 'Off'} · {b.price:,} coins"[:100],
            )
            for b in bundles[:25]
        ]
        super().__init__(placeholder="Toggle bundle on/off…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        bundle = await ShopBundle.objects.aget(pk=int(self.values[0]))
        bundle.enabled = not bundle.enabled
        await bundle.asave(update_fields=("enabled",))
        state = "enabled" if bundle.enabled else "disabled"
        ctx = admin_context(interaction)
        layout = await build_shop_admin_layout(self.owner_id, ctx, notice=f"**{bundle.name}** is now {state}.")
        await interaction.response.edit_message(view=layout)


async def build_shop_admin_layout(owner_id: int, ctx: AdminContext, *, notice: str = "") -> LayoutView:
    bundles = await list_shop_bundles(enabled_only=False)
    lines = [await format_bundle_line_async(b) + f"\n-# `#{b.pk}` · {'✅' if b.enabled else '🚫'}" for b in bundles]
    body = "\n\n".join(lines) if lines else "*No bundles yet — create one with **New bundle**.*"
    if notice:
        body = f"**{notice}**\n\n{body}"

    layout = LayoutView(timeout=600)
    container = Container()
    container.add_item(
        TextDisplay(
            truncate_text(
                "# 🛒 Shop admin\n"
                "-# Bundles, clubball rewards, and optional **special** tags per item.\n"
                "-# Players buy via `/fcdex shop`."
            )
        )
    )
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(body)))
    container.add_item(Separator())
    container.add_item(ShopAdminControls(owner_id))
    if bundles:
        row = ActionRow()
        row.add_item(ShopBundleToggleSelect(owner_id, bundles))
        container.add_item(row)
    container.add_item(Separator())
    container.add_item(AdminHubBackRow(owner_id))
    layout.add_item(container)
    return layout
