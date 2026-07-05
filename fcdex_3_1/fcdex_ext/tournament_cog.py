from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from django.utils import timezone

from ballsdex.core.utils.transformers import TTLModelTransformer
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.services import increment_stat
from fcdex_3_1.fcdex_ext.tournament_bets import place_bet
from fcdex_3_1.fcdex_ext.tournament_bracket import create_semifinal_pairings, sync_bracket_for_status
from fcdex_3_1.fcdex_ext.tournament_host import tournament_start_eligibility, viewer_can_start_group_stage
from fcdex_3_1.fcdex_ext.tournament_match_views import build_tournament_match_menu
from fcdex_3_1.fcdex_ext.tournament_player_views import build_tournament_player_menu
from fcdex_3_1.fcdex_ext.tournament_schedule import past_end_reason
from fcdex_3_1.fcdex_ext.tournament_views import TournamentManageView
from fcdex_3_1.models import (
    Tournament,
    TournamentGroup,
    TournamentMatch,
    TournamentRegistration,
    TournamentRound,
    TournamentStatus,
)

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.tournament")


class TournamentTransformer(TTLModelTransformer[Tournament]):
    name = "tournament"
    column = "name"
    model = Tournament

    def get_queryset(self):
        return super().get_queryset().exclude(status=TournamentStatus.COMPLETED)

    async def get_from_pk(self, value: int) -> Tournament:
        return await self.get_queryset().select_related("host").aget(pk=value)


TournamentTransform = app_commands.Transform[Tournament, TournamentTransformer]


class TournamentCog(commands.GroupCog, group_name="tournament"):
    """Legacy & Main group tournaments with bracket progression."""

    def __init__(self, bot: BallsDexBot):
        self.bot = bot

    @app_commands.command(
        name="manage",
        description="Admin panel — create, edit, host, bounty vault, participation rewards, delete, and announce",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def manage(self, interaction: discord.Interaction):
        view = TournamentManageView(interaction.user.id)
        await interaction.response.send_message(view=view, ephemeral=True)  # pyright: ignore[reportArgumentType]

    @app_commands.command(name="view", description="Tournament hub — overview, standings, bracket, and join")
    async def view(self, interaction: discord.Interaction, tournament: TournamentTransform):
        show_start = await viewer_can_start_group_stage(interaction, tournament)
        layout = await build_tournament_player_menu(
            interaction.user.id, tournament.pk, mode="overview", show_host_start=show_start
        )
        await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]

    @app_commands.command(name="start", description="Open group stage — create round-robin matches (host only)")
    async def start(self, interaction: discord.Interaction, tournament: TournamentTransform):
        from fcdex_3_1.fcdex_ext.tournament_host import viewer_is_host

        if not await viewer_is_host(interaction, tournament):
            await interaction.response.send_message(
                "Only the tournament **host** can start the group stage.", ephemeral=True
            )
            return
        eligible, reason = await tournament_start_eligibility(tournament)
        if not eligible:
            await interaction.response.send_message(reason or "Cannot start this tournament.", ephemeral=True)
            return
        if error := await run_tournament_start(tournament):
            await interaction.response.send_message(error, ephemeral=True)
            return
        from fcdex_3_1.fcdex_ext.tournament_host import registration_counts_by_group
        from fcdex_3_1.fcdex_ext.tournament_pairings import planned_group_stage_match_count

        counts = await registration_counts_by_group(tournament)
        match_count = planned_group_stage_match_count(
            counts[TournamentGroup.LEGACY.value], counts[TournamentGroup.MAIN.value]
        )
        await interaction.response.send_message(
            f"▶ **{tournament.name}** group stage started — **{match_count}** match(es) created.\n"
            "-# Players use `/tournament match` → **Start battle**.",
            ephemeral=True,
        )

    @app_commands.command(name="match", description="View pending matches and claim victory rewards")
    async def match(self, interaction: discord.Interaction, tournament: TournamentTransform):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        try:
            await TournamentRegistration.objects.aget(tournament=tournament, player=player)
        except TournamentRegistration.DoesNotExist:
            await interaction.response.send_message(
                "You must join this tournament first — use `/tournament view`.", ephemeral=True
            )
            return
        show_start = await viewer_can_start_group_stage(interaction, tournament)
        layout = await build_tournament_match_menu(interaction.user.id, tournament.pk, show_host_start=show_start)
        await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]

    @app_commands.command(
        name="rewards",
        description="Admin — participation prizes for players who completed at least one match (Manage Server)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rewards(self, interaction: discord.Interaction):
        from fcdex_3_1.fcdex_ext.tournament_rewards_views import build_rewards_pick_view

        view = await build_rewards_pick_view(interaction.user.id)
        await interaction.response.send_message(view=view, ephemeral=True)  # pyright: ignore[reportArgumentType]

    @app_commands.command(name="bet", description="Wager coins on who wins a tournament match")
    async def bet(
        self,
        interaction: discord.Interaction,
        tournament: TournamentTransform,
        match_id: app_commands.Range[int, 1, 999_999],
        amount: app_commands.Range[int, 1, 10_000_000],
        participant: discord.Member,
    ):
        if not tournament.betting_enabled:
            await interaction.response.send_message("Betting is disabled for this tournament.", ephemeral=True)
            return
        try:
            match = await TournamentMatch.objects.select_related("player1", "player2").aget(
                pk=match_id, tournament=tournament
            )
        except TournamentMatch.DoesNotExist:
            await interaction.response.send_message("That match was not found in this tournament.", ephemeral=True)
            return

        picked, _ = await Player.objects.aget_or_create(discord_id=participant.id)
        bettor, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        ok, message = await place_bet(tournament, match, bettor, picked, amount)
        await interaction.response.send_message(message, ephemeral=not ok)


async def run_tournament_start(tournament: Tournament) -> str | None:
    eligible, reason = await tournament_start_eligibility(tournament)
    if not eligible:
        return reason

    pairings: list[tuple[str, Player, Player]] = []
    for group in TournamentGroup:
        players = [
            reg.player
            async for reg in TournamentRegistration.objects.filter(
                tournament=tournament, group=group.value
            ).select_related("player")
        ]
        if len(players) < 2:
            continue
        for p1, p2 in itertools.combinations(players, 2):
            pairings.append((group.value, p1, p2))

    if not pairings:
        return "Need at least 2 players in the same group (Legacy or Main) to create matches."

    tournament.status = TournamentStatus.GROUP_STAGE
    tournament.started_at = timezone.now()
    await tournament.asave(update_fields=("status", "started_at"))

    for group_value, p1, p2 in pairings:
        await TournamentMatch.objects.acreate(
            tournament=tournament, round=TournamentRound.GROUP, group=group_value, player1=p1, player2=p2
        )
    return None


async def run_tournament_advance(tournament: Tournament) -> tuple[bool, str]:
    if reason := past_end_reason(tournament):
        return False, reason

    if tournament.status == TournamentStatus.GROUP_STAGE:
        pending_group = await TournamentMatch.objects.filter(
            tournament=tournament, round=TournamentRound.GROUP, completed=False
        ).acount()
        if pending_group:
            return False, (
                f"**{pending_group}** group-stage match(es) still open — "
                "players must finish battles via `/tournament match` first."
            )

        eliminated = 0
        for group in TournamentGroup:
            regs = [
                r
                async for r in TournamentRegistration.objects.filter(tournament=tournament, group=group.value)
                .select_related("player")
                .order_by("-score")
            ]
            if len(regs) <= 1:
                continue
            cutoff_index = max(1, len(regs) // 2)
            for reg in regs[cutoff_index:]:
                if not reg.semifinal_eligible or reg.score < tournament.semifinal_cutoff:
                    reg.eliminated = True
                    await reg.asave(update_fields=("eliminated",))
                    eliminated += 1

            finalists = [r for r in regs if not r.eliminated][:2]
            if len(finalists) == 2:
                if not await TournamentMatch.objects.filter(
                    tournament=tournament, round=TournamentRound.SEMIFINAL, group=group.value
                ).aexists():
                    await TournamentMatch.objects.acreate(
                        tournament=tournament,
                        round=TournamentRound.SEMIFINAL,
                        group=group.value,
                        player1=finalists[0].player,
                        player2=finalists[1].player,
                    )

        tournament.status = TournamentStatus.SEMIFINALS
        await tournament.asave(update_fields=("status",))
        semis_created = await create_semifinal_pairings(tournament)
        extra = f" · **{semis_created}** semifinal pairing(s) created" if semis_created else ""
        return True, f"Semifinals started! **{eliminated}** players eliminated.{extra}"

    if tournament.status == TournamentStatus.SEMIFINALS:
        semis, _ = await sync_bracket_for_status(tournament)
        if semis:
            return True, f"Created **{semis}** missing semifinal pairing(s). Players can use `/tournament match` now."

        pending = await TournamentMatch.objects.filter(
            tournament=tournament, round=TournamentRound.SEMIFINAL, completed=False
        ).acount()
        if pending:
            return False, (
                f"**{pending}** semifinal match(es) still open — "
                "players must finish battles via `/tournament match` first."
            )

        if await TournamentMatch.objects.filter(tournament=tournament, round=TournamentRound.FINAL).aexists():
            return False, "Grand final already exists."

        from fcdex_3_1.fcdex_ext.tournament_bracket import create_final_pairing, semifinal_winner_for_group

        legacy_winner = await semifinal_winner_for_group(tournament, TournamentGroup.LEGACY.value)
        main_winner = await semifinal_winner_for_group(tournament, TournamentGroup.MAIN.value)
        if legacy_winner is None or main_winner is None:
            return False, (
                "Need **Legacy** and **Main** semifinal winners before the grand final — "
                "finish both semifinals via `/tournament match`."
            )

        if not await create_final_pairing(tournament):
            return False, "Grand final already exists or could not be created."

        tournament.status = TournamentStatus.FINALS
        await tournament.asave(update_fields=("status",))
        return (
            True,
            "Grand final created — **Legacy** "
            f"<@{legacy_winner.discord_id}> vs **Main** <@{main_winner.discord_id}>! "
            "Battle via `/tournament match`.",
        )

    if tournament.status == TournamentStatus.FINALS:
        _, final_created = await sync_bracket_for_status(tournament)
        if final_created:
            return True, "Grand final match created! Finalists use `/tournament match` → **Start battle**."

        final = (
            await TournamentMatch.objects.filter(tournament=tournament, round=TournamentRound.FINAL)
            .select_related("player1", "player2", "winner")
            .afirst()
        )
        if not final or not final.player2:
            return False, "No grand final match found."
        if not final.completed or not final.winner:
            return False, "The grand final must be completed via `/tournament match` before closing the tournament."

        tournament.status = TournamentStatus.COMPLETED
        tournament.ended_at = timezone.now()
        await tournament.asave(update_fields=("status", "ended_at"))
        await increment_stat(final.winner, "tournament_wins")
        return True, f"🏆 **{tournament.name}** complete! Winner: <@{final.winner.discord_id}>"

    return False, "This tournament cannot be advanced further."
