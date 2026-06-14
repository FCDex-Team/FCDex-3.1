from __future__ import annotations

from dataclasses import dataclass

import discord
from django.utils import timezone

from bd_models.models import Player
from fcdex_3_1.fcdex_ext.broadcast_logic import DMSendOutcome, send_player_dm
from fcdex_3_1.fcdex_ext.tournament_bets import resolve_bets_for_match
from fcdex_3_1.fcdex_ext.tournament_loot import grant_match_loot, load_match_prizes
from fcdex_3_1.models import (
    Tournament,
    TournamentGroup,
    TournamentMatch,
    TournamentRegistration,
    TournamentRound,
    TournamentStatus,
)


@dataclass(frozen=True, slots=True)
class MatchClaimResult:
    ok: bool
    summary: str
    reward_breakdown: str = ""


def format_match_claim_reward_breakdown(
    *, tournament_name: str, match_id: int, group_label: str, opponent_mention: str, reward_lines: list[str]
) -> str:
    group_part = f" · **{group_label}**" if group_label else ""
    lines = [
        "# 🏆 Match victory rewards",
        "",
        f"**{tournament_name}** · Match **#{match_id}**{group_part}",
        f"You defeated {opponent_mention}",
        "",
        "## What you received",
        *[f"- {line}" for line in reward_lines],
        "",
        "-# Track your next fight with `/tournament match`.",
    ]
    return "\n".join(lines)


def format_match_claim_summary(
    *, match_id: int, group_part: str, opponent_mention: str, reward_lines: list[str], bet_lines: list[str]
) -> str:
    reward_text = ""
    if reward_lines:
        reward_text = " · " + " · ".join(reward_lines)
    bet_text = f"\n-# Bets settled: {', '.join(bet_lines)}" if bet_lines else ""
    return (
        f"🏆 Match **#{match_id}** recorded{group_part}! "
        f"You beat {opponent_mention} · **+3** tournament pts{reward_text}{bet_text}"
    )


async def notify_match_claim_rewards(bot: discord.Client, discord_id: int, reward_breakdown: str) -> DMSendOutcome:
    if not reward_breakdown.strip():
        return DMSendOutcome.SENT
    return await send_player_dm(bot, discord_id, reward_breakdown)


async def _opponent_for_winner(match: TournamentMatch, winner: Player) -> Player | None:
    """Resolve the other participant without synchronous FK access (async-safe)."""
    opponent_id = match.player2_id if winner.pk == match.player1_id else match.player1_id
    if opponent_id is None:
        return None
    return await Player.objects.aget(pk=opponent_id)


async def _player_group(tournament: Tournament, player: Player) -> str | None:
    try:
        reg = await TournamentRegistration.objects.aget(tournament=tournament, player=player)
    except TournamentRegistration.DoesNotExist:
        return None
    return reg.group


async def list_pending_matches(tournament: Tournament, player: Player) -> list[TournamentMatch]:
    """Incomplete matches this player is in (group stage scoped to their registration group)."""
    group = await _player_group(tournament, player)
    matches: list[TournamentMatch] = []
    qs = TournamentMatch.objects.filter(tournament=tournament, completed=False).select_related("player1", "player2")
    if tournament.status == TournamentStatus.GROUP_STAGE and group is not None:
        qs = qs.filter(round=TournamentRound.GROUP, group=group)
    async for match in qs.order_by("round", "created_at"):
        if match.player1_id == player.pk or match.player2_id == player.pk:
            matches.append(match)
    return matches


async def list_open_group_matches_in_group(tournament: Tournament, group: str) -> list[TournamentMatch]:
    return [
        m
        async for m in TournamentMatch.objects.filter(
            tournament=tournament, round=TournamentRound.GROUP, group=group, completed=False
        )
        .select_related("player1", "player2")
        .order_by("pk")
    ]


async def record_battle_verification(match_id: int, winner: Player) -> tuple[bool, str]:
    match = await TournamentMatch.objects.select_related("player1", "player2").aget(pk=match_id)
    if match.completed:
        return False, "This tournament match is already completed."
    if winner.pk not in (match.player1_id, match.player2_id):
        return False, "Battle winner is not a participant in this tournament match."

    updated = await TournamentMatch.objects.filter(pk=match_id, completed=False).aupdate(
        verified_winner_id=winner.pk, verified_at=timezone.now()
    )
    if not updated:
        return False, "This tournament match is already completed."
    return True, "Battle result verified."


async def apply_verified_battle_result(match_id: int, winner: Player, *, guild_id: int | None) -> MatchClaimResult:
    match = await TournamentMatch.objects.aget(pk=match_id)
    if match.completed:
        return MatchClaimResult(False, "This tournament match is already completed.")
    tournament = await Tournament.objects.aget(pk=match.tournament_id)
    ok, message = await record_battle_verification(match_id, winner)
    if not ok:
        return MatchClaimResult(False, message)
    match = await TournamentMatch.objects.aget(pk=match_id)
    return await claim_match_victory(tournament, match, winner, guild_id=guild_id)


async def claim_match_victory(
    tournament: Tournament, match: TournamentMatch, winner: Player, *, guild_id: int | None = None
) -> MatchClaimResult:
    if winner.pk not in (match.player1_id, match.player2_id):
        return MatchClaimResult(False, "You aren't a participant in this match.")
    if match.player2_id is None:
        return MatchClaimResult(False, "This match has no opponent yet.")

    fresh = await TournamentMatch.objects.aget(pk=match.pk)
    if fresh.completed:
        return MatchClaimResult(False, "This match is already completed.")
    if fresh.verified_winner_id is None:
        return MatchClaimResult(
            False,
            (
                "No verified battle result yet — use **Start battle** in this hub, win the match, "
                "then claim your rewards."
            ),
        )
    if fresh.verified_winner_id != winner.pk:
        return MatchClaimResult(False, "Only the verified battle winner can claim this match.")

    score1, score2 = (1, 0) if winner.pk == match.player1_id else (0, 1)
    locked = await TournamentMatch.objects.filter(pk=match.pk, completed=False, verified_winner_id=winner.pk).aupdate(
        winner_id=winner.pk, completed=True, score1=score1, score2=score2
    )
    if not locked:
        return MatchClaimResult(False, "This match is already completed.")

    match = await TournamentMatch.objects.aget(pk=match.pk)

    reward_lines: list[str] = ["**+3** tournament points"]
    if not match.reward_claimed:
        prize_pool = await load_match_prizes(match)
        loot_text = await grant_match_loot(match, winner, guild_id=guild_id)
        reward_lines.append(loot_text)
        if not prize_pool and tournament.match_win_reward:
            await winner.add_money(tournament.match_win_reward)
            reward_lines.append(f"**+{tournament.match_win_reward:,}** coins")
        await TournamentMatch.objects.filter(pk=match.pk, reward_claimed=False).aupdate(reward_claimed=True)

    try:
        registration = await TournamentRegistration.objects.aget(tournament=tournament, player=winner)
        registration.score += 3
        if tournament.semifinal_cutoff and registration.score < tournament.semifinal_cutoff:
            registration.semifinal_eligible = False
        await registration.asave(update_fields=("score", "semifinal_eligible"))
    except TournamentRegistration.DoesNotExist:
        # Verified winner without a registration row — record match only, no bracket points.
        pass

    bet_lines = await resolve_bets_for_match(match, winner)

    opponent = await _opponent_for_winner(match, winner)
    try:
        group_label = TournamentGroup(match.group).label if match.group else ""
        group_part = f" · **{group_label}**" if group_label else ""
    except ValueError:
        group_label = ""
        group_part = ""
    opponent_mention = f"<@{opponent.discord_id}>" if opponent else "your opponent"
    reward_breakdown = format_match_claim_reward_breakdown(
        tournament_name=tournament.name,
        match_id=match.pk,
        group_label=group_label,
        opponent_mention=opponent_mention,
        reward_lines=reward_lines,
    )
    summary = format_match_claim_summary(
        match_id=match.pk,
        group_part=group_part,
        opponent_mention=opponent_mention,
        reward_lines=reward_lines,
        bet_lines=bet_lines,
    )
    return MatchClaimResult(True, summary, reward_breakdown)
