from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOGIC_PATH = ROOT / "fcdex_3_1" / "fcdex_ext" / "tournament_rewards_logic.py"


class _TournamentPrizeType:
    COINS = "coins"
    RANDOM_COMMON = "random_common"
    BALL = "ball"


class _RewardModel:
    objects = MagicMock()


class _ClaimModel:
    objects = MagicMock()


def _load_logic_module():
    fcdex_models = ModuleType("fcdex_3_1.models")
    fcdex_models.Tournament = object
    fcdex_models.TournamentMatch = SimpleNamespace(objects=MagicMock())
    fcdex_models.TournamentParticipationReward = _RewardModel
    fcdex_models.TournamentParticipantRewardClaim = _ClaimModel
    fcdex_models.TournamentPrizeType = _TournamentPrizeType

    bd_models = ModuleType("bd_models.models")
    bd_models.Player = SimpleNamespace(objects=MagicMock())

    loot = ModuleType("fcdex_3_1.fcdex_ext.tournament_loot")
    loot.grant_prize_entry = AsyncMock(return_value="**+100** coins")

    saved = {
        "fcdex_3_1.models": sys.modules.get("fcdex_3_1.models"),
        "bd_models.models": sys.modules.get("bd_models.models"),
        "fcdex_3_1.fcdex_ext.tournament_loot": sys.modules.get("fcdex_3_1.fcdex_ext.tournament_loot"),
    }
    sys.modules["fcdex_3_1.models"] = fcdex_models
    sys.modules["bd_models.models"] = bd_models
    sys.modules["fcdex_3_1.fcdex_ext.tournament_loot"] = loot
    sys.modules.pop("tournament_rewards_logic_test", None)

    spec = importlib.util.spec_from_file_location("tournament_rewards_logic_test", LOGIC_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name, previous in saved.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous

    return module


@pytest.fixture
def logic():
    return _load_logic_module()


def test_player_ids_with_completed_matches_collects_both_players(logic):
    matches = [SimpleNamespace(player1_id=1, player2_id=2), SimpleNamespace(player1_id=3, player2_id=None)]

    class _Manager:
        def filter(self, **kwargs):
            return self

        def only(self, *args):
            return self

        def __aiter__(self):
            async def _gen():
                for match in matches:
                    yield match

            return _gen()

    with patch.object(logic, "TournamentMatch", SimpleNamespace(objects=_Manager())):
        ids = asyncio.run(logic.player_ids_with_completed_matches(10))
    assert ids == {1, 2, 3}


def test_eligible_participant_ids_excludes_claimed(logic):
    with (
        patch.object(logic, "player_ids_with_completed_matches", AsyncMock(return_value={1, 2, 3})),
        patch.object(logic, "claimed_player_ids", AsyncMock(return_value={2})),
    ):
        eligible = asyncio.run(logic.eligible_participant_ids(5, 9))
    assert eligible == {1, 3}


def test_create_participation_reward_requires_coins(logic):
    tournament = SimpleNamespace(pk=1)
    create = AsyncMock()
    logic.TournamentParticipationReward.objects.acreate = create
    with pytest.raises(ValueError, match="coin amount"):
        asyncio.run(
            logic.create_participation_reward(
                tournament, label="x", description="", prize_type=logic.TournamentPrizeType.COINS, coins=0
            )
        )
    create.assert_not_called()


def test_grant_participation_reward_to_eligible(logic):
    reward = SimpleNamespace(pk=7, tournament_id=4, label="Consolation", get_prize_type_display=lambda: "Coins")
    players = [SimpleNamespace(pk=1), SimpleNamespace(pk=2)]

    class _PlayerManager:
        def filter(self, **kwargs):
            return self

        def __aiter__(self):
            async def _gen():
                for player in players:
                    yield player

            return _gen()

    claim = AsyncMock()
    logic.TournamentParticipantRewardClaim.objects.acreate = claim
    with (
        patch.object(logic, "eligible_participant_ids", AsyncMock(return_value={1, 2})),
        patch.object(logic, "grant_prize_entry", AsyncMock(return_value="**+100** coins")),
        patch.object(logic.Player, "objects", _PlayerManager()),
    ):
        count, message = asyncio.run(logic.grant_participation_reward_to_eligible(reward, guild_id=99))

    assert count == 2
    assert "2" in message
    assert claim.await_count == 2


def test_parse_participation_prize_type_aliases(logic):
    assert logic.parse_participation_prize_type("coins") == logic.TournamentPrizeType.COINS
    assert logic.parse_participation_prize_type("common") == logic.TournamentPrizeType.RANDOM_COMMON
    with pytest.raises(ValueError):
        logic.parse_participation_prize_type("invalid")
