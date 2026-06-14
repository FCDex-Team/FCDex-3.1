from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum

import discord

from bd_models.models import Player
from fcdex_3_1.fcdex_ext.leaderboard_logic import EXCLUDE_IDS

log = logging.getLogger("fcdex_3_1.broadcast")

DISCORD_MESSAGE_MAX = 2000
DISCORD_DM_CLOSED_CODE = 50007
DM_BATCH_SIZE = 5
DM_BATCH_DELAY_SECONDS = 1.0
DM_PROGRESS_EVERY = 25
SERVER_GUILD_DELAY_SECONDS = 0.75
SERVER_PROGRESS_EVERY = 10

TOS_WARNING = (
    "-# Mass DMs are sensitive — only send real updates players opted into. "
    "Discord may rate-limit or restrict abusive broadcasts."
)


class DMSendOutcome(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    DM_CLOSED = "dm_closed"


@dataclass(frozen=True, slots=True)
class BroadcastTally:
    sent: int = 0
    failed: int = 0
    dm_closed: int = 0

    def merge(self, outcome: DMSendOutcome) -> BroadcastTally:
        if outcome == DMSendOutcome.SENT:
            return BroadcastTally(self.sent + 1, self.failed, self.dm_closed)
        if outcome == DMSendOutcome.DM_CLOSED:
            return BroadcastTally(self.sent, self.failed, self.dm_closed + 1)
        return BroadcastTally(self.sent, self.failed + 1, self.dm_closed)

    def format_dm_summary(self, *, total: int) -> str:
        return (
            f"**DM broadcast complete**\n"
            f"- Sent: **{self.sent:,}**\n"
            f"- DMs closed / blocked: **{self.dm_closed:,}**\n"
            f"- Other failures: **{self.failed:,}**\n"
            f"- Total targeted: **{total:,}**"
        )

    def format_server_summary(self, *, guilds: int, skipped: int) -> str:
        return (
            f"**Server broadcast complete**\n"
            f"- Posted: **{self.sent:,}**\n"
            f"- Skipped (no channel / permission): **{skipped:,}**\n"
            f"- Failed: **{self.failed:,}**\n"
            f"- Guilds: **{guilds:,}**"
        )


def format_announce_message(*, title: str, body: str) -> str:
    title = title.strip()
    body = body.strip()
    combined = f"# {title}\n\n{body}" if title and body else (title or body)
    ok, cleaned = validate_broadcast_message(combined)
    return cleaned if ok else combined[:DISCORD_MESSAGE_MAX]


def validate_broadcast_message(message: str) -> tuple[bool, str]:
    """Return (ok, cleaned message or error text)."""
    text = message.strip()
    if not text:
        return False, "Message cannot be empty."
    if len(text) > DISCORD_MESSAGE_MAX:
        return False, f"Message is too long ({len(text)} characters). Maximum is {DISCORD_MESSAGE_MAX}."
    return True, text


def preview_broadcast_message(message: str, *, max_len: int = 500) -> str:
    if len(message) <= max_len:
        return message
    return message[: max_len - 1] + "…"


def _recipient_queryset():
    qs = Player.objects.filter(balls__deleted=False).distinct()
    if EXCLUDE_IDS:
        qs = qs.exclude(discord_id__in=EXCLUDE_IDS)
    return qs


async def count_dm_recipients() -> int:
    return await _recipient_queryset().acount()


async def iter_dm_recipient_ids() -> AsyncIterator[int]:
    qs = _recipient_queryset().values_list("discord_id", flat=True).order_by("discord_id")
    async for discord_id in qs.aiterator(chunk_size=500):
        yield int(discord_id)


async def collect_guild_config_channels() -> dict[int, int]:
    try:
        from bd_models.models import GuildConfig
    except ImportError:
        return {}
    out: dict[int, int] = {}
    async for config in GuildConfig.objects.filter(enabled=True).only("guild_id", "spawn_channel"):
        if config.spawn_channel:
            out[int(config.guild_id)] = int(config.spawn_channel)
    return out


def _guild_blacklist(bot: discord.Client) -> set[int]:
    raw = getattr(bot, "blacklist_guild", None)
    return set(raw) if raw is not None else set()


def classify_dm_error(exc: BaseException) -> DMSendOutcome:
    if isinstance(exc, discord.Forbidden):
        if getattr(exc, "code", None) == DISCORD_DM_CLOSED_CODE:
            return DMSendOutcome.DM_CLOSED
        if "cannot send messages to this user" in str(exc).lower():
            return DMSendOutcome.DM_CLOSED
    return DMSendOutcome.FAILED


async def send_player_dm(bot: discord.Client, discord_id: int, message: str) -> DMSendOutcome:
    try:
        user = bot.get_user(discord_id) or await bot.fetch_user(discord_id)
        await user.send(message)
        return DMSendOutcome.SENT
    except discord.Forbidden as exc:
        return classify_dm_error(exc)
    except (discord.NotFound, discord.HTTPException):
        return DMSendOutcome.FAILED


async def run_dm_broadcast(bot: discord.Client, message: str) -> tuple[BroadcastTally, int]:
    total = await count_dm_recipients()
    tally = BroadcastTally()
    processed = 0
    async for discord_id in iter_dm_recipient_ids():
        processed += 1
        tally = tally.merge(await send_player_dm(bot, discord_id, message))
        await sleep_dm_batch(processed)
    return tally, total


def pick_guild_announce_channel(
    guild: discord.Guild,
    bot_member: discord.Member,
    *,
    raid_channel_id: int | None = None,
    preferred_channel_id: int | None = None,
) -> discord.TextChannel | discord.Thread | None:
    """Pick a channel the bot can post server-wide announcements in."""
    perms = bot_member.guild_permissions

    def can_send(channel: discord.abc.GuildChannel | None) -> bool:
        if channel is None or not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False
        return channel.permissions_for(bot_member).send_messages

    if preferred_channel_id is not None:
        preferred = guild.get_channel(preferred_channel_id)
        if can_send(preferred):
            return preferred  # type: ignore[return-value]

    if raid_channel_id is not None:
        raid_ch = guild.get_channel(raid_channel_id)
        if can_send(raid_ch):
            return raid_ch  # type: ignore[return-value]

    news = [
        ch
        for ch in guild.text_channels
        if ch.is_news() and ch.permissions_for(bot_member).send_messages and perms.send_messages
    ]
    if news:
        return sorted(news, key=lambda c: c.position)[0]

    system = guild.system_channel
    if can_send(system):
        return system

    for ch in sorted(guild.text_channels, key=lambda c: c.position):
        if ch.permissions_for(bot_member).send_messages:
            return ch
    return None


def raid_channel_id_for_guild(guild_id: int) -> int | None:
    from fcdex_3_1.fcdex_ext.boss_raid import get_raid

    raid = get_raid(guild_id)
    return raid.channel_id if raid is not None else None


async def sleep_dm_batch(batch_index: int) -> None:
    if batch_index > 0 and batch_index % DM_BATCH_SIZE == 0:
        await asyncio.sleep(DM_BATCH_DELAY_SECONDS)


async def count_server_broadcast_targets(bot: discord.Client) -> int:
    config = await collect_guild_config_channels()
    blacklist = _guild_blacklist(bot)
    count = 0
    for guild in bot.guilds:
        if guild.id in blacklist:
            continue
        member = guild.me
        if member is None:
            continue
        if pick_guild_announce_channel(
            guild,
            member,
            raid_channel_id=raid_channel_id_for_guild(guild.id),
            preferred_channel_id=config.get(guild.id),
        ):
            count += 1
    return count


async def run_server_broadcast(bot: discord.Client, message: str) -> tuple[BroadcastTally, int, int]:
    """Return (tally, guild_count, skipped)."""
    config = await collect_guild_config_channels()
    blacklist = _guild_blacklist(bot)
    guilds = [g for g in bot.guilds if g.id not in blacklist]
    total = len(guilds)
    tally = BroadcastTally()
    skipped = 0
    for index, guild in enumerate(guilds, start=1):
        member = guild.me
        if member is None:
            skipped += 1
            continue
        channel = pick_guild_announce_channel(
            guild,
            member,
            raid_channel_id=raid_channel_id_for_guild(guild.id),
            preferred_channel_id=config.get(guild.id),
        )
        if channel is None:
            skipped += 1
            continue
        try:
            await channel.send(message)
            tally = tally.merge(DMSendOutcome.SENT)
        except discord.Forbidden:
            skipped += 1
            log.warning("Server broadcast: no permission in %s (#%s)", guild.id, channel.id)
        except discord.HTTPException as exc:
            tally = tally.merge(DMSendOutcome.FAILED)
            log.warning("Server broadcast failed in %s: %s", guild.id, exc)
        if index < total:
            await asyncio.sleep(SERVER_GUILD_DELAY_SECONDS)
    return tally, total, skipped
