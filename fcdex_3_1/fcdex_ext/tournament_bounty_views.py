from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from fcdex_3_1.fcdex_ext.tournament_config import cap_error, get_tournament_config
from fcdex_3_1.fcdex_ext.tournament_views import (
    TournamentManageView,
    _deny_manage_guild,
    _deny_owner,
    _owner_mismatch,
    _require_manage_guild,
    load_manageable_tournaments,
)
from fcdex_3_1.fcdex_ext.views import truncate_text
from fcdex_3_1.models import (
    Tournament,
    TournamentGroup,
    TournamentMatch,
    TournamentMatchPrize,
    TournamentPrizeType,
    TournamentRound,
)

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.tournament.bounty")

BountyBackTarget = Literal["manage", "hub"]


async def format_bounty_pool(tournament_id: int) -> str:
    lines: list[str] = []
    async for prize in (
        TournamentMatchPrize.objects.filter(tournament_id=tournament_id).select_related("match").order_by("pk")
    ):
        target = f"match **#{prize.match_id}**" if prize.match_id else f"`{prize.round}`/{prize.group or 'all'}"
        extra = f" · **{prize.coins:,}** coins" if prize.prize_type == TournamentPrizeType.COINS else ""
        tag = prize.label or prize.get_prize_type_display()
        lines.append(f"`#{prize.pk}` **{tag}** · {target}{extra}")
    return "\n".join(lines[:20]) if lines else "*No bounties yet — use **Drop** or **Stash** below.*"


async def create_match_bounty(
    tournament: Tournament, match: TournamentMatch, prize_type: str, *, coins: int = 0, label: str = ""
) -> TournamentMatchPrize:
    if prize_type == TournamentPrizeType.COINS and coins <= 0:
        raise ValueError("Set a coin amount for coin bounties.")
    return await TournamentMatchPrize.objects.acreate(
        tournament=tournament,
        match=match,
        round=match.round,
        group=match.group,
        prize_type=prize_type,
        coins=coins,
        label=label[:64],
    )


async def create_round_bounty(
    tournament: Tournament,
    round_value: str,
    prize_type: str,
    *,
    group: str | None = None,
    coins: int = 0,
    label: str = "",
) -> TournamentMatchPrize:
    if prize_type == TournamentPrizeType.COINS and coins <= 0:
        raise ValueError("Set a coin amount for coin bounties.")
    return await TournamentMatchPrize.objects.acreate(
        tournament=tournament,
        match=None,
        round=round_value,
        group=group,
        prize_type=prize_type,
        coins=coins,
        label=(label or f"{round_value} bounty")[:64],
    )


class TournamentBountyPickView(LayoutView):
    def __init__(self, owner_id: int, tournaments: list[Tournament]):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self._build(tournaments)

    def _build(self, tournaments: list[Tournament]) -> None:
        self.clear_items()
        container = Container()
        if not tournaments:
            container.add_item(
                TextDisplay("# 🎁 Bounty vault\n*No tournaments yet — create one in `/tournament manage` first.*")
            )
        else:
            container.add_item(
                TextDisplay(
                    "# 🎁 Bounty vault\n"
                    "-# Private admin hub · attach loot to matches and rounds\n\n"
                    "Select a tournament to manage prize pools, rules, and betting."
                )
            )
            container.add_item(Separator())
            row = ActionRow()
            row.add_item(
                TournamentBountyTournamentSelect(
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
        container.add_item(TournamentBountyBackRow(self.owner_id, "manage"))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        if not _require_manage_guild(interaction):
            await _deny_manage_guild(interaction)
            return False
        return True


class TournamentBountyTournamentSelect(discord.ui.Select):
    def __init__(self, owner_id: int, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose a tournament…", options=options, min_values=1, max_values=1)
        self.owner_id = owner_id

    async def callback(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        view = await build_tournament_bounty_hub(self.owner_id, int(self.values[0]))
        await interaction.response.edit_message(view=view)


async def build_tournament_bounty_hub(owner_id: int, tournament_id: int, *, notice: str = "") -> LayoutView:
    tournament = await Tournament.objects.aget(pk=tournament_id)
    pool = await format_bounty_pool(tournament_id)
    betting = (
        f"**Betting** · on · `{tournament.min_bet:,}`–`{tournament.max_bet:,}` · "
        f"**{tournament.bet_payout_multiplier}x**"
        if tournament.betting_enabled
        else "**Betting** · off"
    )
    rules_preview = (
        (tournament.rules[:240] + "…")
        if len(tournament.rules) > 240
        else (tournament.rules or "*No rules posted yet.*")
    )

    view = TournamentBountyHubView(owner_id, tournament_id, tournament.name)
    container = Container()
    header = f"# 🎁 Bounty vault · **{tournament.name}**"
    if notice:
        header = f"{notice}\n\n{header}"
    container.add_item(
        TextDisplay(
            truncate_text(f"{header}\n-# {betting}\n\n### Prize pool\n{pool}\n\n### Rules preview\n{rules_preview}")
        )
    )
    container.add_item(Separator())
    container.add_item(TournamentBountyActionRow(owner_id, tournament_id))
    container.add_item(TournamentBountyBackRow(owner_id, "manage", tournament_id=tournament_id))
    view.add_item(container)
    return view


class TournamentBountyHubView(LayoutView):
    def __init__(self, owner_id: int, tournament_id: int, tournament_name: str):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self.tournament_name = tournament_name

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        if not _require_manage_guild(interaction):
            await _deny_manage_guild(interaction)
            return False
        return True


class TournamentBountyActionRow(ActionRow):
    def __init__(self, owner_id: int, tournament_id: int):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    @button(label="Drop", style=discord.ButtonStyle.success, emoji="🎯")
    async def drop_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        matches = [
            m async for m in TournamentMatch.objects.filter(tournament_id=self.tournament_id).order_by("pk")[:25]
        ]
        if not matches:
            await interaction.response.send_message(
                "No matches exist yet — start the group stage first.", ephemeral=True
            )
            return
        view = TournamentBountyDropView(self.owner_id, self.tournament_id, matches)
        await interaction.response.edit_message(view=view)

    @button(label="Stash", style=discord.ButtonStyle.primary, emoji="📦")
    async def stash_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        await interaction.response.send_modal(BountyStashModal(self.owner_id, self.tournament_id))

    @button(label="Configure", style=discord.ButtonStyle.secondary, emoji="📜")
    async def configure_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        await interaction.response.send_modal(BountyConfigureModal(self.owner_id, tournament))

    @button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        view = await build_tournament_bounty_hub(self.owner_id, self.tournament_id, notice="🔄 Refreshed.")
        await interaction.response.edit_message(view=view)


class TournamentBountyDropView(LayoutView):
    def __init__(self, owner_id: int, tournament_id: int, matches: list[TournamentMatch]):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self.selected_match_id = matches[0].pk
        self.selected_prize_type = TournamentPrizeType.RANDOM_COMMON
        self._build(matches)

    def _build(self, matches: list[TournamentMatch]) -> None:
        self.clear_items()
        container = Container()
        container.add_item(
            TextDisplay("# 🎯 Drop bounty\n-# Attach a prize to one match · winners draw from the pool on claim")
        )
        container.add_item(Separator())
        row = ActionRow()
        row.add_item(BountyMatchSelect(self.owner_id, matches, self))
        container.add_item(row)
        row2 = ActionRow()
        row2.add_item(BountyPrizeTypeSelect(self.owner_id, self))
        container.add_item(row2)
        container.add_item(TournamentBountyDropConfirmRow(self.owner_id, self.tournament_id, self))
        container.add_item(TournamentBountyBackRow(self.owner_id, "hub", tournament_id=self.tournament_id))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        return True


class BountyMatchSelect(discord.ui.Select):
    def __init__(self, owner_id: int, matches: list[TournamentMatch], menu: TournamentBountyDropView):
        self.owner_id = owner_id
        self.menu = menu
        super().__init__(
            placeholder="Select match…",
            options=[
                discord.SelectOption(label=f"#{m.pk} · {m.get_round_display()} · {m.group or '—'}", value=str(m.pk))
                for m in matches[:25]
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        self.menu.selected_match_id = int(self.values[0])
        await interaction.response.defer()


class BountyPrizeTypeSelect(discord.ui.Select):
    def __init__(self, owner_id: int, menu: TournamentBountyDropView):
        self.owner_id = owner_id
        self.menu = menu
        super().__init__(
            placeholder="Prize type…",
            options=[
                discord.SelectOption(label="Random common clubball", value=TournamentPrizeType.RANDOM_COMMON),
                discord.SelectOption(label="Coins", value=TournamentPrizeType.COINS),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        self.menu.selected_prize_type = self.values[0]
        await interaction.response.defer()


class TournamentBountyDropConfirmRow(ActionRow):
    def __init__(self, owner_id: int, tournament_id: int, menu: TournamentBountyDropView):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self.menu = menu

    @button(label="Add bounty", style=discord.ButtonStyle.success, emoji="➕")
    async def confirm_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        if self.menu.selected_prize_type == TournamentPrizeType.COINS:
            await interaction.response.send_modal(
                BountyDropCoinsModal(
                    self.owner_id, self.tournament_id, self.menu.selected_match_id, self.menu.selected_prize_type
                )
            )
            return
        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        match = await TournamentMatch.objects.aget(pk=self.menu.selected_match_id, tournament=tournament)
        prize = await create_match_bounty(tournament, match, self.menu.selected_prize_type)
        view = await build_tournament_bounty_hub(
            self.owner_id, self.tournament_id, notice=f"✅ Bounty **#{prize.pk}** dropped on match **#{match.pk}**."
        )
        await interaction.response.edit_message(view=view)


class BountyDropCoinsModal(Modal, title="Coin bounty"):
    coins = TextInput(label="Coin amount", placeholder="500", required=True, max_length=10)
    label = TextInput(label="Label (optional)", required=False, max_length=64)

    def __init__(self, owner_id: int, tournament_id: int, match_id: int, prize_type: str):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self.match_id = match_id
        self.prize_type = prize_type

    async def on_submit(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        try:
            amount = int(self.coins.value.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Coin amount must be a positive number.", ephemeral=True)
            return
        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        match = await TournamentMatch.objects.aget(pk=self.match_id, tournament=tournament)
        prize = await create_match_bounty(
            tournament, match, self.prize_type, coins=amount, label=(self.label.value or "").strip()
        )
        view = await build_tournament_bounty_hub(
            self.owner_id, self.tournament_id, notice=f"✅ Coin bounty **#{prize.pk}** on match **#{match.pk}**."
        )
        await interaction.response.edit_message(view=view)


class BountyStashModal(Modal, title="Stash round bounty"):
    round = TextInput(label="Round", placeholder="group, semifinal, or final", required=True, max_length=12)
    group = TextInput(label="Group (optional)", placeholder="legacy or main", required=False, max_length=8)
    prize_type = TextInput(label="Prize type", placeholder="random_common or coins", required=True, max_length=16)
    coins = TextInput(label="Coins (if coin type)", required=False, max_length=10)
    label = TextInput(label="Label (optional)", required=False, max_length=64)

    def __init__(self, owner_id: int, tournament_id: int):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    async def on_submit(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        round_raw = self.round.value.strip().lower()
        try:
            TournamentRound(round_raw)
        except ValueError:
            await interaction.response.send_message("Round must be `group`, `semifinal`, or `final`.", ephemeral=True)
            return
        round_value = round_raw

        group_value: str | None = None
        if self.group.value.strip():
            group_raw = self.group.value.strip().lower()
            try:
                TournamentGroup(group_raw)
            except ValueError:
                await interaction.response.send_message("Group must be `legacy` or `main`.", ephemeral=True)
                return
            group_value = group_raw

        ptype = self.prize_type.value.strip().lower()
        if ptype not in (TournamentPrizeType.COINS, TournamentPrizeType.RANDOM_COMMON):
            await interaction.response.send_message("Prize type must be `random_common` or `coins`.", ephemeral=True)
            return

        coin_amount = 0
        if ptype == TournamentPrizeType.COINS:
            try:
                coin_amount = int((self.coins.value or "").strip())
                if coin_amount <= 0:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message("Set a valid coin amount.", ephemeral=True)
                return

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        try:
            prize = await create_round_bounty(
                tournament,
                round_value,
                ptype,
                group=group_value,
                coins=coin_amount,
                label=(self.label.value or "").strip(),
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        scope = f"{round_value}{f' · {group_value}' if group_value else ''}"
        view = await build_tournament_bounty_hub(
            self.owner_id, self.tournament_id, notice=f"✅ Stashed bounty **#{prize.pk}** for **{scope}**."
        )
        await interaction.response.edit_message(view=view)


class BountyConfigureModal(Modal, title="Rules & betting"):
    rules = TextInput(label="Rules", style=discord.TextStyle.paragraph, required=False, max_length=4000)
    betting = TextInput(label="Betting (on/off)", required=False, max_length=3, placeholder="on")
    min_bet = TextInput(label="Min bet", required=False, max_length=10)
    max_bet = TextInput(label="Max bet", required=False, max_length=10)
    payout = TextInput(label="Payout multiplier", required=False, max_length=2, placeholder="2")

    def __init__(self, owner_id: int, tournament: Tournament):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament.pk
        self.rules.default = tournament.rules[:4000] if tournament.rules else None
        self.betting.default = "on" if tournament.betting_enabled else "off"
        self.min_bet.default = str(tournament.min_bet)
        self.max_bet.default = str(tournament.max_bet)
        self.payout.default = str(tournament.bet_payout_multiplier)

    async def on_submit(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        update_fields: list[str] = []

        if self.rules.value is not None:
            tournament.rules = self.rules.value[:4000]
            update_fields.append("rules")
        if self.betting.value.strip():
            betting_raw = self.betting.value.strip().lower()
            if betting_raw not in ("on", "off", "yes", "no", "true", "false", "1", "0"):
                await interaction.response.send_message("Betting must be `on` or `off`.", ephemeral=True)
                return
            tournament.betting_enabled = betting_raw in ("on", "yes", "true", "1")
            update_fields.append("betting_enabled")
        try:
            if self.min_bet.value.strip():
                tournament.min_bet = int(self.min_bet.value.strip())
                update_fields.append("min_bet")
            if self.max_bet.value.strip():
                tournament.max_bet = int(self.max_bet.value.strip())
                update_fields.append("max_bet")
            if self.payout.value.strip():
                payout = int(self.payout.value.strip())
                if payout < 1 or payout > 10:
                    raise ValueError
                tournament.bet_payout_multiplier = payout
                update_fields.append("bet_payout_multiplier")
        except ValueError:
            await interaction.response.send_message("Check min/max bet and payout values.", ephemeral=True)
            return

        config = await get_tournament_config()
        if error := cap_error(tournament.min_bet, config.min_bet_cap, "Min bet"):
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        if error := cap_error(tournament.max_bet, config.max_bet_cap, "Max bet"):
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        if error := cap_error(tournament.bet_payout_multiplier, config.bet_payout_multiplier_cap, "Payout multiplier"):
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        if tournament.min_bet > tournament.max_bet:
            await interaction.response.send_message("Min bet cannot exceed max bet.", ephemeral=True)
            return

        await tournament.asave(update_fields=update_fields)
        view = await build_tournament_bounty_hub(
            self.owner_id, self.tournament_id, notice=f"✅ Updated **{tournament.name}** settings."
        )
        await interaction.response.edit_message(view=view)


class TournamentBountyBackRow(ActionRow):
    def __init__(self, owner_id: int, target: BountyBackTarget, *, tournament_id: int | None = None):
        super().__init__()
        self.owner_id = owner_id
        self.target = target
        self.tournament_id = tournament_id

    @button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        if self.target == "manage":
            await interaction.response.edit_message(view=TournamentManageView(self.owner_id))
            return
        if self.target == "hub" and self.tournament_id is not None:
            view = await build_tournament_bounty_hub(self.owner_id, self.tournament_id)
            await interaction.response.edit_message(view=view)
            return
        await interaction.response.edit_message(view=TournamentManageView(self.owner_id))


async def build_bounty_pick_view(owner_id: int) -> LayoutView:
    tournaments = await load_manageable_tournaments()
    return TournamentBountyPickView(owner_id, tournaments)
