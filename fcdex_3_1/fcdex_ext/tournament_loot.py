from __future__ import annotations

import random

from bd_models.models import Ball, BallInstance, Player
from fcdex_3_1.models import TournamentMatch, TournamentMatchPrize, TournamentParticipationReward, TournamentPrizeType

PrizeEntry = TournamentMatchPrize | TournamentParticipationReward


async def _pick_random_common_ball() -> Ball | None:
    enabled = [ball async for ball in Ball.objects.filter(enabled=True)]
    if not enabled:
        return None
    min_rarity = min(ball.rarity for ball in enabled)
    pool = [ball for ball in enabled if ball.rarity == min_rarity]
    return random.choice(pool)


async def load_match_prizes(match: TournamentMatch) -> list[TournamentMatchPrize]:
    specific = [prize async for prize in TournamentMatchPrize.objects.filter(match=match).select_related("ball")]
    if specific:
        return specific
    return [
        prize
        async for prize in TournamentMatchPrize.objects.filter(
            tournament_id=match.tournament_id, match__isnull=True, round=match.round, group=match.group
        ).select_related("ball")
    ]


async def grant_prize_entry(player: Player, prize: PrizeEntry, *, guild_id: int | None) -> str:
    if prize.prize_type == TournamentPrizeType.COINS:
        amount = prize.coins or 0
        if amount:
            await player.add_money(amount)
        return f"**+{amount:,}** coins"

    if prize.prize_type == TournamentPrizeType.BALL and prize.ball_id:
        ball = await Ball.objects.aget(pk=prize.ball_id)
        await BallInstance.objects.acreate(ball=ball, player=player, attack_bonus=0, health_bonus=0, server_id=guild_id)
        return f"**{ball.country}** clubball"

    ball = await _pick_random_common_ball()
    if ball is None:
        return "a mystery prize (no clubballs configured)"
    await BallInstance.objects.acreate(ball=ball, player=player, attack_bonus=0, health_bonus=0, server_id=guild_id)
    return f"random **{ball.country}** clubball"


async def grant_match_loot(match: TournamentMatch, winner: Player, *, guild_id: int | None) -> str:
    prizes = await load_match_prizes(match)
    if not prizes:
        ball = await _pick_random_common_ball()
        if ball is None:
            return "🎁 **Random common** prize — none available right now"
        await BallInstance.objects.acreate(ball=ball, player=winner, attack_bonus=0, health_bonus=0, server_id=guild_id)
        return f"🎁 **Random common** · **{ball.country}** clubball"

    picked = random.choices(prizes, weights=[max(p.weight, 1) for p in prizes], k=1)[0]
    label = picked.label or picked.get_prize_type_display()
    detail = await grant_prize_entry(winner, picked, guild_id=guild_id)
    return f"🎁 **{label}** · {detail}"
