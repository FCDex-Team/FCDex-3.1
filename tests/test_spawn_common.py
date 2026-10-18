from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from fcdex_3_1.fcdex_ext import spawn_common
from fcdex_3_1.fcdex_ext.spawn_common import (
    attachment_name,
    can_post_spawn,
    collectible_names,
    post_spawn,
    prompt_message,
)


def ball(name: str, image) -> SimpleNamespace:
    return SimpleNamespace(country=name, wild_card=SimpleNamespace(name=image.name, path=str(image)))


@pytest.fixture
def images(tmp_path):
    paths = []
    for index in range(2):
        path = tmp_path / f"wild{index}.png"
        path.write_bytes(b"\x89PNG fake")
        paths.append(path)
    return paths


def test_attachment_names_hide_the_clubball_and_keep_the_extension(images):
    madrid = ball("Real Madrid", images[0])
    names = {attachment_name(madrid) for _ in range(50)}
    assert len(names) == 50
    for name in names:
        assert name.startswith("nt_") and name.endswith(".png")
        assert "madrid" not in name.lower()
        assert len(name) == len("nt_") + 15 + len(".png")


def test_posting_needs_send_and_attach_permissions():
    def channel(**perms):
        return SimpleNamespace(guild=SimpleNamespace(me=object()), permissions_for=lambda me: SimpleNamespace(**perms))

    assert can_post_spawn(channel(send_messages=True, attach_files=True))
    assert not can_post_spawn(channel(send_messages=True, attach_files=False))
    assert not can_post_spawn(channel(send_messages=False, attach_files=True))


def test_posting_uploads_one_file_per_clubball_and_closes_them(images):
    sent = SimpleNamespace(id=1)
    uploaded: list = []

    async def send(**kwargs):
        uploaded.extend(kwargs["files"])
        return sent

    channel = SimpleNamespace(send=send)
    balls = [ball("A", images[0]), ball("B", images[1])]
    result = asyncio.run(post_spawn(channel, object(), balls, ["x.png", "y.png"]))  # type: ignore[arg-type]
    assert result is sent
    assert [f.filename for f in uploaded] == ["x.png", "y.png"]
    assert all(f.fp.closed for f in uploaded)


@pytest.mark.parametrize(
    "error",
    [
        discord.Forbidden(MagicMock(status=403, reason="no"), "missing access"),
        discord.HTTPException(MagicMock(status=500, reason="boom"), "boom"),
    ],
)
def test_posting_failures_are_reported_as_none(images, error):
    channel = SimpleNamespace(send=AsyncMock(side_effect=error))
    assert asyncio.run(post_spawn(channel, object(), [ball("A", images[0])], ["x.png"])) is None  # type: ignore[arg-type]


def test_a_missing_image_aborts_and_releases_the_files_already_opened(images, tmp_path):
    channel = SimpleNamespace(send=AsyncMock())
    balls = [ball("A", images[0]), ball("B", tmp_path / "gone.png")]
    assert asyncio.run(post_spawn(channel, object(), balls, ["x.png", "y.png"])) is None  # type: ignore[arg-type]
    channel.send.assert_not_awaited()


def test_prompt_messages_come_from_the_host_settings():
    text = prompt_message("SLOW", mention="<@1>", model=object(), bot=object(), fallback="fallback")  # type: ignore[arg-type]
    assert text == "[slow] <@1>"


def test_prompt_messages_fall_back_when_the_host_cannot_provide_them():
    unknown = prompt_message("NOPE", mention="<@1>", model=object(), bot=object(), fallback="fallback")  # type: ignore[arg-type]
    assert unknown == "fallback"


def test_prompt_messages_fall_back_when_formatting_fails(monkeypatch):
    import settings.models as host

    def broken(**kwargs):
        raise KeyError("missing placeholder")

    monkeypatch.setattr(host.settings, "get_formatted_message", broken)
    text = prompt_message("SLOW", mention="<@1>", model=object(), bot=object(), fallback="fallback")  # type: ignore[arg-type]
    assert text == "fallback"


def test_collectible_names_come_from_the_host_settings():
    assert collectible_names() == ("clubball", "clubballs")
    assert spawn_common.ACCENT_TWIN != spawn_common.ACCENT_MATCH
