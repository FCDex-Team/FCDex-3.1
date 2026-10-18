from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from fcdex_3_1.fcdex_ext import tournament_join
from fcdex_3_1.fcdex_ext.tournament_join import (
    BUTTON_TEMPLATE,
    TournamentActionButton,
    build_announcement_layout,
    join_tournament,
    leave_tournament,
)
from tests.conftest import make_tournament

PLAYER = SimpleNamespace(pk=7, discord_id=5)


class FakeRegistration:
    def __init__(self, group: str):
        self.group = group
        self.deleted = False

    def get_group_display(self) -> str:
        return self.group.title()

    async def adelete(self):
        self.deleted = True


class FakeRegistrations:
    """Just enough of TournamentRegistration.objects for join and leave."""

    def __init__(self, existing: FakeRegistration | None = None, total: int = 1):
        self.existing = existing
        self.total = total
        self.created: FakeRegistration | None = None
        self.deleted_rows = 1

    async def aget_or_create(self, **kwargs):
        if self.existing is not None:
            return self.existing, False
        self.created = FakeRegistration(kwargs["defaults"]["group"])
        return self.created, True

    def filter(self, **kwargs):
        return self

    async def acount(self):
        return self.total

    async def adelete(self):
        return self.deleted_rows, {}


@pytest.fixture
def stats(monkeypatch):
    increment, decrement = AsyncMock(), AsyncMock()
    monkeypatch.setattr(tournament_join, "increment_stat", increment)
    monkeypatch.setattr(tournament_join, "decrement_stat", decrement)
    return SimpleNamespace(increment=increment, decrement=decrement)


def use_registrations(monkeypatch, registrations: FakeRegistrations) -> None:
    monkeypatch.setattr(tournament_join, "TournamentRegistration", SimpleNamespace(objects=registrations))


# --- joining ------------------------------------------------------------------------------------------------


def test_joining_registers_the_player_and_counts_a_participation(monkeypatch, stats):
    registrations = FakeRegistrations()
    use_registrations(monkeypatch, registrations)
    outcome = asyncio.run(join_tournament(PLAYER, make_tournament(max_participants=0), "legacy"))  # type: ignore[arg-type]
    assert outcome.ok and "Legacy" in outcome.message
    assert registrations.created is not None and not registrations.created.deleted
    stats.increment.assert_awaited_once_with(PLAYER, "tournament_participations")


def test_joining_after_registration_closed_is_refused(monkeypatch, stats):
    use_registrations(monkeypatch, FakeRegistrations())
    tournament = make_tournament(status="group_stage", max_participants=0)
    outcome = asyncio.run(join_tournament(PLAYER, tournament, "main"))  # type: ignore[arg-type]
    assert not outcome.ok and "closed" in outcome.message.lower()
    stats.increment.assert_not_awaited()


def test_joining_twice_is_refused_and_keeps_the_first_group(monkeypatch, stats):
    use_registrations(monkeypatch, FakeRegistrations(existing=FakeRegistration("legacy")))
    outcome = asyncio.run(join_tournament(PLAYER, make_tournament(max_participants=0), "main"))  # type: ignore[arg-type]
    assert not outcome.ok and "already in the **Legacy** group" in outcome.message
    stats.increment.assert_not_awaited()


def test_a_full_tournament_takes_the_late_registration_back(monkeypatch, stats):
    registrations = FakeRegistrations(total=9)
    use_registrations(monkeypatch, registrations)
    outcome = asyncio.run(join_tournament(PLAYER, make_tournament(max_participants=8), "main"))  # type: ignore[arg-type]
    assert not outcome.ok and "full" in outcome.message
    assert registrations.created is not None and registrations.created.deleted
    stats.increment.assert_not_awaited()


def test_the_last_free_slot_is_still_joinable(monkeypatch, stats):
    use_registrations(monkeypatch, FakeRegistrations(total=8))
    outcome = asyncio.run(join_tournament(PLAYER, make_tournament(max_participants=8), "main"))  # type: ignore[arg-type]
    assert outcome.ok


# --- leaving ------------------------------------------------------------------------------------------------


def test_leaving_takes_the_participation_back(monkeypatch, stats):
    use_registrations(monkeypatch, FakeRegistrations())
    outcome = asyncio.run(leave_tournament(PLAYER, make_tournament()))  # type: ignore[arg-type]
    assert outcome.ok
    stats.decrement.assert_awaited_once_with(PLAYER, "tournament_participations")


def test_leaving_when_not_registered_changes_nothing(monkeypatch, stats):
    registrations = FakeRegistrations()
    registrations.deleted_rows = 0
    use_registrations(monkeypatch, registrations)
    outcome = asyncio.run(leave_tournament(PLAYER, make_tournament()))  # type: ignore[arg-type]
    assert not outcome.ok and "aren't registered" in outcome.message
    stats.decrement.assert_not_awaited()


def test_leaving_after_the_start_is_refused(monkeypatch, stats):
    use_registrations(monkeypatch, FakeRegistrations())
    outcome = asyncio.run(leave_tournament(PLAYER, make_tournament(status="group_stage")))  # type: ignore[arg-type]
    assert not outcome.ok
    stats.decrement.assert_not_awaited()


# --- buttons ------------------------------------------------------------------------------------------------


def test_custom_ids_round_trip_through_the_template():
    for action in ("legacy", "main", "leave", "hub"):
        button = TournamentActionButton(321, action)
        custom_id = button.item.custom_id
        assert custom_id == f"fcdex:tournament:321:{action}"
        match = re.fullmatch(BUTTON_TEMPLATE, custom_id)
        assert match is not None
        rebuilt = asyncio.run(TournamentActionButton.from_custom_id(MagicMock(), button.item, match))
        assert (rebuilt.tournament_id, rebuilt.action) == (321, action)


@pytest.mark.parametrize(
    "custom_id", ["fcdex:tournament:x:legacy", "fcdex:tournament:5:other", "fcdex:tournament::main", "other:5:main"]
)
def test_the_template_ignores_foreign_custom_ids(custom_id):
    assert re.fullmatch(BUTTON_TEMPLATE, custom_id) is None


def test_the_buttons_are_registered_dynamic_items():
    assert TournamentActionButton.__discord_ui_compiled_template__.pattern == BUTTON_TEMPLATE


def fake_interaction(blacklisted: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=5),
        client=SimpleNamespace(blacklist_check=AsyncMock(return_value=not blacklisted)),
        response=SimpleNamespace(send_message=AsyncMock()),
    )


def test_blacklisted_players_cannot_use_the_buttons():
    interaction = fake_interaction(blacklisted=True)
    assert asyncio.run(TournamentActionButton(1, "main").interaction_check(interaction)) is False  # type: ignore[arg-type]
    assert asyncio.run(TournamentActionButton(1, "main").interaction_check(fake_interaction())) is True  # type: ignore[arg-type]


def install_tournament_lookup(monkeypatch, tournament, *, missing: bool = False) -> None:
    class DoesNotExist(Exception):
        pass

    async def aget(pk):
        if missing:
            raise DoesNotExist
        return tournament

    monkeypatch.setattr(
        tournament_join, "Tournament", SimpleNamespace(DoesNotExist=DoesNotExist, objects=SimpleNamespace(aget=aget))
    )

    async def aget_or_create(**kwargs):
        return PLAYER, False

    monkeypatch.setattr(
        tournament_join, "Player", SimpleNamespace(objects=SimpleNamespace(aget_or_create=aget_or_create))
    )


def test_pressing_join_answers_privately(monkeypatch, stats):
    tournament = make_tournament(pk=3, max_participants=0)
    install_tournament_lookup(monkeypatch, tournament)
    use_registrations(monkeypatch, FakeRegistrations())
    interaction = fake_interaction()
    asyncio.run(TournamentActionButton(3, "main").callback(interaction))  # type: ignore[arg-type]
    args, kwargs = interaction.response.send_message.await_args
    assert "Joined **Main** group" in args[0] and kwargs["ephemeral"] is True


def test_pressing_leave_answers_privately(monkeypatch, stats):
    install_tournament_lookup(monkeypatch, make_tournament(pk=3))
    use_registrations(monkeypatch, FakeRegistrations())
    interaction = fake_interaction()
    asyncio.run(TournamentActionButton(3, "leave").callback(interaction))  # type: ignore[arg-type]
    assert "You left the tournament" in interaction.response.send_message.await_args.args[0]


def test_pressing_a_button_for_a_deleted_tournament_explains(monkeypatch, stats):
    install_tournament_lookup(monkeypatch, None, missing=True)
    interaction = fake_interaction()
    asyncio.run(TournamentActionButton(3, "main").callback(interaction))  # type: ignore[arg-type]
    assert "no longer exists" in interaction.response.send_message.await_args.args[0]


def test_pressing_details_opens_the_hub_privately(monkeypatch, stats):
    install_tournament_lookup(monkeypatch, make_tournament(pk=3))
    from fcdex_3_1.fcdex_ext import tournament_player_views

    hub = object()
    build = AsyncMock(return_value=hub)
    monkeypatch.setattr(tournament_player_views, "build_tournament_player_menu", build)
    interaction = fake_interaction()
    asyncio.run(TournamentActionButton(3, "hub").callback(interaction))  # type: ignore[arg-type]
    build.assert_awaited_once_with(5, 3, mode="overview")
    assert interaction.response.send_message.await_args.kwargs == {"view": hub, "ephemeral": True}


# --- announcement -------------------------------------------------------------------------------------------


def announcement_tournament() -> SimpleNamespace:
    return make_tournament(
        pk=42,
        name="Spring Cup",
        description="Friendly cup",
        max_participants=16,
        semifinal_cutoff=9,
        betting_enabled=True,
        started_at=None,
        ended_at=None,
        get_status_display=lambda: "Registration",
    )


def test_the_announcement_never_times_out_and_carries_four_persistent_buttons():
    async def run():
        layout = await build_announcement_layout(announcement_tournament(), 999)  # type: ignore[arg-type]
        assert layout.timeout is None
        found = [item for item in layout.walk_children() if isinstance(item, TournamentActionButton)]
        assert [b.action for b in found] == ["legacy", "main", "leave", "hub"]
        ids = [b.item.custom_id for b in found]
        assert len(set(ids)) == 4 and all(len(i) <= 100 and i.startswith("fcdex:tournament:42:") for i in ids)
        text = "\n".join(i.content for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay))
        assert "Spring Cup" in text and "<@999>" in text and "Join with one tap" in text
        layout.to_components()

    asyncio.run(run())
