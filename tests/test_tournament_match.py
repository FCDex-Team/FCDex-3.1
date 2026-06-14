from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fcdex_3_1.fcdex_ext.tournament_match import (
    _opponent_for_winner,
    format_match_claim_reward_breakdown,
    format_match_claim_summary,
)


def test_format_match_claim_reward_breakdown():
    text = format_match_claim_reward_breakdown(
        tournament_name="Summer Cup",
        match_id=42,
        group_label="Main",
        opponent_mention="<@999>",
        reward_lines=["**+3** tournament points", "🎁 **Bounty pool** · **+500** coins", "**+500** coins"],
    )
    assert "# 🏆 Match victory rewards" in text
    assert "**Summer Cup** · Match **#42** · **Main**" in text
    assert "You defeated <@999>" in text
    assert "## What you received" in text
    assert "- **+3** tournament points" in text
    assert "- 🎁 **Bounty pool** · **+500** coins" in text
    assert "/tournament match" in text


def test_format_match_claim_summary_includes_bets():
    summary = format_match_claim_summary(
        match_id=7,
        group_part=" · **Legacy**",
        opponent_mention="<@111>",
        reward_lines=["**+3** tournament points", "🎁 random **Brazil** clubball"],
        bet_lines=["<@222> won **1,000** coins"],
    )
    assert "Match **#7**" in summary
    assert "**+3** tournament pts" in summary
    assert "Bets settled:" in summary
    assert "<@222> won **1,000** coins" in summary


def test_opponent_for_winner_when_player1_wins():
    match = MagicMock()
    match.player1_id = 10
    match.player2_id = 20
    winner = MagicMock()
    winner.pk = 10
    opponent = MagicMock()

    async def run() -> None:
        with patch("fcdex_3_1.fcdex_ext.tournament_match.Player") as player_model:
            player_model.objects.aget = AsyncMock(return_value=opponent)
            result = await _opponent_for_winner(match, winner)
        assert result is opponent
        player_model.objects.aget.assert_awaited_once_with(pk=20)

    asyncio.run(run())


def test_opponent_for_winner_when_player2_wins():
    match = MagicMock()
    match.player1_id = 10
    match.player2_id = 20
    winner = MagicMock()
    winner.pk = 20
    opponent = MagicMock()

    async def run() -> None:
        with patch("fcdex_3_1.fcdex_ext.tournament_match.Player") as player_model:
            player_model.objects.aget = AsyncMock(return_value=opponent)
            result = await _opponent_for_winner(match, winner)
        assert result is opponent
        player_model.objects.aget.assert_awaited_once_with(pk=10)

    asyncio.run(run())


def test_opponent_for_winner_missing_opponent_id():
    match = MagicMock()
    match.player1_id = 10
    match.player2_id = None
    winner = MagicMock()
    winner.pk = 10

    async def run() -> None:
        with patch("fcdex_3_1.fcdex_ext.tournament_match.Player") as player_model:
            player_model.objects.aget = AsyncMock()
            result = await _opponent_for_winner(match, winner)
        assert result is None
        player_model.objects.aget.assert_not_called()

    asyncio.run(run())
