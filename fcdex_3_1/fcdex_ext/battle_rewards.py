from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from bd_models.models import Player
from fcdex_3_1.fcdex_ext.pack_logic import PackRewardLine, grant_random_clubball
from fcdex_3_1.models import BattleRewardClaim

log = logging.getLogger("fcdex_3_1.battle.rewards")

BATTLE_CHALLENGE_COINS_MIN = 200
BATTLE_CHALLENGE_COINS_MAX = 400
BATTLE_REWARD_DAILY_LIMIT = 10


def _today_start(now: datetime) -> datetime:
    return datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.get_current_timezone())


async def battle_rewards_used_today(player: Player) -> int:
    now = timezone.now()
    return await BattleRewardClaim.objects.filter(player=player, granted_at__gte=_today_start(now)).acount()


def battle_reward_daily_limit_reached(used: int, *, limit: int = BATTLE_REWARD_DAILY_LIMIT) -> bool:
    return used >= limit


def battle_reward_daily_limit_message(*, limit: int = BATTLE_REWARD_DAILY_LIMIT) -> str:
    now = timezone.now()
    next_midnight = _today_start(now) + timedelta(days=1)
    remaining = next_midnight - now
    hours, rem = divmod(int(remaining.total_seconds()), 3600)
    minutes = rem // 60
    return (
        f"You've hit today's battle-reward limit (**{limit}** per day) — the fight still counts, "
        f"but no coins/clubball this time. Resets in **{hours}h {minutes}m** (UTC midnight)."
    )


@dataclass(frozen=True)
class BattleChallengeRewardResult:
    coins: int
    ball_line: PackRewardLine | None
    message: str


def format_battle_challenge_reward_message(coins: int, ball_line: PackRewardLine | None) -> str:
    parts = [f"🎁 **Victory reward** · **+{coins:,}** coins"]
    if ball_line:
        stats = f"`{ball_line.attack_bonus:+}%` ATK · `{ball_line.health_bonus:+}%` HP"
        tag = f" · **{ball_line.special_name}**" if ball_line.special_name else ""
        parts.append(f"**{ball_line.country}** ({stats}){tag}")
    else:
        parts.append("-# No clubball granted (dex empty)")
    return "\n".join(parts)


async def grant_battle_challenge_reward(
    player: Player, *, guild_id: int | None
) -> tuple[bool, str | BattleChallengeRewardResult]:
    used_today = await battle_rewards_used_today(player)
    if battle_reward_daily_limit_reached(used_today):
        return False, battle_reward_daily_limit_message()

    coins = 0
    ball_line: PackRewardLine | None = None
    try:
        coins = random.randint(BATTLE_CHALLENGE_COINS_MIN, BATTLE_CHALLENGE_COINS_MAX)
        await player.add_money(coins)
        ball_line = await grant_random_clubball(player, guild_id=guild_id)
        await BattleRewardClaim.objects.acreate(player=player)
    except Exception:
        log.exception("Battle challenge reward failed for player %s", player.pk)
        return False, "Could not grant match rewards — contact staff if coins or clubballs are missing."

    message = format_battle_challenge_reward_message(coins, ball_line)
    return True, BattleChallengeRewardResult(coins=coins, ball_line=ball_line, message=message)
