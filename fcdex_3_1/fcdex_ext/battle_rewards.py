from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from bd_models.models import Player
from fcdex_3_1.fcdex_ext.pack_logic import PackRewardLine, grant_random_clubball

log = logging.getLogger("fcdex_3_1.battle.rewards")

BATTLE_CHALLENGE_COINS_MIN = 200
BATTLE_CHALLENGE_COINS_MAX = 400


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
    coins = 0
    ball_line: PackRewardLine | None = None
    try:
        coins = random.randint(BATTLE_CHALLENGE_COINS_MIN, BATTLE_CHALLENGE_COINS_MAX)
        await player.add_money(coins)
        ball_line = await grant_random_clubball(player, guild_id=guild_id)
    except Exception:
        log.exception("Battle challenge reward failed for player %s", player.pk)
        return False, "Could not grant match rewards — contact staff if coins or clubballs are missing."

    message = format_battle_challenge_reward_message(coins, ball_line)
    return True, BattleChallengeRewardResult(coins=coins, ball_line=ball_line, message=message)
