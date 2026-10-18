"""Shared plumbing for twin and match spawns: catch engines, attachments, prompt messages and posting."""

from __future__ import annotations

import logging
import random
import string
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot
    from ballsdex.packages.countryballs.countryball import BallSpawnView
    from bd_models.models import Ball

log = logging.getLogger("fcdex_3_1.spawn")

ACCENT_TWIN = discord.Colour.gold()
ACCENT_MATCH = discord.Colour.green()


def engine_class() -> type[BallSpawnView]:
    """The host's spawn view. Imported lazily so this package loads even if BallsDex reorganises it."""
    from ballsdex.packages.countryballs.countryball import BallSpawnView

    return BallSpawnView


def new_engine(bot: BallsDexBot, ball: Ball, *, algo: str | None) -> BallSpawnView:
    """A host `BallSpawnView` used purely as a catch engine.

    It is never sent to Discord. Catching through it keeps specials, stat bonuses, hooks, events and metrics
    identical to a normal catch.
    """
    engine = engine_class()(bot, ball)
    engine.algo = algo
    return engine


def collectible_names() -> tuple[str, str]:
    try:
        from settings.models import settings

        return settings.collectible_name, settings.plural_collectible_name
    except Exception:
        return "clubball", "clubballs"


def prompt_message(category: str, *, mention: str, model: Ball, bot: BallsDexBot, fallback: str, **extra: Any) -> str:
    """One of the admin-configurable prompt messages (slow, wrong, ...), or `fallback` if unavailable."""
    try:
        from settings.models import PromptMessage, settings

        return settings.get_formatted_message(
            category=getattr(PromptMessage.PromptType, category), mention=mention, model=model, bot=bot, **extra
        )
    except Exception:
        log.debug("Prompt message %s unavailable, using the fallback.", category, exc_info=True)
        return fallback


def attachment_name(ball: Ball) -> str:
    """Random file name so the spawn image never gives away the clubball's name."""
    extension = ball.wild_card.name.split(".")[-1]
    return f"nt_{''.join(random.choices(string.ascii_letters, k=15))}.{extension}"


def can_post_spawn(channel: discord.abc.GuildChannel) -> bool:
    permissions = channel.permissions_for(channel.guild.me)
    return bool(permissions.send_messages and permissions.attach_files)


async def post_spawn(
    channel: discord.abc.Messageable, view: discord.ui.LayoutView, balls: Sequence[Ball], file_names: Sequence[str]
) -> discord.Message | None:
    """Send a spawn message with one wild card image per ball. Returns None (after logging) on failure."""
    files: list[discord.File] = []
    try:
        for ball, name in zip(balls, file_names):
            files.append(discord.File(ball.wild_card.path, filename=name))
        return await channel.send(view=view, files=files)
    except discord.Forbidden:
        log.warning("Missing permission to post a special spawn in channel %s.", channel)
    except discord.HTTPException:
        log.error("Failed to post a special spawn.", exc_info=True)
    except (OSError, ValueError):
        log.error("Could not read the wild card image of %s.", [ball.country for ball in balls], exc_info=True)
    finally:
        for file in files:
            file.close()
    return None
