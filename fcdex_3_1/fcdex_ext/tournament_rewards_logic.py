from __future__ import annotations

from django.db import IntegrityError

from bd_models.models import Player
from fcdex_3_1.fcdex_ext.tournament_loot import grant_prize_entry
from fcdex_3_1.models import (
    Tournament,
    TournamentMatch,
    TournamentParticipantRewardClaim,
    TournamentParticipationReward,
    TournamentPrizeType,
)


async def player_ids_with_completed_matches(tournament_id: int) -> set[int]:
    player_ids: set[int] = set()
    async for match in TournamentMatch.objects.filter(tournament_id=tournament_id, completed=True).only(
        "player1_id", "player2_id"
    ):
        if match.player1_id is not None:
            player_ids.add(match.player1_id)
        if match.player2_id is not None:
            player_ids.add(match.player2_id)
    return player_ids


async def claimed_player_ids(tournament_id: int, reward_id: int) -> set[int]:
    return {
        claim.player_id
        async for claim in TournamentParticipantRewardClaim.objects.filter(
            tournament_id=tournament_id, reward_id=reward_id
        ).only("player_id")
    }


async def eligible_participant_ids(tournament_id: int, reward_id: int) -> set[int]:
    participated = await player_ids_with_completed_matches(tournament_id)
    if not participated:
        return set()
    claimed = await claimed_player_ids(tournament_id, reward_id)
    return participated - claimed


async def count_eligible_participants(tournament_id: int, reward_id: int) -> int:
    return len(await eligible_participant_ids(tournament_id, reward_id))


def format_reward_summary(reward: TournamentParticipationReward) -> str:
    label = reward.label or reward.get_prize_type_display()
    if reward.prize_type == TournamentPrizeType.COINS:
        return f"`#{reward.pk}` **{label}** · **{reward.coins:,}** coins"
    if reward.prize_type == TournamentPrizeType.BALL and reward.ball_id:
        return f"`#{reward.pk}` **{label}** · specific clubball **#{reward.ball_id}**"
    return f"`#{reward.pk}` **{label}** · random common clubball"


async def format_rewards_pool(tournament_id: int) -> str:
    lines: list[str] = []
    async for reward in TournamentParticipationReward.objects.filter(tournament_id=tournament_id).order_by("pk"):
        eligible = await count_eligible_participants(tournament_id, reward.pk)
        claimed = len(await claimed_player_ids(tournament_id, reward.pk))
        lines.append(f"{format_reward_summary(reward)} · eligible **{eligible}** · granted **{claimed}**")
    return "\n".join(lines[:20]) if lines else "*No participation rewards yet — use **Create reward** below.*"


def parse_participation_prize_type(raw: str) -> str:
    value = raw.strip().lower()
    aliases = {
        "coin": TournamentPrizeType.COINS,
        "coins": TournamentPrizeType.COINS,
        "random": TournamentPrizeType.RANDOM_COMMON,
        "random_common": TournamentPrizeType.RANDOM_COMMON,
        "common": TournamentPrizeType.RANDOM_COMMON,
        "ball": TournamentPrizeType.BALL,
        "clubball": TournamentPrizeType.BALL,
        "specific": TournamentPrizeType.BALL,
    }
    if value not in aliases:
        raise ValueError("Prize type must be `coins`, `random_common`, or `ball`.")
    return aliases[value]


async def create_participation_reward(
    tournament: Tournament, *, label: str, description: str, prize_type: str, coins: int = 0, ball_id: int | None = None
) -> TournamentParticipationReward:
    if prize_type == TournamentPrizeType.COINS and coins <= 0:
        raise ValueError("Set a coin amount for coin rewards.")
    if prize_type == TournamentPrizeType.BALL and ball_id is None:
        raise ValueError("Set a clubball for ball-type rewards.")
    return await TournamentParticipationReward.objects.acreate(
        tournament=tournament,
        label=label[:64],
        description=description[:2000],
        prize_type=prize_type,
        coins=coins,
        ball_id=ball_id,
    )


async def grant_participation_reward_to_eligible(
    reward: TournamentParticipationReward, *, guild_id: int | None
) -> tuple[int, str]:
    eligible_ids = await eligible_participant_ids(reward.tournament_id, reward.pk)
    if not eligible_ids:
        return 0, "No eligible participants left for this reward."

    granted = 0
    async for player in Player.objects.filter(pk__in=eligible_ids):
        # Claim the (tournament, player, reward) slot first via the unique constraint — this is
        # the atomic lock. Only grant the prize if we actually won that slot, so two concurrent
        # "Grant all eligible" calls can't both pay the same player for the same reward.
        try:
            await TournamentParticipantRewardClaim.objects.acreate(
                tournament_id=reward.tournament_id, player=player, reward=reward
            )
        except IntegrityError:
            continue
        await grant_prize_entry(player, reward, guild_id=guild_id)
        granted += 1

    label = reward.label or reward.get_prize_type_display()
    return granted, f"Granted **{label}** to **{granted}** participant(s)."
