from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Separator, TextDisplay, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.services import increment_stat
from fcdex_3_1.fcdex_ext.tournament_match_views import build_bracket_sections
from fcdex_3_1.fcdex_ext.tournament_schedule import (
    registration_closed_reason,
    registration_is_open,
    registration_status_label,
    schedule_summary_lines,
)
from fcdex_3_1.fcdex_ext.views import truncate_text
from fcdex_3_1.models import Tournament, TournamentGroup, TournamentRegistration

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.tournament.player_views")


async def build_overview_sections(tournament: Tournament, viewer_id: int | None = None) -> list[str]:
    host_discord_id = await Player.objects.values_list("discord_id", flat=True).aget(pk=tournament.host_id)
    legacy_count = await TournamentRegistration.objects.filter(
        tournament=tournament, group=TournamentGroup.LEGACY
    ).acount()
    main_count = await TournamentRegistration.objects.filter(tournament=tournament, group=TournamentGroup.MAIN).acount()
    schedule_lines = schedule_summary_lines(tournament)
    registration_note = registration_status_label(tournament)

    your_group = ""
    if viewer_id:
        try:
            reg = (
                await TournamentRegistration.objects.filter(tournament=tournament)
                .select_related("player")
                .aget(player__discord_id=viewer_id)
            )
            your_group = f"\n**Your group** · **{reg.get_group_display()}** · `{reg.score}` pts"
        except TournamentRegistration.DoesNotExist:
            if registration_is_open(tournament):
                your_group = "\n**Your group** · *Not registered — pick **Legacy** or **Main** below*"
            else:
                closed = registration_closed_reason(tournament) or "Registration is closed."
                your_group = f"\n**Your group** · *Not registered · {closed}*"

    rules_text = (
        (tournament.rules[:500] + "…")
        if len(tournament.rules) > 500
        else (tournament.rules or "*No rules posted yet.*")
    )
    max_participants_text = "unlimited" if not tournament.max_participants else f"{tournament.max_participants:,}"
    total_count = legacy_count + main_count
    slots_text = f"**{total_count}/{max_participants_text}**" if tournament.max_participants else f"**{total_count}**"
    return [
        f"**Status** · {tournament.get_status_display()}\n"
        f"**Host** · <@{host_discord_id}>\n"
        f"**Registration** · {registration_note}\n"
        f"**Players** · {slots_text} · Legacy **{legacy_count}** · Main **{main_count}\n"
        f"**Semifinal cutoff** · `{tournament.semifinal_cutoff}` pts\n"
        f"**Betting** · {'on' if tournament.betting_enabled else 'off'}"
        + (
            f" · `{tournament.min_bet:,}`–`{tournament.max_bet:,}` · **{tournament.bet_payout_multiplier}x**"
            if tournament.betting_enabled
            else ""
        )
        + your_group
        + ("\n" + "\n".join(schedule_lines) if schedule_lines else ""),
        rules_text,
        tournament.description or "*No description provided.*",
        "-# **Bracket** tab shows **match #** for bets · `/tournament match` (**Start battle**) · "
        "`/tournament bet <match_id> <amount> @participant`",
    ]


async def build_standings_sections(tournament: Tournament) -> list[str]:
    sections: list[str] = []
    for group in TournamentGroup:
        lines: list[str] = []
        queryset = (
            TournamentRegistration.objects.filter(tournament=tournament, group=group.value)
            .select_related("player")
            .order_by("-score", "player_id")
        )
        rank = 1
        async for reg in queryset:
            flag = "❌" if reg.eliminated else ("⚠️" if not reg.semifinal_eligible else "✅")
            lines.append(f"`{rank}.` <@{reg.player.discord_id}> · **{reg.score}** pts · **{group.label}** {flag}")
            rank += 1
        sections.append(f"### {group.label} group\n" + ("\n".join(lines) if lines else "*No players yet*"))
    return sections


class TournamentJoinSelect(discord.ui.Select):
    def __init__(self, owner_id: int, tournament_id: int):
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        super().__init__(
            placeholder="Pick a group to join…",
            options=[
                discord.SelectOption(label="Legacy group", value="legacy", emoji="🛡️"),
                discord.SelectOption(label="Main group", value="main", emoji="⚔️"),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is for the player who opened it.", ephemeral=True)
            return

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        if reason := registration_closed_reason(tournament):
            await interaction.response.send_message(reason, ephemeral=True)
            return

        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        already_registered = await TournamentRegistration.objects.filter(tournament=tournament, player=player).aexists()
        if not already_registered and tournament.max_participants:
            total = await TournamentRegistration.objects.filter(tournament=tournament).acount()
            if total >= tournament.max_participants:
                await interaction.response.send_message(
                    f"❌ This tournament is full (**{tournament.max_participants}** player slots).", ephemeral=True
                )
                return

        group = self.values[0]
        registration, created = await TournamentRegistration.objects.aget_or_create(
            tournament=tournament, player=player, defaults={"group": group}
        )
        if not created:
            await interaction.response.send_message(
                f"You're already in the **{registration.get_group_display()}** group.", ephemeral=True
            )
            return

        await increment_stat(player, "tournament_participations")
        layout = await build_tournament_player_menu(
            interaction.user.id, tournament.pk, mode="overview", notice=f"✅ Joined **{group.title()}** group!"
        )
        await interaction.response.edit_message(view=layout)


class TournamentJoinRow(ActionRow):
    def __init__(self, owner_id: int, tournament_id: int):
        super().__init__()
        self.add_item(TournamentJoinSelect(owner_id, tournament_id))


class TournamentLeaveRow(ActionRow):
    def __init__(self, owner_id: int, tournament_id: int):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    @button(label="Leave tournament", style=discord.ButtonStyle.danger, emoji="🚪")
    async def leave_button(self, interaction: Interaction, button: Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is for the player who opened it.", ephemeral=True)
            return

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        if not registration_is_open(tournament):
            await interaction.response.send_message(
                "You can only leave while **registration** is still open (before the host starts group stage).",
                ephemeral=True,
            )
            return

        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        deleted, _ = await TournamentRegistration.objects.filter(tournament=tournament, player=player).adelete()
        if not deleted:
            await interaction.response.send_message("You aren't registered in this tournament.", ephemeral=True)
            return

        layout = await build_tournament_player_menu(
            interaction.user.id,
            tournament.pk,
            mode="overview",
            notice="You left the tournament. Pick **Legacy** or **Main** below to rejoin.",
        )
        await interaction.response.edit_message(view=layout)


class TournamentPlayerTabControls(ActionRow):
    def __init__(self, owner_id: int, tournament_id: int, active: str):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self.active = active

    @button(label="Overview", style=discord.ButtonStyle.primary, emoji="🏟️")
    async def overview_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "overview")

    @button(label="Standings", style=discord.ButtonStyle.secondary, emoji="📊")
    async def standings_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "standings")

    @button(label="Bracket", style=discord.ButtonStyle.secondary, emoji="🗂️")
    async def bracket_tab(self, interaction: Interaction, button: Button):
        await self._switch(interaction, "bracket")

    async def _switch(self, interaction: Interaction, mode: str) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is for the player who opened it.", ephemeral=True)
            return
        layout = await build_tournament_player_menu(self.owner_id, self.tournament_id, mode=mode)
        await interaction.response.edit_message(view=layout)


async def viewer_can_join(tournament: Tournament, viewer_id: int) -> bool:
    if not registration_is_open(tournament):
        return False
    return not await TournamentRegistration.objects.filter(
        tournament=tournament, player__discord_id=viewer_id
    ).aexists()


async def viewer_is_registered(tournament: Tournament, viewer_id: int) -> bool:
    return await TournamentRegistration.objects.filter(tournament=tournament, player__discord_id=viewer_id).aexists()


async def build_tournament_player_menu(
    owner_id: int, tournament_id: int, *, mode: str = "overview", notice: str = "", show_host_start: bool = False
) -> LayoutView:
    tournament = await Tournament.objects.aget(pk=tournament_id)
    layout = LayoutView(timeout=300)
    container = Container()

    titles = {"overview": "Overview", "standings": "Standings", "bracket": "Bracket"}
    subtitle = f"**{tournament.name}** · {titles.get(mode, mode.title())}"
    if notice:
        subtitle = f"{notice}\n{subtitle}"

    if mode == "overview":
        sections = await build_overview_sections(tournament, viewer_id=owner_id)
    elif mode == "standings":
        sections = await build_standings_sections(tournament)
    else:
        sections = await build_bracket_sections(tournament)

    container.add_item(TextDisplay(truncate_text(f"# 🏟️ Tournament hub\n-# {subtitle}")))
    for section in sections:
        container.add_item(Separator())
        container.add_item(TextDisplay(truncate_text(section)))

    if mode == "overview" and await viewer_can_join(tournament, owner_id):
        container.add_item(Separator())
        container.add_item(TextDisplay("### Join this tournament\nPick **Legacy** or **Main** below."))
        container.add_item(TournamentJoinRow(owner_id, tournament_id))
    elif mode == "overview" and registration_is_open(tournament) and await viewer_is_registered(tournament, owner_id):
        container.add_item(Separator())
        container.add_item(
            TextDisplay("### Leave tournament\nRegistration is still open — you can leave before group stage starts.")
        )
        container.add_item(TournamentLeaveRow(owner_id, tournament_id))

    if mode == "overview" and show_host_start:
        container.add_item(Separator())
        container.add_item(
            TextDisplay(
                "### Start group stage\n"
                "-# **Manage Server** required · opens matches for groups with **≥2** players "
                "(or use `/tournament start`)."
            )
        )
        from fcdex_3_1.fcdex_ext.tournament_host import TournamentStartGroupRow

        container.add_item(TournamentStartGroupRow(owner_id, tournament_id, refresh="player"))

    container.add_item(Separator())
    container.add_item(TournamentPlayerTabControls(owner_id, tournament_id, mode))
    layout.add_item(container)
    return layout
