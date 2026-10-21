"""FC Derby database work: config, formation, squad, the daily cap and stats."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone

from fcdex_3_1.fcdex_ext.derby_logic import (
    DerbyRanges,
    SlotKey,
    get_formation,
    ranges_from_config,
    slots_outside,
    utc_day_start,
)
from fcdex_3_1.models import DerbyClaim, DerbyConfig, DerbyLayout, DerbySlot, DerbyStats

if TYPE_CHECKING:
    from bd_models.models import Ball, BallInstance, Player

log = logging.getLogger("fcdex_3_1.derby")

CONFIG_TTL_SECONDS = 30.0

_config_cache: tuple[float, DerbyConfig] | None = None


async def get_derby_config(*, max_age: float = CONFIG_TTL_SECONDS) -> DerbyConfig:
    """The singleton DerbyConfig row (created on first use), cached briefly."""
    global _config_cache
    now = time.monotonic()
    if _config_cache is not None and now - _config_cache[0] < max_age:
        return _config_cache[1]
    config, _ = await DerbyConfig.objects.aget_or_create(pk=1)
    _config_cache = (now, config)
    return config


def invalidate_derby_config() -> None:
    global _config_cache
    _config_cache = None


async def get_derby_ranges() -> DerbyRanges:
    return ranges_from_config(await get_derby_config())


# -- formation and squad ---------------------------------------------------------------------------------------


async def get_formation_key(player: Player) -> str:
    layout = await DerbyLayout.objects.filter(player=player).afirst()
    return get_formation(layout.formation if layout else None).key


async def set_formation(player: Player, key: str) -> list[SlotKey]:
    """Save the formation and drop squad slots the new formation does not have. Returns the dropped slots."""
    formation = get_formation(key)
    await DerbyLayout.objects.aupdate_or_create(player=player, defaults={"formation": formation.key})
    squad = await load_squad(player)
    dropped = slots_outside(formation, squad)
    for position, slot in dropped:
        await DerbySlot.objects.filter(player=player, position=position, slot=slot).adelete()
    return dropped


async def load_slots(player: Player) -> list[DerbySlot]:
    """The player's slots with their clubballs. Cards that were traded away or deleted are removed first."""
    await DerbySlot.objects.filter(player=player).exclude(instance__player=player, instance__deleted=False).adelete()
    return [slot async for slot in DerbySlot.objects.filter(player=player).select_related("ball", "instance")]


async def load_squad(player: Player) -> dict[SlotKey, int]:
    """`{(position, slot): ball_id}` for the player's squad."""
    return {(row.position, row.slot): row.ball_id for row in await load_slots(player)}


async def place_clubball(player: Player, position: str, slot: int, instance: BallInstance, ball: Ball) -> bool:
    """Put a card in a slot, replacing whatever was there. False when the one-club-once rule was hit by a race."""
    try:
        await DerbySlot.objects.aupdate_or_create(
            player=player, position=position, slot=slot, defaults={"instance": instance, "ball": ball}
        )
    except IntegrityError:
        return False
    return True


async def clear_slot(player: Player, position: str, slot: int) -> bool:
    deleted, _ = await DerbySlot.objects.filter(player=player, position=position, slot=slot).adelete()
    return deleted > 0


# -- daily cap -------------------------------------------------------------------------------------------------


async def derbies_used_today(player: Player) -> int:
    return await DerbyClaim.objects.filter(player=player, played_at__gte=utc_day_start(timezone.now())).acount()


async def claim_derby(players: list[Player], *, limit: int) -> Player | None:
    """Claim one derby for every player before the match starts.

    Rows are created first and counted afterwards, so two derbies started at once cannot both slip under the cap.
    Returns the first player who is over the limit (all claims made here are then undone), or None on success.
    """
    claims: list[DerbyClaim] = []
    day_start = utc_day_start(timezone.now())
    try:
        for player in players:
            claims.append(await DerbyClaim.objects.acreate(player=player))
            used = await DerbyClaim.objects.filter(player=player, played_at__gte=day_start).acount()
            if used > limit:
                for claim in claims:
                    await claim.adelete()
                return player
    except Exception:
        for claim in claims:
            await claim.adelete()
        raise
    return None


# -- stats -----------------------------------------------------------------------------------------------------


async def record_result(winner: Player, loser: Player) -> None:
    await _bump(winner, wins=1)
    await _bump(loser, losses=1)


async def record_draw(first: Player, second: Player) -> None:
    await _bump(first)
    await _bump(second)


async def _bump(player: Player, *, wins: int = 0, losses: int = 0) -> None:
    stats, _ = await DerbyStats.objects.aget_or_create(player=player)
    await DerbyStats.objects.filter(pk=stats.pk).aupdate(
        wins=F("wins") + wins, losses=F("losses") + losses, played=F("played") + 1
    )


async def get_derby_stats(player: Player) -> DerbyStats | None:
    return await DerbyStats.objects.filter(player=player).afirst()
