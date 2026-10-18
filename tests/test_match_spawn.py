from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from fcdex_3_1.fcdex_ext import compat, match_spawn
from fcdex_3_1.fcdex_ext.match_logic import MatchRoll
from fcdex_3_1.fcdex_ext.match_spawn import MatchCard, MatchPickerView, MatchSpawnView, spawn_match, strongest_cards


def ball(pk: int, name: str, rarity: float) -> SimpleNamespace:
    return SimpleNamespace(
        pk=pk,
        country=name,
        rarity=rarity,
        enabled=True,
        attack=100,
        health=100,
        wild_card=SimpleNamespace(name=f"wild{pk}.png", path=f"/tmp/wild{pk}.png"),
    )


ORIGINAL = ball(1, "Crewe Alexandra", 50.0)
RARER = ball(2, "Real Madrid", 5.0)
DEX = [ORIGINAL, RARER, ball(3, "Barcelona", 80.0)]


class FakeEngine:
    def __init__(self, model: SimpleNamespace):
        self.model = model
        self.message = None
        self.algo = None
        self.caught = False
        self.catches: list[int] = []
        self.fail_with: Exception | None = None

    async def catch_ball(self, user, *, player, guild):
        self.caught = True
        await asyncio.sleep(0)
        if self.fail_with is not None:
            raise self.fail_with
        self.catches.append(user.id)
        return SimpleNamespace(pk=0xAB), True

    def get_catch_message(self, ball, new_ball, mention) -> str:
        return f"{mention} caught {self.model.country}"


class FakePlayer:
    can_be_mentioned = True


def interaction(user_id: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, mention=f"<@{user_id}>"),
        guild=SimpleNamespace(id=9),
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def panel_text(ctx: SimpleNamespace) -> str:
    """All text shown by the last panel edited onto the interaction."""
    view = ctx.edit_original_response.await_args.kwargs["view"]
    return "\n".join(item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay))


@pytest.fixture
def world(monkeypatch):
    state = SimpleNamespace(rewards=[], card=MatchCard(100, "Messi", 150, 120), roll=MatchRoll(500, 100))

    async def aget_or_create(**kwargs):
        await asyncio.sleep(0)
        return FakePlayer(), False

    async def load_card(player, instance_id):
        await asyncio.sleep(0)
        return state.card

    def new_engine(bot, model, *, algo):
        engine = FakeEngine(model)
        engine.algo = algo
        state.rewards.append(engine)
        return engine

    monkeypatch.setattr(match_spawn, "Player", SimpleNamespace(objects=SimpleNamespace(aget_or_create=aget_or_create)))
    monkeypatch.setattr(match_spawn, "load_card", load_card)
    monkeypatch.setattr(match_spawn, "roll_match", lambda user_power, target_power: state.roll)
    monkeypatch.setattr(match_spawn, "fetch_all_balls", AsyncMock(return_value=DEX))
    monkeypatch.setattr(match_spawn, "new_engine", new_engine)
    return state


def make_view() -> MatchSpawnView:
    view = MatchSpawnView(
        SimpleNamespace(),  # type: ignore[arg-type]
        FakeEngine(ORIGINAL),  # type: ignore[arg-type]
        "spawn.png",
        target_power=300,
        algo="algo:match",
    )
    view.message = SimpleNamespace(id=1, edit=AsyncMock(), channel=SimpleNamespace(send=AsyncMock()))  # type: ignore[assignment]
    return view


def play_button(view: MatchSpawnView) -> discord.ui.Button:
    return next(item for item in view.walk_children() if isinstance(item, discord.ui.Button))


# --- layout -------------------------------------------------------------------------------------------------


def test_spawn_message_shows_the_clubball_and_an_open_play_button():
    async def run():
        view = make_view()
        galleries = [item for item in view.walk_children() if isinstance(item, discord.ui.MediaGallery)]
        assert [item.media.url for item in galleries[0].items] == ["attachment://spawn.png"]
        button = play_button(view)
        assert button.label == "Play match" and not button.disabled
        view.to_components()

    asyncio.run(run())


# --- choosing a clubball ------------------------------------------------------------------------------------


class FakeQuerySet:
    def __init__(self, rows):
        self.rows = rows
        self.requested = None

    def filter(self, **kwargs):
        return self

    def values_list(self, *fields):
        self.requested = fields
        return self

    def __aiter__(self):
        async def iterate():
            for row in self.rows:
                yield row

        return iterate()

    async def afirst(self):
        return self.rows[0] if self.rows else None


def test_strongest_cards_come_back_best_first_with_stat_bonuses(monkeypatch):
    rows = [
        (1, 0, 0, 100, 100, "Plain"),  # power 300
        (2, 50, 0, 100, 100, "Boosted attack"),  # attack 150 -> 400
        (3, -50, -50, 100, 100, "Nerfed"),  # attack 50, health 50 -> 150
    ]
    queryset = FakeQuerySet(rows)
    monkeypatch.setattr(match_spawn, "BallInstance", SimpleNamespace(objects=queryset))
    cards = asyncio.run(strongest_cards(SimpleNamespace()))  # type: ignore[arg-type]
    assert [card.country for card in cards] == ["Boosted attack", "Plain", "Nerfed"]
    assert [card.power for card in cards] == [400, 300, 150]
    assert queryset.requested == ("pk", "attack_bonus", "health_bonus", "ball__attack", "ball__health", "ball__country")


def test_strongest_cards_never_exceed_what_a_select_menu_holds(monkeypatch):
    rows = [(i, 0, 0, i, i, f"Club {i}") for i in range(1, 80)]
    monkeypatch.setattr(match_spawn, "BallInstance", SimpleNamespace(objects=FakeQuerySet(rows)))
    cards = asyncio.run(strongest_cards(SimpleNamespace()))  # type: ignore[arg-type]
    assert len(cards) == 25
    assert cards[0].country == "Club 79"


def test_open_picker_lists_the_players_cards(monkeypatch, world):
    cards = [MatchCard(10 + i, f"Club {i}", 100 + i, 100) for i in range(25)]
    monkeypatch.setattr(match_spawn, "strongest_cards", AsyncMock(return_value=cards))

    async def run():
        view = make_view()
        ctx = interaction()
        await view.open_picker(ctx)
        picker = ctx.response.send_message.await_args.kwargs["view"]
        assert isinstance(picker, MatchPickerView)
        assert ctx.response.send_message.await_args.kwargs["ephemeral"] is True
        selects = [item for item in picker.walk_children() if isinstance(item, discord.ui.Select)]
        assert len(selects[0].options) == 25
        assert picker.discord_id == 5  # only the player who opened it can use it
        picker.to_components()

    asyncio.run(run())


def test_open_picker_explains_when_there_is_nothing_to_play_with(monkeypatch, world):
    monkeypatch.setattr(match_spawn, "strongest_cards", AsyncMock(return_value=[]))

    async def run():
        view = make_view()
        ctx = interaction()
        await view.open_picker(ctx)
        assert "don't own" in ctx.response.send_message.await_args.args[0]

    asyncio.run(run())


def test_open_picker_refuses_second_tries_and_finished_matches(world):
    async def run():
        view = make_view()
        view.attempted.add(5)
        ctx = interaction(5)
        await view.open_picker(ctx)
        assert "already played" in ctx.response.send_message.await_args.args[0]

        view.expired = True
        ctx = interaction(6)
        await view.open_picker(ctx)
        assert "already over" in ctx.response.send_message.await_args.args[0]

    asyncio.run(run())


# --- playing ------------------------------------------------------------------------------------------------


def test_winning_pays_a_rarer_clubball_and_closes_the_match(world):
    async def run():
        view = make_view()
        ctx = interaction()
        await view.play(ctx, 100)
        assert [r.model.country for r in world.rewards] == ["Real Madrid"]  # the only clubball rarer than the original
        assert world.rewards[0].catches == [5]
        assert world.rewards[0].message is view.message
        assert world.rewards[0].algo == "algo:match"
        assert view.winner_id == 5 and view.closed
        assert "Match won" in panel_text(ctx)
        view.message.edit.assert_awaited_once()
        announcement = view.message.channel.send.await_args.args[0]
        assert "<@5>" in announcement and "Crewe Alexandra" in announcement
        button = play_button(view)
        assert button.disabled and button.label == "Won!"

    asyncio.run(run())


def test_losing_uses_up_the_try_but_leaves_the_prize_open(world):
    world.roll = MatchRoll(100, 500)

    async def run():
        view = make_view()
        ctx = interaction()
        await view.play(ctx, 100)
        assert "Match lost" in panel_text(ctx)
        assert not view.closed and world.rewards == []
        again = interaction()
        await view.play(again, 100)
        assert "already played" in panel_text(again)

    asyncio.run(run())


def test_nobody_can_play_after_the_prize_is_taken(world):
    async def run():
        view = make_view()
        await view.play(interaction(5), 100)
        late = interaction(6)
        await view.play(late, 100)
        assert "already over" in panel_text(late)
        assert len(world.rewards) == 1

    asyncio.run(run())


def test_two_simultaneous_winners_cannot_both_be_paid(world):
    async def run():
        view = make_view()
        first, second = interaction(5), interaction(6)
        await asyncio.gather(view.play(first, 100), view.play(second, 100))
        paid = [r for r in world.rewards if r.catches]
        assert len(paid) == 1
        texts = {panel_text(first), panel_text(second)}
        assert any("Match won" in t for t in texts)
        assert any("Too slow" in t for t in texts)

    asyncio.run(run())


def test_a_double_click_cannot_play_twice(world):
    async def run():
        view = make_view()
        world.roll = MatchRoll(100, 500)
        first, second = interaction(5), interaction(5)
        await asyncio.gather(view.play(first, 100), view.play(second, 100))
        outcomes = [panel_text(first), panel_text(second)]
        assert sum("Match lost" in t for t in outcomes) == 1
        assert sum("already played" in t for t in outcomes) == 1

    asyncio.run(run())


def test_a_clubball_that_is_not_yours_does_not_burn_the_try(world):
    world.card = None  # type: ignore[assignment]

    async def run():
        view = make_view()
        ctx = interaction()
        await view.play(ctx, 999)
        assert "isn't yours" in panel_text(ctx)
        assert 5 not in view.attempted

    asyncio.run(run())


def test_a_failed_payout_releases_the_prize_and_the_try(world, monkeypatch):
    broken = FakeEngine(RARER)
    broken.fail_with = RuntimeError("database down")
    monkeypatch.setattr(match_spawn, "new_engine", lambda bot, model, *, algo: broken)

    async def run():
        view = make_view()
        with pytest.raises(RuntimeError):
            await view.play(interaction(), 100)
        assert view.winner_id is None and not view.closed
        assert 5 not in view.attempted
        broken.fail_with = None
        ctx = interaction()
        await view.play(ctx, 100)
        assert view.winner_id == 5

    asyncio.run(run())


def test_a_pre_catch_hook_can_veto_the_prize(world, monkeypatch):
    async def veto(bot, name, **fields):
        return SimpleNamespace(cancelled=True, reason="Not today.") if name == "PreCatchContext" else None

    monkeypatch.setattr(compat, "run_hook", veto)

    async def run():
        view = make_view()
        ctx = interaction()
        await view.play(ctx, 100)
        assert "Not today." in panel_text(ctx)
        assert view.winner_id is None and 5 not in view.attempted
        assert all(not r.catches for r in world.rewards)

    asyncio.run(run())


def test_a_failed_announcement_does_not_take_the_prize_back(world):
    async def run():
        view = make_view()
        view.message.edit = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500, reason="boom"), "boom"))
        view.message.channel.send = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(status=500, reason="boom"), "boom")
        )
        ctx = interaction()
        await view.play(ctx, 100)
        assert world.rewards[0].catches == [5]
        assert "Match won" in panel_text(ctx)

    asyncio.run(run())


def test_the_picker_hands_the_chosen_card_to_the_match(world):
    async def run():
        view = make_view()
        view.play = AsyncMock()  # type: ignore[method-assign]
        picker = MatchPickerView(view, 5, [MatchCard(10, "A", 1, 1), MatchCard(11, "B", 2, 2)])
        ctx = interaction()
        await picker.play(ctx, 11)
        view.play.assert_awaited_once_with(ctx, 11)
        assert picker.is_finished()

    asyncio.run(run())


def test_timeout_closes_an_unwon_match(world):
    async def run():
        view = make_view()
        await view.on_timeout()
        assert view.expired and view.closed
        view.message.edit.assert_awaited_once()
        button = play_button(view)
        assert button.disabled and button.label == "Over"

    asyncio.run(run())


def test_timeout_does_not_touch_a_won_match(world):
    async def run():
        view = make_view()
        await view.play(interaction(), 100)
        view.message.edit.reset_mock()
        await view.on_timeout()
        assert not view.expired
        view.message.edit.assert_not_awaited()

    asyncio.run(run())


# --- posting ------------------------------------------------------------------------------------------------


def patch_posting(monkeypatch, *, balls=None, posted: bool = True, can_post: bool = True):
    sent = SimpleNamespace(id=1)
    post = AsyncMock(return_value=sent if posted else None)
    dispatched: list = []
    monkeypatch.setattr(match_spawn, "fetch_all_balls", AsyncMock(return_value=DEX if balls is None else balls))
    monkeypatch.setattr(match_spawn, "can_post_spawn", lambda channel: can_post)
    monkeypatch.setattr(match_spawn, "post_spawn", post)
    monkeypatch.setattr(match_spawn, "new_engine", lambda bot, model, *, algo: _engine(model, algo))
    monkeypatch.setattr(match_spawn, "get_spawn_config", AsyncMock(return_value=SimpleNamespace(match_difficulty=150)))
    monkeypatch.setattr(compat, "dispatch_ball_spawned", lambda bot, view, channel: dispatched.append(view))
    return sent, post, dispatched


def _engine(model, algo) -> FakeEngine:
    engine = FakeEngine(model)
    engine.algo = algo
    return engine


def test_spawn_match_posts_the_original_with_a_scaled_opponent(monkeypatch):
    sent, post, dispatched = patch_posting(monkeypatch)
    assert asyncio.run(spawn_match(SimpleNamespace(), SimpleNamespace(), algo="algo")) is True  # type: ignore[arg-type]
    view, shown, names = post.await_args.args[1:]
    original = shown[0]
    assert view.target_power == int((original.attack * 2 + original.health) * 150 / 100)
    assert view.algo == "algo:match" and view.message is sent
    assert view.engine.message is sent
    assert dispatched == [view.engine]
    assert names[0].startswith("nt_")


def test_spawn_match_gives_up_cleanly(monkeypatch):
    _, post, _ = patch_posting(monkeypatch, balls=[])
    assert asyncio.run(spawn_match(SimpleNamespace(), SimpleNamespace())) is False  # type: ignore[arg-type]
    post.assert_not_awaited()

    _, post, _ = patch_posting(monkeypatch, can_post=False)
    assert asyncio.run(spawn_match(SimpleNamespace(), SimpleNamespace())) is False  # type: ignore[arg-type]
    post.assert_not_awaited()

    _, post, dispatched = patch_posting(monkeypatch, posted=False)
    assert asyncio.run(spawn_match(SimpleNamespace(), SimpleNamespace())) is False  # type: ignore[arg-type]
    assert dispatched == []
