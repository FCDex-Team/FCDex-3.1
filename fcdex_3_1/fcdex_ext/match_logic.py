from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from fcdex_3_1.models import MatchClaim

if TYPE_CHECKING:
    from bd_models.models import Player

MATCH_DAILY_LIMIT = 5


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
        f"You've reached today's match limit (**{limit}** per day). "
        f"Resets in **{hours}h {minutes}m** (UTC midnight)."
    )
