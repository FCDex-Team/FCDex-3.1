"""`/fcdex admin` -> Club Pass: seasons, level rewards, season clubs and premium."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.bd_resolve import resolve_ball_for_lookup
from fcdex_3_1.fcdex_ext.club_pass_logic import (
    MAX_SEASON_MONTHS,
    create_season,
    end_season,
    get_active_season,
    invalidate_season_cache,
    parse_months,
    parse_reward_spec,
    reward_text,
    set_premium,
)
from fcdex_3_1.fcdex_ext.club_pass_views import LAST_PAGE, ball_names_for, level_range
from fcdex_3_1.fcdex_ext.views import AdminHubBackRow, truncate_text
from fcdex_3_1.models import PassLevelReward, PassRewardType, PassSeasonClub, PassTrack

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.club_pass.admin")

_DISCORD_ID_RE = re.compile(r"\d{15,21}")


async def _deny(interaction: Interaction, owner_id: int) -> bool:
    if interaction.user.id != owner_id:
        await interaction.response.send_message("This panel is not yours.", ephemeral=True)
        return True
    return False


async def _refresh(interaction: Interaction, owner_id: int, notice: str = "", page: int = 0) -> None:
    layout = await build_pass_admin_layout(owner_id, notice=notice, page=page)
    await interaction.response.edit_message(view=layout)


class NewSeasonModal(Modal, title="New club pass season"):
    name = TextInput(label="Season name", placeholder="Season 1", max_length=64)
    months = TextInput(label="Months until it ends", placeholder="3", max_length=2, default="3")

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if await _deny(interaction, self.owner_id):
            return
        try:
            months = parse_months(self.months.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if await get_active_season(use_cache=False) is not None:
            await interaction.response.send_message("A season is already running, end it first.", ephemeral=True)
            return
        season = await create_season(self.name.value.strip() or "Season", months)
        await _refresh(
            interaction,
            self.owner_id,
            f"Started **{season.name}**, ends <t:{int(season.ends_at.timestamp())}:D>. Default rewards were added.",
        )


class SetRewardModal(Modal, title="Set level reward"):
    level = TextInput(label="Level (1-50)", placeholder="6", max_length=2)
    track = TextInput(label="Track (normal or premium)", placeholder="normal", max_length=7, default="normal")
    kind = TextInput(label="Type: none, coins, ball, random_common", placeholder="coins", max_length=13)
    value = TextInput(label="Coins amount or clubball name", placeholder="1000", required=False, max_length=100)

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if await _deny(interaction, self.owner_id):
            return
        season = await get_active_season(use_cache=False)
        if season is None:
            await interaction.response.send_message("Start a season first.", ephemeral=True)
            return
        try:
            spec = parse_reward_spec(self.level.value, self.track.value, self.kind.value, self.value.value or "")
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if spec.reward_type == PassRewardType.NONE:
            await PassLevelReward.objects.filter(season=season, level=spec.level, track=spec.track).adelete()
            await _refresh(
                interaction,
                self.owner_id,
                f"Level {spec.level} ({spec.track}) now gives nothing.",
                page=(spec.level - 1) // 10,
            )
            return
        ball_id = None
        if spec.ball_query:
            ball = await resolve_ball_for_lookup(spec.ball_query)
            if ball is None:
                await interaction.response.send_message("Clubball not found.", ephemeral=True)
                return
            ball_id = ball.pk
        await PassLevelReward.objects.aupdate_or_create(
            season=season,
            level=spec.level,
            track=spec.track,
            defaults={"reward_type": spec.reward_type, "coins": spec.coins, "ball_id": ball_id},
        )
        await _refresh(
            interaction, self.owner_id, f"Saved level {spec.level} ({spec.track}).", page=(spec.level - 1) // 10
        )


class SeasonClubModal(Modal, title="Season club"):
    club = TextInput(label="Clubball name or id", max_length=100)

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if await _deny(interaction, self.owner_id):
            return
        season = await get_active_season(use_cache=False)
        if season is None:
            await interaction.response.send_message("Start a season first.", ephemeral=True)
            return
        ball = await resolve_ball_for_lookup(self.club.value)
        if ball is None:
            await interaction.response.send_message("Clubball not found.", ephemeral=True)
            return
        existing = await PassSeasonClub.objects.filter(season=season, ball_id=ball.pk).adelete()
        if existing[0]:
            await _refresh(interaction, self.owner_id, f"Removed **{ball.country}** from the season clubs.")
            return
        await PassSeasonClub.objects.acreate(season=season, ball_id=ball.pk)
        await _refresh(interaction, self.owner_id, f"Added **{ball.country}** to the season clubs (+50% xp).")


class PremiumModal(Modal, title="Club pass premium"):
    user = TextInput(label="Discord user id or mention", max_length=40)
    state = TextInput(label="Premium? yes or no", default="yes", max_length=3)

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if await _deny(interaction, self.owner_id):
            return
        match = _DISCORD_ID_RE.search(self.user.value)
        if match is None:
            await interaction.response.send_message("Send a numeric Discord user id or a mention.", ephemeral=True)
            return
        enable = self.state.value.strip().lower() not in {"no", "n", "false", "0", "off"}
        player, _ = await Player.objects.aget_or_create(discord_id=int(match.group()))
        if not await set_premium(player, enable):
            await interaction.response.send_message("Start a season first.", ephemeral=True)
            return
        await _refresh(
            interaction,
            self.owner_id,
            f"<@{player.discord_id}> is now {'**premium**' if enable else 'on the normal track'}.",
        )


class PassAdminControls(ActionRow):
    def __init__(self, owner_id: int, page: int, *, running: bool):
        super().__init__()
        self.owner_id = owner_id
        self.page = page
        self.new_season.disabled = running
        self.end_current.disabled = not running
        self.set_reward.disabled = not running
        self.clubs.disabled = not running
        self.premium.disabled = not running

    @button(label="New season", style=discord.ButtonStyle.success, emoji="\N{HEAVY PLUS SIGN}")
    async def new_season(self, interaction: Interaction, button: Button):
        if await _deny(interaction, self.owner_id):
            return
        await interaction.response.send_modal(NewSeasonModal(self.owner_id))

    @button(label="End season", style=discord.ButtonStyle.danger, emoji="\N{OCTAGONAL SIGN}")
    async def end_current(self, interaction: Interaction, button: Button):
        if await _deny(interaction, self.owner_id):
            return
        season = await get_active_season(use_cache=False)
        if season is not None:
            await end_season(season)
        await _refresh(interaction, self.owner_id, "Season ended. Unclaimed rewards can no longer be claimed.")

    @button(label="Set reward", style=discord.ButtonStyle.primary, emoji="\N{WRAPPED PRESENT}")
    async def set_reward(self, interaction: Interaction, button: Button):
        if await _deny(interaction, self.owner_id):
            return
        await interaction.response.send_modal(SetRewardModal(self.owner_id))

    @button(label="Clubs", style=discord.ButtonStyle.primary, emoji="\N{SOCCER BALL}")
    async def clubs(self, interaction: Interaction, button: Button):
        if await _deny(interaction, self.owner_id):
            return
        await interaction.response.send_modal(SeasonClubModal(self.owner_id))

    @button(label="Premium", style=discord.ButtonStyle.primary, emoji="\N{GLOWING STAR}")
    async def premium(self, interaction: Interaction, button: Button):
        if await _deny(interaction, self.owner_id):
            return
        await interaction.response.send_modal(PremiumModal(self.owner_id))


class PassAdminPager(ActionRow):
    def __init__(self, owner_id: int, page: int):
        super().__init__()
        self.owner_id = owner_id
        self.page = page
        self.prev_page.disabled = page <= 0
        self.next_page.disabled = page >= LAST_PAGE

    @button(
        label="Prev levels",
        style=discord.ButtonStyle.secondary,
        emoji="\N{LEFTWARDS BLACK ARROW}\N{VARIATION SELECTOR-16}",
    )
    async def prev_page(self, interaction: Interaction, button: Button):
        if await _deny(interaction, self.owner_id):
            return
        await _refresh(interaction, self.owner_id, page=self.page - 1)

    @button(
        label="Next levels",
        style=discord.ButtonStyle.secondary,
        emoji="\N{BLACK RIGHTWARDS ARROW}\N{VARIATION SELECTOR-16}",
    )
    async def next_page(self, interaction: Interaction, button: Button):
        if await _deny(interaction, self.owner_id):
            return
        await _refresh(interaction, self.owner_id, page=self.page + 1)

    @button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}",
    )
    async def refresh(self, interaction: Interaction, button: Button):
        if await _deny(interaction, self.owner_id):
            return
        invalidate_season_cache()
        await _refresh(interaction, self.owner_id, page=self.page)


async def build_pass_admin_layout(owner_id: int, *, notice: str = "", page: int = 0) -> LayoutView:
    page = max(0, min(LAST_PAGE, page))
    season = await get_active_season(use_cache=False)
    layout = LayoutView(timeout=600)
    container = Container()
    container.add_item(
        TextDisplay(
            truncate_text(
                "# \N{TICKET} Club pass admin\n"
                "-# One season at a time, it ends on its end date. Players use `/club pass`.\n"
                "-# **Set reward**: level, track, type (none, coins, ball, random_common) and the amount or club."
            )
        )
    )
    container.add_item(Separator())
    if season is None:
        body = "*No season is running.* Press **New season** to start one with the default rewards."
    else:
        rewards = [r async for r in PassLevelReward.objects.filter(season=season)]
        names = await ball_names_for(rewards)
        by_level: dict[int, dict[str, PassLevelReward]] = {}
        for reward in rewards:
            by_level.setdefault(reward.level, {})[reward.track] = reward
        lines = []
        for level in level_range(page):
            cells = []
            for track, tag in ((PassTrack.NORMAL.value, "N"), (PassTrack.PREMIUM.value, "P")):
                reward = by_level.get(level, {}).get(track)
                if reward is None or reward.reward_type == PassRewardType.NONE:
                    cells.append(f"{tag}: -")
                else:
                    cells.append(f"{tag}: {reward_text(reward, names.get(reward.ball_id) if reward.ball_id else None)}")
            lines.append(f"`L{level:>2}` " + " · ".join(cells))
        clubs = [c.ball.country async for c in PassSeasonClub.objects.filter(season=season).select_related("ball")]
        players = await season.players.acount()
        body = (
            f"**{season.name}** · ends <t:{int(season.ends_at.timestamp())}:F> · **{players}** players\n"
            f"Season clubs: {', '.join(sorted(clubs)) if clubs else '*none*'}\n"
            f"-# Season length is set in months (1-{MAX_SEASON_MONTHS}) when created. Season clubs give +50% xp.\n\n"
            f"### Levels {level_range(page)[0]}-{level_range(page)[-1]}\n" + "\n".join(lines)
        )
    if notice:
        body = f"**{notice}**\n\n{body}"
    container.add_item(TextDisplay(truncate_text(body)))
    container.add_item(Separator())
    container.add_item(PassAdminControls(owner_id, page, running=season is not None))
    container.add_item(PassAdminPager(owner_id, page))
    container.add_item(Separator())
    container.add_item(AdminHubBackRow(owner_id))
    layout.add_item(container)
    return layout
