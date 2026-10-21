"""Player-facing `/club pass` panel (Components v2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Separator, TextDisplay, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Ball, Player
from fcdex_3_1.fcdex_ext.club_pass_logic import (
    MAX_LEVEL,
    claim_pass_rewards,
    get_pass_progress,
    reward_text,
    unlocked_rewards,
    xp_bar,
)
from fcdex_3_1.fcdex_ext.views import truncate_text
from fcdex_3_1.models import PassLevelReward, PassRewardClaim, PassRewardType, PassSeasonClub, PassTrack

if TYPE_CHECKING:
    from discord import Interaction

LEVELS_PER_PAGE = 10
LAST_PAGE = (MAX_LEVEL - 1) // LEVELS_PER_PAGE


def page_for_level(level: int) -> int:
    return max(0, min(LAST_PAGE, (max(level, 1) - 1) // LEVELS_PER_PAGE))


def level_range(page: int) -> range:
    first = page * LEVELS_PER_PAGE + 1
    return range(first, min(MAX_LEVEL, first + LEVELS_PER_PAGE - 1) + 1)


async def ball_names_for(rewards: list[PassLevelReward]) -> dict[int, str]:
    ids = {r.ball_id for r in rewards if r.ball_id}
    if not ids:
        return {}
    return {b.pk: b.country async for b in Ball.objects.filter(pk__in=ids)}


def format_level_line(
    level: int,
    rewards: dict[str, PassLevelReward],
    claimed: set[tuple[int, str]],
    progress_level: int,
    premium: bool,
    names: dict[int, str],
) -> str:
    parts: list[str] = []
    for track in (PassTrack.NORMAL.value, PassTrack.PREMIUM.value):
        reward = rewards.get(track)
        if reward is None or reward.reward_type == PassRewardType.NONE:
            continue
        text = reward.label or reward_text(reward, names.get(reward.ball_id) if reward.ball_id else None)
        if (level, track) in claimed:
            mark = "\N{WHITE HEAVY CHECK MARK}"
        elif level > progress_level or (track == PassTrack.PREMIUM and not premium):
            mark = "\N{LOCK}"
        else:
            mark = "\N{WRAPPED PRESENT}"
        star = "\N{GLOWING STAR} " if track == PassTrack.PREMIUM else ""
        parts.append(f"{mark} {star}{text}")
    reached = "**" if level <= progress_level else ""
    body = " · ".join(parts) if parts else "-# nothing"
    return f"{reached}L{level}{reached} · {body}"


async def build_pass_layout(user_id: int, *, page: int | None = None, notice: str = "") -> LayoutView:
    player, _ = await Player.objects.aget_or_create(discord_id=user_id)
    progress = await get_pass_progress(player)
    layout = LayoutView(timeout=600)
    container = Container()
    if progress is None:
        container.add_item(
            TextDisplay("# \N{TICKET} Club pass\nNo season is running right now. Ask an admin to start one.")
        )
        layout.add_item(container)
        return layout

    page = page_for_level(progress.level + 1) if page is None else max(0, min(LAST_PAGE, page))
    season = progress.season
    rewards_all = [r async for r in PassLevelReward.objects.filter(season=season)]
    claimed = {
        (level, track)
        async for level, track in PassRewardClaim.objects.filter(player=player, season=season).values_list(
            "level", "track"
        )
    }
    names = await ball_names_for(rewards_all)
    by_level: dict[int, dict[str, PassLevelReward]] = {}
    for reward in rewards_all:
        by_level.setdefault(reward.level, {})[reward.track] = reward
    lines = [
        format_level_line(level, by_level.get(level, {}), claimed, progress.level, progress.premium, names)
        for level in level_range(page)
    ]
    waiting = len(unlocked_rewards(rewards_all, progress.level, progress.premium, claimed))
    club_names = [c.ball.country async for c in PassSeasonClub.objects.filter(season=season).select_related("ball")]

    status = "\N{GLOWING STAR} Premium" if progress.premium else "Normal"
    if progress.maxed:
        xp_line = f"\N{TROPHY} **Level {MAX_LEVEL}** (max) · `{progress.xp_total:,}` xp"
    else:
        xp_line = (
            f"**Level {progress.level}** {xp_bar(progress.xp_total, progress.level, progress.track)} "
            f"`{progress.xp_into_level:,}/{progress.xp_needed:,}` xp to level {progress.level + 1}"
        )
    header = (
        f"# \N{TICKET} Club pass · {season.name}\n"
        f"-# Ends <t:{int(season.ends_at.timestamp())}:R> · {status} track · catch clubballs and win Derby matches "
        "to earn xp, rarer clubballs give more"
    )
    if notice:
        header += f"\n\n{notice}"
    container.add_item(TextDisplay(truncate_text(header)))
    container.add_item(Separator())
    container.add_item(
        TextDisplay(
            truncate_text(
                xp_line + (f"\n\N{WRAPPED PRESENT} **{waiting}** reward(s) ready to claim" if waiting else "")
            )
        )
    )
    container.add_item(Separator())
    container.add_item(
        TextDisplay(truncate_text(f"### Levels {level_range(page)[0]}-{level_range(page)[-1]}\n" + "\n".join(lines)))
    )
    if club_names:
        container.add_item(
            TextDisplay(truncate_text("-# Season clubs (+50% xp): " + ", ".join(sorted(club_names)[:30])))
        )
    container.add_item(PassControls(user_id, page, can_claim=waiting > 0))
    layout.add_item(container)
    return layout


class PassControls(ActionRow):
    def __init__(self, user_id: int, page: int, *, can_claim: bool):
        super().__init__()
        self.user_id = user_id
        self.page = page
        self.claim.disabled = not can_claim
        self.prev_page.disabled = page <= 0
        self.next_page.disabled = page >= LAST_PAGE

    async def _guard(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This pass panel is not yours, use `/club pass`.", ephemeral=True)
            return False
        return True

    @button(label="Claim rewards", style=discord.ButtonStyle.success, emoji="\N{WRAPPED PRESENT}")
    async def claim(self, interaction: Interaction, button: Button):
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        outcome = await claim_pass_rewards(player, guild_id=interaction.guild_id)
        if outcome is None:
            notice = "No season is running right now."
        elif outcome.claimed == 0 and outcome.failed == 0:
            notice = "**Nothing to claim right now.**"
        else:
            notice = "**Claimed!**\n" + "\n".join(outcome.lines)
            if outcome.failed:
                notice += f"\n-# {outcome.failed} reward(s) could not be granted, try again."
        layout = await build_pass_layout(self.user_id, page=self.page, notice=notice)
        await interaction.edit_original_response(view=layout)

    @button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        emoji="\N{LEFTWARDS BLACK ARROW}\N{VARIATION SELECTOR-16}",
    )
    async def prev_page(self, interaction: Interaction, button: Button):
        if not await self._guard(interaction):
            return
        layout = await build_pass_layout(self.user_id, page=self.page - 1)
        await interaction.response.edit_message(view=layout)

    @button(
        label="Next", style=discord.ButtonStyle.secondary, emoji="\N{BLACK RIGHTWARDS ARROW}\N{VARIATION SELECTOR-16}"
    )
    async def next_page(self, interaction: Interaction, button: Button):
        if not await self._guard(interaction):
            return
        layout = await build_pass_layout(self.user_id, page=self.page + 1)
        await interaction.response.edit_message(view=layout)
