from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from fcdex_3_1.fcdex_ext.rarity_logic import fetch_all_balls
from fcdex_3_1.models import MatchClaim

if TYPE_CHECKING:
    from bd_models.models import Ball, Player

MATCH_DAILY_LIMIT = 5

MATCH_CHALLENGE_BASE_COST = 1_000
MATCH_CHALLENGE_MAX_COST = 20_000


async def _rarity_bounds() -> tuple[float, float]:
    values = [ball.rarity for ball in await fetch_all_balls() if ball.enabled]
    if not values:
        return 0.0, 0.0
    return min(values), max(values)


async def match_challenge_cost(clubball: Ball) -> int:
    """Scale linearly from the max cost (lowest rarity value = rarest) to the base cost (highest value = commonest)."""
    min_rarity, max_rarity = await _rarity_bounds()
    if max_rarity <= min_rarity:
        return MATCH_CHALLENGE_BASE_COST
    ratio = (max_rarity - clubball.rarity) / (max_rarity - min_rarity)
    ratio = max(0.0, min(1.0, ratio))
    cost = MATCH_CHALLENGE_BASE_COST + ratio * (MATCH_CHALLENGE_MAX_COST - MATCH_CHALLENGE_BASE_COST)
    return int(round(cost))


def _today_start(now: datetime) -> datetime:
    return datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.get_current_timezone())


async def matches_used_today(player: Player) -> int:
    now = timezone.now()
    return await MatchClaim.objects.filter(player=player, played_at__gte=_today_start(now)).acount()


def match_daily_limit_reached(used: int, *, limit: int = MATCH_DAILY_LIMIT) -> bool:
    return used >= limit


def next_reset_delta(*, now: datetime | None = None) -> timedelta:
    moment = now or timezone.now()
    next_midnight = _today_start(moment) + timedelta(days=1)
    return next_midnight - moment


def match_daily_limit_message(*, limit: int = MATCH_DAILY_LIMIT, now: datetime | None = None) -> str:
    remaining = next_reset_delta(now=now)
    hours, rem = divmod(int(remaining.total_seconds()), 3600)
    minutes = rem // 60
    return (
        f"You've reached today's match limit (**{limit}** per day). Resets in **{hours}h {minutes}m** (UTC midnight)."
    )
