from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from fcdex_3_1.fcdex_ext.bd_resolve import resolve_ball_input
from fcdex_3_1.fcdex_ext.tournament_rewards_logic import (
    count_eligible_participants,
    create_participation_reward,
    format_rewards_pool,
    grant_participation_reward_to_eligible,
    parse_participation_prize_type,
)
from fcdex_3_1.fcdex_ext.tournament_views import (
    TournamentManageView,
    _deny_manage_guild,
    _deny_owner,
    _owner_mismatch,
    _require_manage_guild,
    load_manageable_tournaments,
)
from fcdex_3_1.fcdex_ext.views import truncate_text
from fcdex_3_1.models import Tournament, TournamentParticipationReward, TournamentPrizeType

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.tournament.rewards")


class TournamentRewardsPickView(LayoutView):
    def __init__(self, owner_id: int, tournaments: list[Tournament]):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self._build(tournaments)

    def _build(self, tournaments: list[Tournament]) -> None:
        self.clear_items()
        container = Container()
        if not tournaments:
            container.add_item(
                TextDisplay(
                    "# 🎖️ Participation rewards\n*No tournaments yet — create one in `/tournament manage` first.*"
                )
            )
        else:
            container.add_item(
                TextDisplay(
                    "# 🎖️ Participation rewards\n"
                    "-# Private admin hub · consolation prizes for players who finished at least one match\n\n"
                    "Select a tournament to configure rewards and grant them to eligible participants."
                )
            )
            container.add_item(Separator())
            row = ActionRow()
            row.add_item(
                TournamentRewardsTournamentSelect(
                    self.owner_id,
                    [
                        discord.SelectOption(
                            label=t.name[:100], value=str(t.pk), description=t.get_status_display()[:100]
                        )
                        for t in tournaments[:25]
                    ],
                )
            )
            container.add_item(row)
        container.add_item(TournamentRewardsBackRow(self.owner_id))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        if not _require_manage_guild(interaction):
            await _deny_manage_guild(interaction)
            return False
        return True


class TournamentRewardsTournamentSelect(discord.ui.Select):
    def __init__(self, owner_id: int, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose a tournament…", options=options, min_values=1, max_values=1)
        self.owner_id = owner_id

    async def callback(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        view = await build_tournament_rewards_hub(self.owner_id, int(self.values[0]))
        await interaction.response.edit_message(view=view)


async def build_tournament_rewards_hub(owner_id: int, tournament_id: int, *, notice: str = "") -> LayoutView:
    tournament = await Tournament.objects.aget(pk=tournament_id)
    pool = await format_rewards_pool(tournament_id)
    body = f"# 🎖️ {tournament.name}\n-# Participation rewards · players need at least one **completed** match\n\n{pool}"
    if notice:
        body = f"{notice}\n\n{body}"
    reward_options = await _reward_select_options(tournament_id)
    return TournamentRewardsHubView(owner_id, tournament_id, truncate_text(body), reward_options)


class TournamentRewardsHubView(LayoutView):
    def __init__(self, owner_id: int, tournament_id: int, body: str, reward_options: list[discord.SelectOption]):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self._build(body, reward_options)

    def _build(self, body: str, reward_options: list[discord.SelectOption]) -> None:
        self.clear_items()
        container = Container()
        container.add_item(TextDisplay(body))
        container.add_item(Separator())
        if reward_options:
            row = ActionRow()
            row.add_item(
                TournamentRewardSelect(
                    self.owner_id, self.tournament_id, reward_options, placeholder="Select a reward…"
                )
            )
            container.add_item(row)
        container.add_item(TournamentRewardsControls(self.owner_id, self.tournament_id))
        container.add_item(TournamentRewardsBackRow(self.owner_id))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        if not _require_manage_guild(interaction):
            await _deny_manage_guild(interaction)
            return False
        return True


async def _reward_select_options(tournament_id: int) -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []
    async for reward in TournamentParticipationReward.objects.filter(tournament_id=tournament_id).order_by("pk")[:25]:
        eligible = await count_eligible_participants(tournament_id, reward.pk)
        label = (reward.label or reward.get_prize_type_display())[:100]
        options.append(
            discord.SelectOption(
                label=label,
                value=str(reward.pk),
                description=f"{eligible} eligible · {reward.get_prize_type_display()}"[:100],
            )
        )
    return options


class TournamentRewardSelect(discord.ui.Select):
    def __init__(self, owner_id: int, tournament_id: int, options: list[discord.SelectOption], *, placeholder: str):
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    async def callback(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        reward = await TournamentParticipationReward.objects.aget(pk=int(self.values[0]))
        eligible = await count_eligible_participants(self.tournament_id, reward.pk)
        label = reward.label or reward.get_prize_type_display()
        view = await build_tournament_rewards_hub(
            self.owner_id, self.tournament_id, notice=f"Selected **{label}** · **{eligible}** player(s) still eligible."
        )
        await interaction.response.edit_message(view=view)


class TournamentRewardsControls(ActionRow):
    def __init__(self, owner_id: int, tournament_id: int):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    @button(label="Create reward", style=discord.ButtonStyle.success, emoji="➕")
    async def create_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        await interaction.response.send_modal(ParticipationRewardCreateModal(self.owner_id, self.tournament_id))

    @button(label="Grant all eligible", style=discord.ButtonStyle.primary, emoji="🎁")
    async def grant_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        rewards = [
            r
            async for r in TournamentParticipationReward.objects.filter(tournament_id=self.tournament_id).order_by("pk")
        ]
        if not rewards:
            await interaction.response.send_message("Create a reward first.", ephemeral=True)
            return
        if len(rewards) == 1:
            reward = rewards[0]
        else:
            view = TournamentRewardsGrantPickView(self.owner_id, self.tournament_id, rewards)
            await interaction.response.edit_message(view=view)
            return
        count, message = await grant_participation_reward_to_eligible(
            reward, guild_id=interaction.guild_id if interaction.guild else None
        )
        notice = message if count else f"⚠️ {message}"
        view = await build_tournament_rewards_hub(self.owner_id, self.tournament_id, notice=notice)
        await interaction.response.edit_message(view=view)

    @button(label="Delete reward", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        rewards = [
            r
            async for r in TournamentParticipationReward.objects.filter(tournament_id=self.tournament_id).order_by("pk")
        ]
        if not rewards:
            await interaction.response.send_message("No rewards to delete.", ephemeral=True)
            return
        view = TournamentRewardsDeletePickView(self.owner_id, self.tournament_id, rewards)
        await interaction.response.edit_message(view=view)

    @button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        view = await build_tournament_rewards_hub(self.owner_id, self.tournament_id, notice="🔄 Refreshed.")
        await interaction.response.edit_message(view=view)


class TournamentRewardsGrantPickView(LayoutView):
    def __init__(self, owner_id: int, tournament_id: int, rewards: list[TournamentParticipationReward]):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self._build(rewards)

    def _build(self, rewards: list[TournamentParticipationReward]) -> None:
        self.clear_items()
        container = Container()
        container.add_item(
            TextDisplay("# 🎁 Grant participation reward\n-# Pick which reward to send to all eligible players")
        )
        container.add_item(Separator())
        row = ActionRow()
        row.add_item(
            TournamentRewardsGrantSelect(
                self.owner_id,
                self.tournament_id,
                [
                    discord.SelectOption(
                        label=(r.label or r.get_prize_type_display())[:100],
                        value=str(r.pk),
                        description=r.get_prize_type_display()[:100],
                    )
                    for r in rewards[:25]
                ],
            )
        )
        container.add_item(row)
        container.add_item(TournamentRewardsBackRow(self.owner_id, tournament_id=self.tournament_id))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        return True


class TournamentRewardsGrantSelect(discord.ui.Select):
    def __init__(self, owner_id: int, tournament_id: int, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose reward…", options=options, min_values=1, max_values=1)
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    async def callback(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        reward = await TournamentParticipationReward.objects.aget(pk=int(self.values[0]))
        count, message = await grant_participation_reward_to_eligible(
            reward, guild_id=interaction.guild_id if interaction.guild else None
        )
        notice = message if count else f"⚠️ {message}"
        view = await build_tournament_rewards_hub(self.owner_id, self.tournament_id, notice=notice)
        await interaction.response.edit_message(view=view)


class TournamentRewardsDeletePickView(LayoutView):
    def __init__(self, owner_id: int, tournament_id: int, rewards: list[TournamentParticipationReward]):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self._build(rewards)

    def _build(self, rewards: list[TournamentParticipationReward]) -> None:
        self.clear_items()
        container = Container()
        container.add_item(
            TextDisplay("# 🗑️ Delete participation reward\n-# This removes the reward and its grant history")
        )
        container.add_item(Separator())
        row = ActionRow()
        row.add_item(
            TournamentRewardsDeleteSelect(
                self.owner_id,
                self.tournament_id,
                [
                    discord.SelectOption(
                        label=(r.label or r.get_prize_type_display())[:100],
                        value=str(r.pk),
                        description=r.get_prize_type_display()[:100],
                    )
                    for r in rewards[:25]
                ],
            )
        )
        container.add_item(row)
        container.add_item(TournamentRewardsBackRow(self.owner_id, tournament_id=self.tournament_id))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        return True


class TournamentRewardsDeleteSelect(discord.ui.Select):
    def __init__(self, owner_id: int, tournament_id: int, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose reward to delete…", options=options, min_values=1, max_values=1)
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    async def callback(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        reward = await TournamentParticipationReward.objects.aget(pk=int(self.values[0]))
        label = reward.label or reward.get_prize_type_display()
        await reward.adelete()
        view = await build_tournament_rewards_hub(
            self.owner_id, self.tournament_id, notice=f"🗑️ Deleted reward **{label}**."
        )
        await interaction.response.edit_message(view=view)


class ParticipationRewardCreateModal(Modal, title="Create participation reward"):
    label = TextInput(label="Label", placeholder="Participation prize", required=False, max_length=64)
    description = TextInput(label="Description", style=discord.TextStyle.paragraph, required=False, max_length=500)
    prize_type = TextInput(
        label="Prize type", placeholder="coins, random_common, or ball", required=True, max_length=16
    )
    coins = TextInput(label="Coins (if coin type)", required=False, max_length=10)
    clubball = TextInput(label="Clubball (if ball type)", required=False, max_length=128, placeholder="Country or PK")

    def __init__(self, owner_id: int, tournament_id: int):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    async def on_submit(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        try:
            prize_type = parse_participation_prize_type(self.prize_type.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        coin_amount = 0
        if prize_type == TournamentPrizeType.COINS:
            try:
                coin_amount = int((self.coins.value or "").strip())
                if coin_amount <= 0:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message("Set a valid coin amount.", ephemeral=True)
                return

        ball_id: int | None = None
        if prize_type == TournamentPrizeType.BALL:
            ball = await resolve_ball_input(self.clubball.value or "")
            if ball is None:
                await interaction.response.send_message("Clubball not found.", ephemeral=True)
                return
            ball_id = ball.pk

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        try:
            reward = await create_participation_reward(
                tournament,
                label=(self.label.value or "").strip(),
                description=(self.description.value or "").strip(),
                prize_type=prize_type,
                coins=coin_amount,
                ball_id=ball_id,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        label = reward.label or reward.get_prize_type_display()
        view = await build_tournament_rewards_hub(
            self.owner_id, self.tournament_id, notice=f"✅ Created reward **{label}** (`#{reward.pk}`)."
        )
        await interaction.response.edit_message(view=view)


class TournamentRewardsBackRow(ActionRow):
    def __init__(self, owner_id: int, *, tournament_id: int | None = None):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    @button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        if self.tournament_id is not None:
            view = await build_tournament_rewards_hub(self.owner_id, self.tournament_id)
            await interaction.response.edit_message(view=view)
            return
        await interaction.response.edit_message(view=TournamentManageView(self.owner_id))


async def build_rewards_pick_view(owner_id: int) -> LayoutView:
    tournaments = await load_manageable_tournaments()
    return TournamentRewardsPickView(owner_id, tournaments)
