from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import discord

_bd_models = ModuleType("bd_models")
_bd_models_models = ModuleType("bd_models.models")
_bd_models_models.Player = object
_bd_models.models = _bd_models_models
sys.modules.setdefault("bd_models", _bd_models)
sys.modules.setdefault("bd_models.models", _bd_models_models)

from fcdex_3_1.fcdex_ext.broadcast_logic import (  # noqa: E402
    DISCORD_MESSAGE_MAX,
    DMSendOutcome,
    classify_dm_error,
    format_announce_message,
    pick_guild_announce_channel,
    preview_broadcast_message,
    validate_broadcast_message,
)


def test_validate_broadcast_message_empty():
    ok, msg = validate_broadcast_message("   ")
    assert ok is False
    assert "empty" in msg.lower()


def test_validate_broadcast_message_too_long():
    ok, msg = validate_broadcast_message("x" * (DISCORD_MESSAGE_MAX + 1))
    assert ok is False
    assert "too long" in msg.lower()


def test_validate_broadcast_message_ok():
    ok, msg = validate_broadcast_message("  Hello FCDex  ")
    assert ok is True
    assert msg == "Hello FCDex"


def test_preview_broadcast_message_truncates():
    long = "a" * 600
    preview = preview_broadcast_message(long, max_len=100)
    assert len(preview) == 100
    assert preview.endswith("…")


def _channel(cid: int, *, news: bool = False, position: int = 0, can_send: bool = True):
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = cid
    ch.is_news.return_value = news
    ch.position = position
    ch.permissions_for.return_value.send_messages = can_send
    return ch


def test_pick_guild_prefers_raid_channel():
    guild = MagicMock(spec=discord.Guild)
    raid = _channel(99)
    other = _channel(1, position=0)
    guild.get_channel.return_value = raid
    guild.system_channel = other
    guild.text_channels = [other]
    member = MagicMock()
    picked = pick_guild_announce_channel(guild, member, raid_channel_id=99)
    assert picked is raid


def test_pick_guild_system_channel_when_no_raid():
    guild = MagicMock(spec=discord.Guild)
    system = _channel(2)
    guild.get_channel.return_value = None
    guild.system_channel = system
    guild.text_channels = [_channel(3, position=1)]
    member = MagicMock()
    picked = pick_guild_announce_channel(guild, member, raid_channel_id=None)
    assert picked is system


def test_format_announce_message_title_and_body():
    text = format_announce_message(title="Update", body="New packs live.")
    assert text.startswith("# Update")
    assert "New packs live." in text


def test_classify_dm_closed_forbidden():
    exc = MagicMock(spec=discord.Forbidden)
    exc.code = 50007
    assert classify_dm_error(exc) == DMSendOutcome.DM_CLOSED


def test_pick_guild_prefers_spawn_channel():
    guild = MagicMock(spec=discord.Guild)
    spawn = _channel(50, position=5)
    system = _channel(2)
    guild.get_channel.return_value = spawn
    guild.system_channel = system
    guild.text_channels = [system]
    member = MagicMock()
    picked = pick_guild_announce_channel(guild, member, preferred_channel_id=50)
    assert picked is spawn


def test_pick_guild_first_text_channel_fallback():
    guild = MagicMock(spec=discord.Guild)
    guild.get_channel.return_value = None
    guild.system_channel = None
    low = _channel(10, position=2)
    high = _channel(11, position=0)
    guild.text_channels = [low, high]
    member = MagicMock()
    picked = pick_guild_announce_channel(guild, member)
    assert picked is high
