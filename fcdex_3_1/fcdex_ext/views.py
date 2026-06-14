from __future__ import annotations

import io
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Separator, TextDisplay, button

from ballsdex.core.discord import LayoutView
from fcdex_3_1.fcdex_ext.battle_engine import BattleBall
from settings.models import settings

if TYPE_CHECKING:
    from fcdex_3_1.fcdex_ext.battle_cog import ActiveBattle

TEXT_DISPLAY_LIMIT = 4000


def truncate_text(text: str, limit: int = TEXT_DISPLAY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_panel_layout(
    *, title: str, subtitle: str = "", sections: list[str] | None = None, footer: str = ""
) -> LayoutView:
    layout = LayoutView()
    container = Container()
    header = f"# {title}"
    if subtitle:
        header += f"\n-# {subtitle}"
    container.add_item(TextDisplay(truncate_text(header)))
    for section in sections or []:
        container.add_item(Separator())
        container.add_item(TextDisplay(truncate_text(section)))
    if footer:
        container.add_item(Separator())
        container.add_item(TextDisplay(truncate_text(footer)))
    layout.add_item(container)
    return layout


def format_lineup(balls: list[BattleBall]) -> str:
    if not balls:
        return "*No clubballs selected yet.*"
    lines = [f"▸ {ball.emoji} **{ball.name}** · `{ball.health}` HP · `{ball.attack}` ATK" for ball in balls]
    text = "\n".join(lines)
    return text[:950] + "\n…" if len(text) > 1024 else text


def _lock_badge(ready: bool) -> str:
    return "🔒 Locked" if ready else "⏳ Picking"


class BattleLineupControls(ActionRow):
    def __init__(self, battle: ActiveBattle):
        super().__init__()
        self.battle = battle

    @button(label="Random 5", style=discord.ButtonStyle.secondary, emoji="🎲")
    async def random_button(self, interaction: discord.Interaction, button: Button):
        from fcdex_3_1.fcdex_ext.battle_cog import apply_lineup_mode, refresh_battle_message

        if message := await apply_lineup_mode(self.battle, interaction, mode="all"):
            if message.startswith("Lineup set"):
                await interaction.response.send_message(message, ephemeral=True)
                await refresh_battle_message(self.battle)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await refresh_battle_message(self.battle)

    @button(label="Strongest", style=discord.ButtonStyle.secondary, emoji="💪")
    async def best_button(self, interaction: discord.Interaction, button: Button):
        from fcdex_3_1.fcdex_ext.battle_cog import apply_lineup_mode, refresh_battle_message

        if message := await apply_lineup_mode(self.battle, interaction, mode="best"):
            if message.startswith("Lineup set"):
                await interaction.response.send_message(message, ephemeral=True)
                await refresh_battle_message(self.battle)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await refresh_battle_message(self.battle)

    @button(label="Clear", style=discord.ButtonStyle.secondary, emoji="🗑️")
    async def clear_button(self, interaction: discord.Interaction, button: Button):
        from fcdex_3_1.fcdex_ext.battle_cog import clear_lineup, refresh_battle_message

        if message := await clear_lineup(self.battle, interaction):
            if message == "Lineup cleared.":
                await interaction.response.send_message(message, ephemeral=True)
                await refresh_battle_message(self.battle)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await refresh_battle_message(self.battle)


class BattleMatchControls(ActionRow):
    def __init__(self, battle: ActiveBattle):
        super().__init__()
        self.battle = battle

    @button(label="Lock Selection", style=discord.ButtonStyle.success, emoji="🔒")
    async def ready_button(self, interaction: discord.Interaction, button: Button):
        await self.battle.mark_ready(interaction)

    @button(label="Cancel Match", style=discord.ButtonStyle.danger, emoji="✖")
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        await self.battle.cancel(interaction)


class BattleLayoutView(LayoutView):
    def __init__(self, battle: ActiveBattle, *, banner: str | None = None, interactive: bool = True):
        super().__init__(timeout=None)
        self.battle = battle
        self.banner = banner
        self.interactive = interactive and battle.is_active
        self._build()

    def _build(self) -> None:
        self.clear_items()
        container = Container()
        battle = self.battle
        collectible = settings.plural_collectible_name.title()

        if self.interactive:
            intro = (f"{self.banner}\n\n" if self.banner else "") + (
                f"# ⚔️ {collectible} Match\n"
                f"{battle.author.mention} **vs** {battle.opponent.mention}\n\n"
                f"Pick your lineup with the buttons below, then **Lock Selection**.\n"
                f"-# Use `/battle card` to add or remove a specific clubball · Max **5** per player"
            )
        else:
            intro = self.banner or "**This match has ended.**"

        container.add_item(TextDisplay(truncate_text(intro)))
        container.add_item(Separator())
        container.add_item(
            TextDisplay(
                f"### {_lock_badge(battle.author_ready)} · {battle.author.display_name}\n"
                f"{format_lineup(battle.instance.p1_balls)}"
            )
        )
        container.add_item(Separator())
        container.add_item(
            TextDisplay(
                f"### {_lock_badge(battle.opponent_ready)} · {battle.opponent.display_name}\n"
                f"{format_lineup(battle.instance.p2_balls)}"
            )
        )
        if self.interactive:
            container.add_item(Separator())
            container.add_item(
                TextDisplay(
                    "### 📋 Match rules\n"
                    "▸ **Random 5** — up to 5 random clubballs (use `/battle random` for instant match)\n"
                    "▸ **Strongest** — your top 5 by ATK + HP\n"
                    "▸ **Clear** — empty your lineup\n"
                    "▸ 30% miss chance · damage varies ±20% from ATK"
                )
            )
            container.add_item(BattleLineupControls(battle))
            container.add_item(BattleMatchControls(battle))
        self.add_item(container)


def build_battle_result_layout(
    battle: ActiveBattle, log_lines: list[str], *, winner_reward_message: str | None = None
) -> LayoutView:
    layout = LayoutView()
    container = Container()
    winner = battle.instance.winner

    container.add_item(
        TextDisplay(
            truncate_text(
                f"# 🏁 Match complete\n"
                f"{battle.author.mention} **vs** {battle.opponent.mention}\n"
                f"**Winner:** {winner or 'Draw — nobody wins'}\n"
                f"**Turns played:** {battle.instance.turns}"
            )
        )
    )

    if winner_reward_message:
        container.add_item(Separator())
        container.add_item(TextDisplay(truncate_text(f"### 🎁 Rewards\n{winner_reward_message}")))

    commentary = "\n".join(log_lines[-14:])
    if commentary:
        container.add_item(Separator())
        container.add_item(TextDisplay(truncate_text(f"### 🎙️ Commentary\n{commentary}")))

    container.add_item(Separator())
    container.add_item(
        TextDisplay(
            truncate_text(
                f"### Final lineups\n"
                f"**{battle.author.display_name}**\n{format_lineup(battle.instance.p1_balls)}\n\n"
                f"**{battle.opponent.display_name}**\n{format_lineup(battle.instance.p2_balls)}"
            )
        )
    )
    container.add_item(Separator())
    container.add_item(TextDisplay("-# Full commentary attached as `match-commentary.txt`"))

    layout.add_item(container)
    return layout


def build_achievement_layout(title: str, body: str, *, subtitle: str = "", footer: str = "") -> LayoutView:
    return build_panel_layout(title=title, subtitle=subtitle, sections=[body] if body else None, footer=footer)


def build_tournament_layout(title: str, sections: list[str], *, subtitle: str = "") -> LayoutView:
    return build_panel_layout(title=title, subtitle=subtitle, sections=sections)


def match_log_file(log_lines: list[str]) -> discord.File:
    return discord.File(io.BytesIO("\n".join(log_lines).encode()), filename="match-commentary.txt")


def battle_log_file(log_lines: list[str]) -> discord.File:
    return match_log_file(log_lines)


class AdminHubBackRow(ActionRow):
    """Back navigation for ephemeral admin sub-panels."""

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="← Admin hub", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: Button):
        from fcdex_3_1.fcdex_ext.admin_hub_views import build_admin_hub_layout
        from fcdex_3_1.fcdex_ext.interaction_context import admin_context

        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        ctx = admin_context(interaction)
        layout = build_admin_hub_layout(self.owner_id, ctx.guild_id, ctx.channel_id)
        await interaction.response.edit_message(view=layout)
