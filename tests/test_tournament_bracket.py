from __future__ import annotations

from types import SimpleNamespace

from fcdex_3_1.fcdex_ext.tournament_match_views import _build_knockout_ascii_tree, _player_label, _winner_label


def _match(
    *, p1_id: int = 1, p2_id: int = 2, winner_id: int | None = None, p1_discord: int = 101, p2_discord: int = 102
) -> SimpleNamespace:
    return SimpleNamespace(
        pk=1,
        player1=SimpleNamespace(pk=p1_id, discord_id=p1_discord),
        player2=SimpleNamespace(pk=p2_id, discord_id=p2_discord),
        winner_id=winner_id,
        winner=SimpleNamespace(pk=winner_id, discord_id=999) if winner_id else None,
        completed=bool(winner_id),
    )


def test_player_label_shows_pending_player():
    match = _match()
    assert _player_label(match, "player1") == "<@101>"  # type: ignore[arg-type]


def test_player_label_marks_winner_and_loser():
    match = _match(winner_id=1)
    assert "**<@101>**" in _player_label(match, "player1")  # type: ignore[arg-type]
    assert "✓" in _player_label(match, "player1")  # type: ignore[arg-type]
    assert "~~<@102>~~" in _player_label(match, "player2")  # type: ignore[arg-type]
    assert "✗" in _player_label(match, "player2")  # type: ignore[arg-type]


def test_winner_label_shows_pending():
    assert _winner_label(_match()) == "_pending_"  # type: ignore[arg-type]


def test_winner_label_shows_champion():
    match = _match(winner_id=2)
    assert "<@999>" in _winner_label(match)  # type: ignore[arg-type]


def test_build_knockout_ascii_tree_renders_all_rounds():
    sf1 = _match(p1_id=1, p2_id=2, winner_id=1, p1_discord=101, p2_discord=102)
    sf2 = _match(p1_id=3, p2_id=4, winner_id=4, p1_discord=103, p2_discord=104)
    final = _match(p1_id=1, p2_id=4, winner_id=1, p1_discord=101, p2_discord=104)
    text = _build_knockout_ascii_tree([sf1, sf2], final)  # type: ignore[arg-type]
    assert "semifinal 1" in text
    assert "semifinal 2" in text
    assert "final" in text
    assert "<@101>" in text
    assert "<@104>" in text


def test_build_knockout_ascii_tree_returns_empty_for_less_than_two_semifinals():
    sf1 = _match()
    assert _build_knockout_ascii_tree([sf1], None) == ""  # type: ignore[arg-type]
