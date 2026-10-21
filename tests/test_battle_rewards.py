from __future__ import annotations

from fcdex_3_1.fcdex_ext import battle_rewards
from fcdex_3_1.fcdex_ext.battle_rewards import (
    BATTLE_REWARD_DAILY_LIMIT,
    battle_reward_daily_limit_message,
    battle_reward_daily_limit_reached,
    format_battle_challenge_reward_message,
)
from fcdex_3_1.fcdex_ext.pack_logic import PackRewardLine


def test_daily_limit_is_eight():
    assert BATTLE_REWARD_DAILY_LIMIT == 8
    assert not battle_reward_daily_limit_reached(7)
    assert battle_reward_daily_limit_reached(8)
    assert "**8** per day" in battle_reward_daily_limit_message()


def test_no_coin_constants_left():
    assert not hasattr(battle_rewards, "BATTLE_CHALLENGE_COINS_MIN")
    assert not hasattr(battle_rewards, "BATTLE_CHALLENGE_COINS_MAX")


def test_format_battle_challenge_reward_with_ball():
    line = PackRewardLine("Arsenal", 4, -2, None)
    text = format_battle_challenge_reward_message(line)
    assert "**Arsenal**" in text
    assert "`+4%` ATK" in text
    assert "coins" not in text


def test_format_battle_challenge_reward_no_ball():
    text = format_battle_challenge_reward_message(None)
    assert "dex empty" in text
    assert "coins" not in text
