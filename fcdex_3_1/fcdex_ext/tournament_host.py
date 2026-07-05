from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, button

from bd_models.models import Player
from fcdex_3_1.fcdex_ext.tournament_pairings import planned_group_stage_match_count
from fcdex_3_1.fcdex_ext.tournament_schedule import start_blocked_reason
from fcdex_3_1.models import Tournament, TournamentGroup, TournamentRegistration, TournamentStatus

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.tournament.host")


async def registration_counts_by_group(tournament: Tournament) -> dict[str, int]:
    counts: dict[str, int] = {}
    for group in TournamentGroup:
        counts[group.value] = await TournamentRegistration.objects.filter(
            tournament=tournament, group=group.value
        ).acount()
    return counts


async def tournament_start_eligibility(tournament: Tournament) -> tuple[bool, str | None]:
    """Whether group stage can be opened now; second value is a user-facing blocker."""
    if tournament.status != TournamentStatus.REGISTRATION:
        return False, "This tournament has already started."
    if reason := start_blocked_reason(tournament):
        return False, reason

    counts = await registration_counts_by_group(tournament)
    total = sum(counts.values())
    legacy = counts[TournamentGroup.LEGACY.value]
    main = counts[TournamentGroup.MAIN.value]

    if total < 2:
        return False, "Need at least **2** players registered (any group) to start."

    if planned_group_stage_match_count(legacy, main) == 0:
        return (
            False,
            "Need at least **2** players in the **same** group (Legacy or Main) to create matches. "
            f"Currently: Legacy **{legacy}**, Main **{main}**.",
        )
    return True, None


def viewer_has_manage_guild(interaction: Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return bool(interaction.user.guild_permissions.manage_guild)


async def viewer_is_host(interaction: Interaction, tournament: Tournament) -> bool:
    host_discord_id = await Player.objects.values_list("discord_id", flat=True).aget(pk=tournament.host_id)
    return interaction.user.id == host_discord_id


async def viewer_can_start_group_stage(interaction: Interaction, tournament: Tournament) -> bool:
    if not await viewer_is_host(interaction, tournament):
        return False
    eligible, _ = await tournament_start_eligibility(tournament)
    return eligible


class TournamentStartGroupRow(ActionRow):
    """Start group stage from player or match hub (host only)."""

    def __init__(self, owner_id: int, tournament_id: int, *, refresh: str):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self.refresh = refresh

    @button(label="Start group stage", style=discord.ButtonStyle.success, emoji="▶")
    async def start_button(self, interaction: Interaction, button: Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is for the player who opened it.", ephemeral=True)
            return
        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        if not await viewer_is_host(interaction, tournament):
            await interaction.response.send_message(
                "Only the tournament **host** can start the group stage.", ephemeral=True
            )
            return

        from fcdex_3_1.fcdex_ext.tournament_cog import run_tournament_start

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        if error := await run_tournament_start(tournament):
            await interaction.response.send_message(error, ephemeral=True)
            return

        counts = await registration_counts_by_group(tournament)
        match_count = planned_group_stage_match_count(
            counts[TournamentGroup.LEGACY.value], counts[TournamentGroup.MAIN.value]
        )
        notice = f"▶ **{tournament.name}** group stage started — **{match_count}** match(es) created."

        if self.refresh == "match":
            from fcdex_3_1.fcdex_ext.tournament_match_views import build_tournament_match_menu

            layout = await build_tournament_match_menu(self.owner_id, self.tournament_id, notice=notice)
        else:
            from fcdex_3_1.fcdex_ext.tournament_player_views import build_tournament_player_menu

            layout = await build_tournament_player_menu(
                self.owner_id, self.tournament_id, mode="overview", notice=notice
            )
        await interaction.response.edit_message(view=layout)
