from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fcdex_3_1.fcdex_ext import tournament_config
from fcdex_3_1.fcdex_ext.tournament_config import cap_error, get_tournament_config


def test_cap_error_returns_message_when_over_cap():
    assert cap_error(15, 12, "Max participants") == "Max participants cannot exceed the server cap of **12**."


def test_cap_error_returns_none_when_under_cap():
    assert cap_error(10, 12, "Max participants") is None


def test_cap_error_returns_none_when_cap_is_zero():
    assert cap_error(9999, 0, "Max participants") is None


def test_cap_error_returns_none_when_equal_to_cap():
    assert cap_error(12, 12, "Max participants") is None


async def test_get_tournament_config_returns_singleton():
    mock_manager = MagicMock()
    mock_manager.aget_or_create = AsyncMock(return_value=(SimpleNamespace(max_participants_cap=12), True))

    class _FakeConfig:
        objects = mock_manager

    with patch.object(tournament_config, "TournamentConfig", _FakeConfig):
        config = await get_tournament_config()

    assert config.max_participants_cap == 12
    mock_manager.aget_or_create.assert_awaited_once_with(pk=1)
