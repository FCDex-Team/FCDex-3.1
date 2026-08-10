from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Separator, TextDisplay, button

from ballsdex.core.discord import LayoutView
from bd_models.models import BallInstance
from fcdex_3_1.fcdex_ext.rarity_data import RarityCategory, format_rarity_value
from fcdex_3_1.fcdex_ext.rarity_logic import (
    balls_at_rarity,
    build_category_overview,
    build_spawnable_overview,
    build_specials_overview,
    count_catalog,
    fetch_all_balls,
    rarity_distribution,
)
from fcdex_3_1.fcdex_ext.views import truncate_text

if TYPE_CHECKING:
    from discord import Interaction

    from bd_models.models import Ball

log = logging.getLogger("fcdex_3_1.rarity.views")

CATEGORY_MODES: dict[str, RarityCategory] = {
    "spawnable": RarityCategory.SPAWNABLE,
    "unspawnable": RarityCategory.UNSPAWNABLE,
    "specials": RarityCategory.SPECIALS,
}


def _overview_body(all_balls: list[Ball]) -> str:
    counts = count_catalog(all_balls)
    distribution = rarity_distribution(all_balls)
    distinct = len(distribution)
    rarest = next(iter(distribution), "—")
    lines = [
        "Live **BallsDex spawn weights** — lower value = rarer.",
        "",
        f"✅ Spawnable · **{counts['spawnable']}** clubballs",
        f"🚫 Unspawnable · **{counts['unspawnable']}** clubballs",
        "✨ Specials · browse the **Specials** tab",
        f"📈 **{distinct}** distinct spawn weights · rarest spawnable: **r:{rarest}**",
        "",
        "-# Use tabs below · `/fcdex rarity clubball:<card>` · `/fcdex rarity rarity:<value>`",
    ]
    return "\n".join(lines)


class RarityCategoryTabs(ActionRow):
    def __init__(self, owner_id: int, *, mode: str = "overview", page: int = 0):
        super().__init__()
        self.owner_id = owner_id
        self.mode = mode
        self.page = page

    @button(label="Overview", style=discord.ButtonStyle.primary, emoji="📋")
    async def overview_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "overview", 0)

    @button(label="Spawnable", style=discord.ButtonStyle.secondary, emoji="✅")
    async def spawnable_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "spawnable", 0)

    @button(label="Unspawnable", style=discord.ButtonStyle.secondary, emoji="🚫")
    async def unspawnable_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "unspawnable", 0)

    @button(label="Specials", style=discord.ButtonStyle.secondary, emoji="✨")
    async def specials_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "specials", 0)

    async def _switch(self, interaction: Interaction, mode: str, page: int) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is private to you.", ephemeral=True)
            return
        layout = await build_rarity_menu(self.owner_id, mode=mode, page=page)
        await interaction.response.edit_message(view=layout)


class RarityPageRow(ActionRow):
    def __init__(self, owner_id: int, *, page: int, page_count: int):
        super().__init__()
        self.owner_id = owner_id
        self.page = page
        self.page_count = page_count

    @button(label="Prev", style=discord.ButtonStyle.secondary, emoji="◀")
    async def prev_page(self, interaction: Interaction, button: Button):
        if self.page <= 0:
            await interaction.response.send_message("Already on the first page.", ephemeral=True)
            return
        await self._go(interaction, self.page - 1)

    @button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶")
    async def next_page(self, interaction: Interaction, button: Button):
        if self.page >= self.page_count - 1:
            await interaction.response.send_message("Already on the last page.", ephemeral=True)
            return
        await self._go(interaction, self.page + 1)

    async def _go(self, interaction: Interaction, page: int) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is private to you.", ephemeral=True)
            return
        layout = await build_rarity_menu(self.owner_id, mode="spawnable", page=max(0, page))
        await interaction.response.edit_message(view=layout)


async def build_rarity_menu(owner_id: int, *, mode: str = "overview", page: int = 0) -> LayoutView:
    all_balls = await fetch_all_balls()
    layout = LayoutView(timeout=300)
    container = Container()

    if mode == "overview":
        container.add_item(TextDisplay(truncate_text(f"# 📊 FCDex rarity\n\n{_overview_body(all_balls)}")))
    elif mode == "spawnable":
        pages = build_spawnable_overview(all_balls)
        page = max(0, min(page, len(pages) - 1))
        footer = f"\n\n-# Page **{page + 1}/{len(pages)}** · lower spawn weight = rarer"
        container.add_item(TextDisplay(truncate_text(pages[page] + footer)))
        if len(pages) > 1:
            container.add_item(Separator())
            container.add_item(RarityPageRow(owner_id, page=page, page_count=len(pages)))
    elif mode == "specials":
        body = await build_specials_overview()
        container.add_item(TextDisplay(truncate_text(body)))
    elif mode in CATEGORY_MODES:
        body = build_category_overview(all_balls, CATEGORY_MODES[mode])
        container.add_item(TextDisplay(truncate_text(body)))
    else:
        container.add_item(TextDisplay("Unknown rarity view."))

    container.add_item(Separator())
    container.add_item(RarityCategoryTabs(owner_id, mode=mode, page=page))
    layout.add_item(container)
    return layout


async def build_ball_rarity_layout(ball: Ball) -> LayoutView:
    layout = LayoutView(timeout=120)
    container = Container()

    regime_name = getattr(ball.regime, "name", None)
    economy_name = getattr(ball.economy, "name", None) if ball.economy_id else None
    tradeable = "✅ tradeable" if ball.tradeable else "🚫 untradeable"
    spawnable = "✅ spawnable" if ball.enabled else "🚫 unspawnable"

    owner_count = await BallInstance.objects.filter(ball=ball, deleted=False).acount()

    lines = [
        f"# 🔍 {ball.country}",
        f"**r:{format_rarity_value(ball.rarity)}** · `{ball.attack}` ATK · `{ball.health}` HP",
        f"-# {spawnable} · {tradeable} · owned by **{owner_count:,}** player(s)",
    ]
    if regime_name:
        lines.append(f"🏟️ Regime: **{regime_name}**")
    if economy_name:
        lines.append(f"💰 Economy: **{economy_name}**")
    if ball.capacity_name:
        lines.append(f"⚡ Capacity: **{ball.capacity_name}** — {ball.capacity_description or 'No description'}")
    if ball.catch_names:
        aliases = [a.strip() for a in ball.catch_names.split(";") if a.strip()]
        if aliases:
            lines.append(f"📝 Catch aliases: {', '.join(aliases[:5])}")

    container.add_item(TextDisplay(truncate_text("\n".join(lines))))
    layout.add_item(container)
    return layout


async def build_rarity_value_layout(rarity: float) -> LayoutView:
    all_balls = await fetch_all_balls()
    rows = balls_at_rarity(all_balls, rarity, spawnable_only=True)
    layout = LayoutView(timeout=120)
    container = Container()
    display = format_rarity_value(rarity)
    if not rows:
        container.add_item(TextDisplay(f"# r:{display}\nNo spawnable clubballs at this spawn weight."))
    else:
        lines = [f"**{row.name}** · `{row.attack}` ATK · `{row.health}` HP" for row in rows]
        container.add_item(TextDisplay(truncate_text(f"# ✅ Spawnable · r:{display}\n\n" + "\n".join(lines))))
    layout.add_item(container)
    return layout
