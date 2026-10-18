from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from fcdex_3_1.fcdex_ext import compat, twin_spawn
from fcdex_3_1.fcdex_ext.twin_spawn import TwinSpawnView, spawn_twin


def ball(pk: int, name: str, rarity: float = 10.0) -> SimpleNamespace:
    return SimpleNamespace(
        pk=pk,
        country=name,
        rarity=rarity,
        enabled=True,
        attack=100,
        health=100,
        wild_card=SimpleNamespace(name=f"wild{pk}.png", path=f"/tmp/wild{pk}.png"),
    )


class FakeEngine:
    """Stands in for the host BallSpawnView used as a catch engine."""

    def __init__(self, model: SimpleNamespace):
        self.model = model
        self.caught = False
        self.message = None
        self.algo = None
        self.catches: list[int] = []
        self.fail_with: Exception | None = None

    def is_name_valid(self, text: str) -> bool:
        return text.strip().lower() == self.model.country.lower()

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


def install_player(monkeypatch) -> None:
    async def aget_or_create(**kwargs):
        await asyncio.sleep(0)
        return FakePlayer(), False

    monkeypatch.setattr(twin_spawn, "Player", SimpleNamespace(objects=SimpleNamespace(aget_or_create=aget_or_create)))


def interaction(user_id: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, mention=f"<@{user_id}>"),
        client=SimpleNamespace(hooks=None),
        guild=SimpleNamespace(id=9),
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), send_modal=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock(), edit_message=AsyncMock()),
    )


def make_view() -> tuple[TwinSpawnView, FakeEngine, FakeEngine]:
    left, right = FakeEngine(ball(1, "Real Madrid")), FakeEngine(ball(2, "Barcelona"))
    view = TwinSpawnView(SimpleNamespace(), (left, right), ("a.png", "b.png"))  # type: ignore[arg-type]
    view.message = SimpleNamespace(id=77, edit=AsyncMock())  # type: ignore[assignment]
    return view, left, right


def buttons(view: TwinSpawnView) -> list[discord.ui.Button]:
    return [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]


def test_layout_shows_both_clubballs_and_two_open_buttons(monkeypatch):
    async def run():
        view, _, _ = make_view()
        galleries = [item for item in view.walk_children() if isinstance(item, discord.ui.MediaGallery)]
        assert len(galleries) == 1
        assert [item.media.url for item in galleries[0].items] == ["attachment://a.png", "attachment://b.png"]
        found = buttons(view)
        assert [b.label for b in found] == ["Catch left", "Catch right"]
        assert not any(b.disabled for b in found)
        assert view.total_children_count <= 40
        view.to_components()  # serializes without error

    asyncio.run(run())


def test_wrong_name_keeps_the_spawn_open(monkeypatch):
    install_player(monkeypatch)

    async def run():
        view, left, right = make_view()
        ctx = interaction()
        await view.handle_guess(ctx, 0, "Barcelona")  # that is the right-hand clubball's name
        assert not view.closed
        assert left.catches == [] and right.catches == []
        ctx.followup.send.assert_awaited_once()
        assert ctx.followup.send.await_args.kwargs["ephemeral"] is False

    asyncio.run(run())


def test_correct_name_catches_the_chosen_side_and_closes_the_spawn(monkeypatch):
    install_player(monkeypatch)

    async def run():
        view, left, right = make_view()
        ctx = interaction()
        await view.handle_guess(ctx, 1, " barcelona ")
        assert view.caught_slot == 1
        assert right.catches == [5] and left.catches == []
        assert ctx.followup.send.await_args.args[0] == "<@5> caught Barcelona"
        ctx.followup.edit_message.assert_awaited_once()
        assert ctx.followup.edit_message.await_args.args[0] == 77
        states = {b.label: b.disabled for b in buttons(view)}
        assert states == {"Got away": True, "Caught!": True}

    asyncio.run(run())


def test_only_one_side_can_ever_be_caught(monkeypatch):
    install_player(monkeypatch)

    async def run():
        view, left, right = make_view()
        await view.handle_guess(interaction(5), 0, "real madrid")
        late = interaction(6)
        await view.handle_guess(late, 1, "barcelona")
        assert left.catches == [5] and right.catches == []
        assert late.followup.send.await_args.kwargs["ephemeral"] is True

    asyncio.run(run())


def test_two_simultaneous_correct_guesses_cannot_both_win(monkeypatch):
    install_player(monkeypatch)

    async def run():
        view, left, right = make_view()
        await asyncio.gather(
            view.handle_guess(interaction(5), 0, "real madrid"), view.handle_guess(interaction(6), 1, "barcelona")
        )
        assert len(left.catches) + len(right.catches) == 1

    asyncio.run(run())


def test_a_failed_catch_reopens_the_spawn(monkeypatch):
    install_player(monkeypatch)

    async def run():
        view, left, _ = make_view()
        left.fail_with = RuntimeError("database down")
        with pytest.raises(RuntimeError):
            await view.handle_guess(interaction(), 0, "real madrid")
        assert not view.closed
        assert left.caught is False
        left.fail_with = None
        await view.handle_guess(interaction(), 0, "real madrid")
        assert view.caught_slot == 0

    asyncio.run(run())


def test_a_pre_catch_hook_can_veto_the_catch(monkeypatch):
    install_player(monkeypatch)

    async def veto(bot, name, **fields):
        return SimpleNamespace(cancelled=True, reason="Slow down!") if name == "PreCatchContext" else None

    monkeypatch.setattr(compat, "run_hook", veto)

    async def run():
        view, left, _ = make_view()
        ctx = interaction()
        await view.handle_guess(ctx, 0, "real madrid")
        assert left.catches == [] and not view.closed
        assert ctx.followup.send.await_args.args[0] == "Slow down!"
        assert ctx.followup.send.await_args.kwargs["ephemeral"] is True

    asyncio.run(run())


def test_a_catch_message_hook_can_rewrite_the_reply(monkeypatch):
    install_player(monkeypatch)

    async def rewrite(bot, name, **fields):
        if name == "CatchMessageContext":
            return SimpleNamespace(content=fields["content"] + " (boosted)")
        return None

    monkeypatch.setattr(compat, "run_hook", rewrite)

    async def run():
        view, _, _ = make_view()
        ctx = interaction()
        await view.handle_guess(ctx, 0, "real madrid")
        assert ctx.followup.send.await_args.args[0] == "<@5> caught Real Madrid (boosted)"

    asyncio.run(run())


def test_a_failing_message_edit_does_not_undo_the_catch(monkeypatch):
    install_player(monkeypatch)

    async def run():
        view, left, _ = make_view()
        ctx = interaction()
        ctx.followup.edit_message = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "boom"))
        await view.handle_guess(ctx, 0, "real madrid")
        assert left.catches == [5] and view.caught

    asyncio.run(run())


def test_buttons_open_the_prompt_for_their_side(monkeypatch):
    async def run():
        view, _, _ = make_view()
        ctx = interaction()
        await view.open_prompt(ctx, 1)
        modal = ctx.response.send_modal.await_args.args[0]
        assert modal.slot == 1
        assert "right" in modal.title

    asyncio.run(run())


def test_buttons_refuse_once_the_spawn_is_closed(monkeypatch):
    async def run():
        view, _, _ = make_view()
        view.expired = True
        ctx = interaction()
        await view.open_prompt(ctx, 0)
        ctx.response.send_modal.assert_not_awaited()
        assert ctx.response.send_message.await_args.kwargs["ephemeral"] is True

    asyncio.run(run())


def test_timeout_closes_an_unclaimed_spawn(monkeypatch):
    async def run():
        view, _, _ = make_view()
        await view.on_timeout()
        assert view.expired
        view.message.edit.assert_awaited_once()
        assert all(b.disabled for b in buttons(view))

    asyncio.run(run())


def test_timeout_leaves_a_caught_spawn_alone(monkeypatch):
    install_player(monkeypatch)

    async def run():
        view, _, _ = make_view()
        await view.handle_guess(interaction(), 0, "real madrid")
        view.message.edit.reset_mock()
        await view.on_timeout()
        assert not view.expired
        view.message.edit.assert_not_awaited()

    asyncio.run(run())


# --- posting ------------------------------------------------------------------------------------------------


def channel() -> SimpleNamespace:
    return SimpleNamespace(name="spawns")


def patch_posting(monkeypatch, *, balls, posted: bool = True, can_post: bool = True):
    sent = SimpleNamespace(id=1)
    post = AsyncMock(return_value=sent if posted else None)
    dispatched: list[FakeEngine] = []
    monkeypatch.setattr(twin_spawn, "fetch_all_balls", AsyncMock(return_value=balls))
    monkeypatch.setattr(twin_spawn, "can_post_spawn", lambda ch: can_post)
    monkeypatch.setattr(twin_spawn, "post_spawn", post)
    monkeypatch.setattr(twin_spawn, "new_engine", lambda bot, model, *, algo: _tagged_engine(model, algo))
    monkeypatch.setattr(compat, "dispatch_ball_spawned", lambda bot, view, ch: dispatched.append(view))
    return sent, post, dispatched


def _tagged_engine(model, algo) -> FakeEngine:
    engine = FakeEngine(model)
    engine.algo = algo
    return engine


def test_spawn_twin_posts_two_different_clubballs(monkeypatch):
    sent, post, dispatched = patch_posting(monkeypatch, balls=[ball(1, "A"), ball(2, "B"), ball(3, "C")])
    assert asyncio.run(spawn_twin(SimpleNamespace(), channel(), algo="algo")) is True  # type: ignore[arg-type]
    view, shown_balls, names = post.await_args.args[1:]
    assert len({b.pk for b in shown_balls}) == 2
    assert len(set(names)) == 2 and all(n.startswith("nt_") for n in names)
    assert view.message is sent
    assert [e.message for e in view.engines] == [sent, sent]
    assert {e.algo for e in view.engines} == {"algo:twin"}
    assert dispatched == list(view.engines)


def test_spawn_twin_gives_up_cleanly(monkeypatch):
    _, post, _ = patch_posting(monkeypatch, balls=[ball(1, "A")])
    assert asyncio.run(spawn_twin(SimpleNamespace(), channel())) is False  # type: ignore[arg-type]
    post.assert_not_awaited()

    _, post, _ = patch_posting(monkeypatch, balls=[ball(1, "A"), ball(2, "B")], can_post=False)
    assert asyncio.run(spawn_twin(SimpleNamespace(), channel())) is False  # type: ignore[arg-type]
    post.assert_not_awaited()

    _, post, dispatched = patch_posting(monkeypatch, balls=[ball(1, "A"), ball(2, "B")], posted=False)
    assert asyncio.run(spawn_twin(SimpleNamespace(), channel())) is False  # type: ignore[arg-type]
    assert dispatched == []
