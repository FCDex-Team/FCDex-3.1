from __future__ import annotations

from fcdex_3_1.fcdex_ext.battle_rewards import (
    BATTLE_CHALLENGE_COINS_MAX,
    BATTLE_CHALLENGE_COINS_MIN,
    format_battle_challenge_reward_message,
)
from fcdex_3_1.fcdex_ext.pack_logic import PackRewardLine


def test_battle_challenge_coin_bounds():
    assert 100 <= BATTLE_CHALLENGE_COINS_MIN <= BATTLE_CHALLENGE_COINS_MAX <= 500


def test_format_battle_challenge_reward_with_ball():
    line = PackRewardLine("Arsenal", 4, -2, None)
    text = format_battle_challenge_reward_message(320, line)
    assert "**+320** coins" in text
    assert "**Arsenal**" in text
    assert "`+4%` ATK" in text


def test_format_battle_challenge_reward_no_ball():
    text = format_battle_challenge_reward_message(250, None)
    assert "**+250** coins" in text
    assert "dex empty" in text
