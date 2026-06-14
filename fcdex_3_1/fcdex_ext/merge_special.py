from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.utils import timezone

from bd_models.models import Special, specials
from fcdex_3_1.fcdex_ext.merge_assets import merge_background_filename, read_merge_card
from fcdex_3_1.fcdex_ext.merge_config import MAX_MERGE_LEVEL
from fcdex_3_1.fcdex_ext.merge_levels import get_merge_level_config

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.merge.special")

MERGE_SPECIAL_NAME = "FCDex Merge"
MERGE_SPECIAL_EMOJI = "✨"
MERGE_SPECIAL_CATCH = "Forged in the FCDex merge — matching clubballs became one masterpiece."
MERGE_SPECIAL_NAME_PATTERN = re.compile(r"^FCDex Merge(?: L([1-7]))?$")


def merge_special_name(level: int) -> str:
    if level == 1:
        return MERGE_SPECIAL_NAME
    return f"{MERGE_SPECIAL_NAME} L{level}"


def parse_merge_special_level(name: str) -> int | None:
    match = MERGE_SPECIAL_NAME_PATTERN.match(name.strip())
    if not match:
        return None
    if match.group(1) is None:
        return 1
    return int(match.group(1))


def is_merge_special_name(name: str) -> bool:
    return parse_merge_special_level(name) is not None


def _save_background_sync(special: Special, payload: bytes, *, level: int) -> None:
    special.background.save(merge_background_filename(level), ContentFile(payload), save=True)


def _has_background_file(special: Special) -> bool:
    return bool(special.background and special.background.name)


async def _save_background(special: Special, payload: bytes, *, level: int) -> None:
    await sync_to_async(_save_background_sync)(special, payload, level=level)


async def ensure_merge_special_for_level(level: int) -> Special:
    """Create or repair the merge special for a forge tier and attach that tier's card art."""
    if level < 1 or level > MAX_MERGE_LEVEL:
        raise ValueError(f"Invalid merge level: {level}")

    name = merge_special_name(level)
    cfg = get_merge_level_config(level)
    payload = read_merge_card(level)
    special = await Special.objects.filter(name=name).afirst()

    if special is None:
        special = await Special.objects.acreate(
            name=name,
            catch_phrase=MERGE_SPECIAL_CATCH,
            emoji=cfg.emoji or MERGE_SPECIAL_EMOJI,
            rarity=0,
            tradeable=True,
            hidden=True,
            start_date=timezone.now(),
        )
        await _save_background(special, payload, level=level)
        special = await Special.objects.aget(pk=special.pk)
        log.info("Created merge special %s (pk=%s) for L%s.", name, special.pk, level)
    elif not await sync_to_async(_has_background_file)(special):
        await _save_background(special, payload, level=level)
        special = await Special.objects.aget(pk=special.pk)
        log.info("Repaired missing background for merge special %s (L%s).", name, level)

    specials[special.pk] = special
    return special


async def ensure_all_merge_specials() -> list[Special]:
    created: list[Special] = []
    for level in range(1, MAX_MERGE_LEVEL + 1):
        created.append(await ensure_merge_special_for_level(level))
    return created


async def get_merge_special_for_level(level: int) -> Special:
    name = merge_special_name(level)
    cached = next((entry for entry in specials.values() if entry.name == name), None)
    if cached is not None:
        return cached
    return await ensure_merge_special_for_level(level)


async def get_merge_special() -> Special:
    return await get_merge_special_for_level(1)


async def bootstrap_merge_specials(bot: BallsDexBot | None = None) -> list[Special]:
    rows = await ensure_all_merge_specials()
    if bot is not None and hasattr(bot, "load_cache"):
        await bot.load_cache()
    log.info("Merge specials ready for L1–L%s (%s tiers).", MAX_MERGE_LEVEL, len(rows))
    return rows


async def bootstrap_merge_special(bot: BallsDexBot | None = None) -> Special:
    rows = await bootstrap_merge_specials(bot)
    return rows[0]
