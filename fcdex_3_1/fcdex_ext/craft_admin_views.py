from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from fcdex_3_1.fcdex_ext.bd_resolve import resolve_ball_input
from fcdex_3_1.fcdex_ext.interaction_context import AdminContext, admin_context
from fcdex_3_1.fcdex_ext.views import AdminHubBackRow, truncate_text
from fcdex_3_1.models import SBCRecipe, SBCRecipeType

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.craft.admin")


class CreateSBCModal(Modal, title="New SBC recipe"):
    name = TextInput(label="Recipe name", max_length=64)
    recipe_type = TextInput(
        label="Recipe type",
        default="standard",
        max_length=20,
        placeholder="standard, clubball_to_custom, custom_to_card",
    )
    required_ball = TextInput(label="Required clubball", placeholder="PK or country name", max_length=128)
    required_count = TextInput(label="Required count", default="1", max_length=3)
    reward_ball = TextInput(label="Reward clubball", placeholder="PK or country name", max_length=128)
    reward_money = TextInput(label="Bonus coins (optional)", required=False, default="0", max_length=12)

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        try:
            req_count = int(self.required_count.value.strip())
            reward_money = int((self.reward_money.value or "0").strip().replace(",", ""))
            if req_count < 1 or reward_money < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Invalid count or coin reward.", ephemeral=True)
            return
        recipe_type = self.recipe_type.value.strip().lower()
        if recipe_type not in SBCRecipeType.values:
            await interaction.response.send_message(
                f"Recipe type must be one of: {', '.join(SBCRecipeType.values)}.", ephemeral=True
            )
            return
        req_ball = await resolve_ball_input(self.required_ball.value)
        rew_ball = await resolve_ball_input(self.reward_ball.value)
        if req_ball is None or rew_ball is None:
            await interaction.response.send_message("Could not find one of the clubballs in the dex.", ephemeral=True)
            return
        name = self.name.value.strip()
        if await SBCRecipe.objects.filter(name__iexact=name).aexists():
            await interaction.response.send_message(f"Recipe **{name}** already exists.", ephemeral=True)
            return
        await SBCRecipe.objects.acreate(
            name=name,
            description="",
            recipe_type=recipe_type,
            required_ball=req_ball,
            required_count=req_count,
            reward_ball=rew_ball,
            reward_money=reward_money,
        )
        ctx = admin_context(interaction)
        layout = await build_craft_admin_layout(self.owner_id, ctx, notice=f"Created SBC **{name}**.")
        await interaction.response.edit_message(view=layout)


class CraftAdminControls(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="New recipe", style=discord.ButtonStyle.success, emoji="➕")
    async def new_recipe(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(CreateSBCModal(self.owner_id))

    @button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_craft_admin_layout(self.owner_id, ctx)
        await interaction.response.edit_message(view=layout)


class SBCRecipeToggleSelect(discord.ui.Select):
    def __init__(self, owner_id: int, recipes: list[SBCRecipe]):
        self.owner_id = owner_id
        options = [
            discord.SelectOption(
                label=r.name[:100], value=str(r.pk), description=f"{'On' if r.enabled else 'Off'}"[:100]
            )
            for r in recipes[:25]
        ]
        super().__init__(placeholder="Enable / disable recipe…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        recipe = await SBCRecipe.objects.aget(pk=int(self.values[0]))
        recipe.enabled = not recipe.enabled
        await recipe.asave(update_fields=("enabled",))
        state = "enabled" if recipe.enabled else "disabled"
        ctx = admin_context(interaction)
        layout = await build_craft_admin_layout(self.owner_id, ctx, notice=f"**{recipe.name}** is now {state}.")
        await interaction.response.edit_message(view=layout)


async def build_craft_admin_layout(owner_id: int, ctx: AdminContext, *, notice: str = "") -> LayoutView:
    recipes = [r async for r in SBCRecipe.objects.select_related("required_ball", "reward_ball").order_by("name")]
    lines: list[str] = []
    for recipe in recipes:
        type_label = recipe.get_recipe_type_display()
        lines.append(
            f"**{recipe.name}** — **{type_label}**\n"
            f"**{recipe.required_count}×** {recipe.required_ball.country} → "
            f"**{recipe.reward_ball.country}**"
            + (f" · **+{recipe.reward_money:,}** coins" if recipe.reward_money else "")
            + f"\n-# `#{recipe.pk}` · {'✅' if recipe.enabled else '🚫'}"
        )
    body = "\n\n".join(lines) if lines else "*No recipes — use **New recipe**.*"
    if notice:
        body = f"**{notice}**\n\n{body}"

    layout = LayoutView(timeout=600)
    container = Container()
    container.add_item(
        TextDisplay(
            truncate_text(
                "# 🧪 Craft admin\n"
                "-# Manage SBC recipes without the web panel.\n"
                "-# Clubball fields accept **PK or country name**."
            )
        )
    )
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(body)))
    container.add_item(Separator())
    container.add_item(CraftAdminControls(owner_id))
    if recipes:
        row = ActionRow()
        row.add_item(SBCRecipeToggleSelect(owner_id, recipes))
        container.add_item(row)
    container.add_item(Separator())
    container.add_item(AdminHubBackRow(owner_id))
    layout.add_item(container)
    return layout
