from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from django.utils import timezone

from fcdex_3_1.fcdex_ext.match_logic import (
    MATCH_DAILY_LIMIT,
    match_daily_limit_message,
    match_daily_limit_reached,
    matches_used_today,
    next_reset_delta,
)


def test_match_daily_limit_reached_at_cap():
    assert not match_daily_limit_reached(MATCH_DAILY_LIMIT - 1)
    assert match_daily_limit_reached(MATCH_DAILY_LIMIT)
    assert match_daily_limit_reached(MATCH_DAILY_LIMIT + 1)


def test_match_daily_limit_message_mentions_limit_and_reset():
    message = match_daily_limit_message(now=timezone.now())
    assert str(MATCH_DAILY_LIMIT) in message
    assert "Resets in" in message


def test_next_reset_delta_is_within_24h():
    now = timezone.now()
    remaining = next_reset_delta(now=now)
    assert remaining.total_seconds() > 0
    assert remaining.total_seconds() <= 24 * 3600


def test_matches_used_today_counts_via_queryset(monkeypatch):
    mock_acount = AsyncMock(return_value=3)
    mock_queryset = MagicMock()
    mock_queryset.acount = mock_acount
    mock_objects = MagicMock()
    mock_objects.filter.return_value = mock_queryset

    class _MatchClaim:
        objects = mock_objects

    monkeypatch.setattr("fcdex_3_1.fcdex_ext.match_logic.MatchClaim", _MatchClaim)

    player = SimpleNamespace()
    used = asyncio.run(matches_used_today(player))
    assert used == 3
    mock_objects.filter.assert_called_once()
    _, kwargs = mock_objects.filter.call_args
    assert kwargs["player"] is player
    assert "played_at__gte" in kwargs
