from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Separator, TextDisplay, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.services import (
    achievement_is_complete,
    check_achievements,
    claim_achievement,
    format_achievement_progress,
    get_or_create_stats,
)
from fcdex_3_1.fcdex_ext.views import truncate_text
from fcdex_3_1.models import Achievement, PlayerAchievement

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.achievement.views")


def _reward_message(achievement: Achievement) -> str:
    reward = achievement.reward_ball
    parts: list[str] = []
    if achievement.reward_money:
        parts.append(f"{achievement.reward_money:,} coins")
    if reward is not None:
        parts.append(f"**{reward.country}** card")
    return " + ".join(parts) if parts else "bragging rights"


async def build_catalog_body() -> str:
    lines: list[str] = []
    async for achievement in (
        Achievement.objects.filter(enabled=True, hidden=False).select_related("reward_ball").order_by("name")
    ):
        reward_text = _reward_message(achievement)
        lines.append(
            f"{achievement.emoji} **{achievement.name}**\n"
            f"{achievement.description}\n"
            f"-# Goal: `{achievement.required_count}` · Message rewards: {reward_text}"
        )
    return "\n\n".join(lines[:25]) if lines else ""


async def build_progress_body(owner_id: int) -> tuple[str, str]:
    player, _ = await Player.objects.aget_or_create(discord_id=owner_id)
    await get_or_create_stats(player)
    await check_achievements(player)

    lines: list[str] = []
    async for player_achievement in PlayerAchievement.objects.filter(player=player).select_related(
        "achievement", "achievement__reward_ball"
    ):
        ach = player_achievement.achievement
        status = (
            "✅ Claimed"
            if player_achievement.claimed_at
            else ("🎉 Ready" if achievement_is_complete(player_achievement, ach) else "⏳ In progress")
        )
        reward_text = _reward_message(ach)
        lines.append(
            f"{ach.emoji} **{ach.name}** · `{format_achievement_progress(player_achievement, ach)}`\n"
            f"-# {status} · Message rewards: {reward_text}"
        )

    stats = await get_or_create_stats(player)
    subtitle = (
        f"Battles won `{stats.battles_won}` · Merges `{stats.merges_completed}` · "
        f"Tournament wins `{stats.tournament_wins}` · Joined `{stats.tournament_participations}`"
    )
    body = "\n\n".join(lines) if lines else "*No achievement progress yet.*"
    return subtitle, body


async def load_claimable(player: Player) -> list[Achievement]:
    await check_achievements(player)
    claimable: list[Achievement] = []
    async for pa in PlayerAchievement.objects.filter(player=player, claimed_at__isnull=True).select_related(
        "achievement"
    ):
        if achievement_is_complete(pa, pa.achievement) and pa.achievement.enabled and not pa.achievement.hidden:
            claimable.append(pa.achievement)
    return claimable


class AchievementClaimSelect(discord.ui.Select):
    def __init__(self, owner_id: int, achievements: list[Achievement]):
        self.owner_id = owner_id
        super().__init__(
            placeholder="Choose an achievement to claim…",
            options=[discord.SelectOption(label=a.name[:100], value=str(a.pk)) for a in achievements[:25]],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is private to you.", ephemeral=True)
            return
        achievement = await Achievement.objects.filter(enabled=True, hidden=False).aget(pk=int(self.values[0]))
        player, _ = await Player.objects.aget_or_create(discord_id=self.owner_id)
        _success, message = await claim_achievement(player, achievement)
        layout = await build_achievement_menu(self.owner_id, mode="claim_result", extra=message)
        await interaction.response.edit_message(view=layout)


class AchievementTabControls(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="Catalog", style=discord.ButtonStyle.primary, emoji="🏅")
    async def catalog_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "catalog")

    @button(label="Progress", style=discord.ButtonStyle.secondary, emoji="📊")
    async def progress_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "progress")

    @button(label="Claim", style=discord.ButtonStyle.success, emoji="🎁")
    async def claim_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "claim")

    async def _switch(self, interaction: Interaction, mode: str) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is private to you.", ephemeral=True)
            return
        layout = await build_achievement_menu(self.owner_id, mode=mode)
        await interaction.response.edit_message(view=layout)


async def build_achievement_menu(owner_id: int, *, mode: str = "catalog", extra: str = "") -> LayoutView:
    layout = LayoutView(timeout=300)
    container = Container()

    if mode == "catalog":
        body = await build_catalog_body()
        content = body or "*No achievements configured yet.*"
        title = "🏅 Achievement catalog"
        subtitle = "All public achievements and rewards"
    elif mode == "progress":
        subtitle, content = await build_progress_body(owner_id)
        title = "📊 Your progress"
    elif mode == "claim":
        player, _ = await Player.objects.aget_or_create(discord_id=owner_id)
        claimable = await load_claimable(player)
        if not claimable:
            title = "🎁 Claim rewards"
            content = "*Nothing ready to claim. Check **Progress** for goals.*"
            container.add_item(TextDisplay(truncate_text(f"# {title}\n{content}")))
            container.add_item(Separator())
            container.add_item(AchievementTabControls(owner_id))
            layout.add_item(container)
            return layout
        container.add_item(TextDisplay("# 🎁 Claim rewards\nSelect a completed achievement below."))
        container.add_item(Separator())
        row = ActionRow()
        row.add_item(AchievementClaimSelect(owner_id, claimable))
        container.add_item(row)
        container.add_item(AchievementTabControls(owner_id))
        layout.add_item(container)
        return layout
    elif mode == "claim_result":
        title = "🎁 Claim result"
        content = extra
        subtitle = ""
    else:
        title = "🏆 Achievements"
        content = ""
        subtitle = ""

    header = f"# {title}"
    if subtitle:
        header += f"\n-# {subtitle}"
    container.add_item(TextDisplay(truncate_text(f"{header}\n\n{content}")))
    container.add_item(Separator())
    container.add_item(AchievementTabControls(owner_id))
    layout.add_item(container)
    return layout
