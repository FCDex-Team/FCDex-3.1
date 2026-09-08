from __future__ import annotations

from bd_models.models import Player
from fcdex_3_1.models import Tournament, TournamentBet, TournamentMatch


async def place_bet(
    tournament: Tournament, match: TournamentMatch, bettor: Player, picked: Player, amount: int
) -> tuple[bool, str]:
    if not tournament.betting_enabled:
        return False, "Betting is disabled for this tournament."
    if match.tournament_id != tournament.pk:
        return False, "That match does not belong to this tournament."
    match = await TournamentMatch.objects.aget(pk=match.pk)
    if match.completed:
        return False, "This match is already finished."
    if match.verified_winner_id is not None:
        return False, "This match's battle result is already known — betting is closed."
    if picked.pk not in (match.player1_id, match.player2_id):
        return False, "You can only bet on a match participant."
    if bettor.pk in (match.player1_id, match.player2_id):
        return False, "Players in this match can't place bets on it."
    if amount < tournament.min_bet or amount > tournament.max_bet:
        return False, f"Bets must be between **{tournament.min_bet:,}** and **{tournament.max_bet:,}** coins."

    bettor = await Player.objects.aget(pk=bettor.pk)
    if not bettor.can_afford(amount):
        return False, f"You only have **{bettor.money:,}** coins."

    if await TournamentBet.objects.filter(match=match, bettor=bettor, resolved=False).aexists():
        return False, "You already have an open bet on this match."

    try:
        await bettor.remove_money(amount)
    except ValueError:
        return False, "Not enough coins for that wager."

    await TournamentBet.objects.acreate(tournament=tournament, match=match, bettor=bettor, picked=picked, amount=amount)
    return True, (
        f"Placed **{amount:,}** coins on <@{picked.discord_id}> for match **#{match.pk}** "
        f"({tournament.bet_payout_multiplier}x payout if they win)."
    )


async def resolve_bets_for_match(match: TournamentMatch, winner: Player) -> list[str]:
    tournament = await Tournament.objects.only("bet_payout_multiplier").aget(pk=match.tournament_id)
    lines: list[str] = []
    async for bet in TournamentBet.objects.filter(match=match, resolved=False).select_related("bettor", "picked"):
        payout = bet.amount * tournament.bet_payout_multiplier if bet.picked_id == winner.pk else 0
        updated = await TournamentBet.objects.filter(pk=bet.pk, resolved=False).aupdate(resolved=True, payout=payout)
        if not updated:
            continue
        if payout:
            bettor = await Player.objects.aget(pk=bet.bettor_id)
            await bettor.add_money(payout)
            lines.append(f"<@{bettor.discord_id}> won **{payout:,}** coins")
    return lines
