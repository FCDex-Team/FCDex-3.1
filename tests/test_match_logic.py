from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from django.utils import timezone

from fcdex_3_1.fcdex_ext.match_logic import (
    MATCH_CHALLENGE_BASE_COST,
    MATCH_CHALLENGE_MAX_COST,
    MATCH_DAILY_LIMIT,
    match_challenge_cost,
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


def _patch_dex_rarities(monkeypatch, rarities: list[float]) -> None:
    pool = [SimpleNamespace(rarity=r, enabled=True) for r in rarities]
    monkeypatch.setattr("fcdex_3_1.fcdex_ext.match_logic.fetch_all_balls", AsyncMock(return_value=pool))


def test_match_challenge_cost_floors_at_base_for_most_common_ball(monkeypatch):
    _patch_dex_rarities(monkeypatch, [1, 25, 50])
    common = SimpleNamespace(rarity=50)
    assert asyncio.run(match_challenge_cost(common)) == MATCH_CHALLENGE_BASE_COST


def test_match_challenge_cost_scales_up_with_rarity(monkeypatch):
    _patch_dex_rarities(monkeypatch, [1, 25, 50])
    cheap = SimpleNamespace(rarity=40)
    pricey = SimpleNamespace(rarity=10)
    cheap_cost = asyncio.run(match_challenge_cost(cheap))
    pricey_cost = asyncio.run(match_challenge_cost(pricey))
    assert pricey_cost > cheap_cost > MATCH_CHALLENGE_BASE_COST


def test_match_challenge_cost_caps_at_max_for_rarest_ball(monkeypatch):
    _patch_dex_rarities(monkeypatch, [1, 25, 50])
    rarest = SimpleNamespace(rarity=1)
    assert asyncio.run(match_challenge_cost(rarest)) == MATCH_CHALLENGE_MAX_COST


def test_match_challenge_cost_with_no_enabled_balls_falls_back_to_base(monkeypatch):
    monkeypatch.setattr(
        "fcdex_3_1.fcdex_ext.match_logic.fetch_all_balls",
        AsyncMock(return_value=[SimpleNamespace(rarity=5, enabled=False)]),
    )
    target = SimpleNamespace(rarity=5)
    assert asyncio.run(match_challenge_cost(target)) == MATCH_CHALLENGE_BASE_COST


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
