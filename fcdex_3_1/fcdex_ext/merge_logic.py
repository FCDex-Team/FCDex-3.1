from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import discord
from django.db.models import Q

from bd_models.models import Ball, BallInstance, Player, Special, specials
from fcdex_3_1.fcdex_ext.bd_helpers import format_instance, get_ball, instance_attack, instance_health
from fcdex_3_1.fcdex_ext.merge_levels import (
    MAX_MERGE_LEVEL,
    format_merge_count_mismatch,
    get_merge_level_config,
    get_merge_level_emoji,
    level_requires_ball_country,
    resolve_merge_level_from_bonuses,
)
from fcdex_3_1.fcdex_ext.merge_limits import merge_special_blocked_message
from fcdex_3_1.fcdex_ext.merge_quota import (
    get_merge_quota_snapshot,
    merge_quota_limit_message,
    merge_quota_limit_reached,
)
from fcdex_3_1.fcdex_ext.merge_special import MERGE_SPECIAL_NAME, get_merge_special_for_level, is_merge_special_name
from fcdex_3_1.fcdex_ext.services import increment_stat
from fcdex_3_1.models import MergeLog
from settings.models import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.merge.logic")


class MergeValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def instance_has_merge_special(instance: BallInstance) -> bool:
    if instance.special_id is None:
        return False
    cached = specials.get(instance.special_id)
    if cached is not None:
        return is_merge_special_name(cached.name)
    special = await Special.objects.filter(pk=instance.special_id).afirst()
    return special is not None and is_merge_special_name(special.name)


async def get_instance_merge_level(instance: BallInstance) -> int | None:
    if not await instance_has_merge_special(instance):
        return 0
    return resolve_merge_level_from_bonuses(instance.attack_bonus, instance.health_bonus)


async def is_valid_l1_base_ball(ball: Ball) -> bool:
    """Any enabled clubball is valid as an L1 base input, regardless of rarity."""
    return bool(ball.enabled)


async def is_valid_l1_forge_input(instance: BallInstance) -> bool:
    """True when this instance can be consumed for a Forge L1 merge."""
    if instance.special_id is not None:
        return False
    ball = await get_ball(instance)
    return await is_valid_l1_base_ball(ball)


async def forge_bucket_level_for_instance(instance: BallInstance) -> int | None:
    """UI bucket level for forge inventory, or None when the card cannot be used in any forge tier."""
    if await instance_has_merge_special(instance):
        level = await get_instance_merge_level(instance)
        if level is None or level <= 0:
            return None
        return level
    if await is_valid_l1_forge_input(instance):
        return 0
    return None


async def instance_already_used_in_merge(instance_id: int) -> bool:
    if await MergeLog.objects.filter(Q(source_ball1_id=instance_id) | Q(source_ball2_id=instance_id)).aexists():
        return True
    return await MergeLog.objects.filter(source_ids__contains=instance_id).aexists()


def _duplicate_instance_ids(instances: list[BallInstance]) -> set[int]:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for instance in instances:
        if instance.pk in seen:
            duplicates.add(instance.pk)
        seen.add(instance.pk)
    return duplicates


async def _validate_merge_quota(player: Player) -> None:
    snapshot = await get_merge_quota_snapshot(player)
    if merge_quota_limit_reached(snapshot.used, snapshot.cap):
        from fcdex_3_1.fcdex_ext.merge_quota import get_merge_quota_settings

        settings_row = await get_merge_quota_settings()
        raise MergeValidationError(merge_quota_limit_message(cap=snapshot.cap, period_days=settings_row.period_days))


async def _validate_ball_country_for_level(ball: Ball, target_level: int) -> None:
    required = level_requires_ball_country(target_level)
    if required and ball.country.lower() != required.lower():
        raise MergeValidationError(
            f"{get_merge_level_emoji(target_level)} **Forge L{target_level}** only accepts "
            f"**{required}** clubballs (you selected **{ball.country}**)."
        )


async def _resolve_unanimous_input_level(instances: list[BallInstance]) -> int:
    input_levels: list[int] = []
    for instance in instances:
        input_level = await get_instance_merge_level(instance)
        if input_level is None:
            raise MergeValidationError(
                "One of these cards is a legacy merge result and can't be used in the 7-tier forge."
            )
        input_levels.append(input_level)

    unique_levels = set(input_levels)
    if len(unique_levels) != 1:
        raise MergeValidationError(
            "All inputs must be the same forge tier — either all **plain (no-special)** clubballs "
            "or all the same **forge level** cards."
        )
    return input_levels[0]


async def validate_merge_batch(player: Player, instances: list[BallInstance]) -> int:
    if len(instances) < 2:
        raise MergeValidationError("Pick at least two clubballs to forge.")

    duplicates = _duplicate_instance_ids(instances)
    if duplicates:
        raise MergeValidationError("Each card can only be selected once.")

    input_level = await _resolve_unanimous_input_level(instances)
    if input_level >= MAX_MERGE_LEVEL:
        raise MergeValidationError(merge_special_blocked_message(MERGE_SPECIAL_NAME, max_level=MAX_MERGE_LEVEL))

    target_level = input_level + 1
    cfg = get_merge_level_config(target_level)
    selected_count = len(instances)

    ball_ids = {instance.ball_id for instance in instances}
    if len(ball_ids) != 1:
        raise MergeValidationError("All inputs must be the **same clubball** (same name — not just the same country).")

    if selected_count != cfg.input_count:
        raise MergeValidationError(format_merge_count_mismatch(input_level, target_level, selected_count))

    result_ball = await get_ball(instances[0])
    await _validate_ball_country_for_level(result_ball, target_level)
    await _validate_merge_quota(player)

    for instance in instances:
        if instance.player_id != player.pk:
            raise MergeValidationError(f"All {settings.plural_collectible_name} must belong to you.")
        if instance.deleted:
            raise MergeValidationError("One of these cards is no longer available.")
        if await instance_already_used_in_merge(instance.pk):
            raise MergeValidationError("One of these cards was already used in a merge.")
        if await instance.is_locked():
            raise MergeValidationError("One of these cards is locked for a trade.")

        if input_level == 0:
            if instance.special_id is not None:
                raise MergeValidationError("Forge L1 only accepts plain clubballs without any special.")
            ball = await get_ball(instance)
            if not await is_valid_l1_base_ball(ball):
                country = getattr(ball, "country", "This clubball")
                emoji = get_merge_level_emoji(target_level)
                raise MergeValidationError(
                    f"**{country}** can't be used for **{emoji} Forge L{target_level}** — "
                    "only **enabled** clubballs (no special) count. "
                    "Pick a clubball that shows **Ready** in the dropdown."
                )

    return target_level


async def consume_merge_inputs(instance_ids: list[int]) -> None:
    consumed = await BallInstance.objects.filter(pk__in=instance_ids, deleted=False).aupdate(deleted=True)
    if consumed != len(instance_ids):
        raise MergeValidationError("One of these cards is no longer available.")


def preview_merge_stats(ball: Ball, target_level: int) -> tuple[int, int, int, int]:
    cfg = get_merge_level_config(target_level)
    base_attack = ball.attack
    base_health = ball.health
    preview = BallInstance(attack_bonus=cfg.attack_bonus, health_bonus=cfg.health_bonus)
    preview.ball_id = ball.pk
    return (base_attack, base_health, instance_attack(preview, ball), instance_health(preview, ball))


async def execute_merge(
    player: Player, instances: list[BallInstance], *, guild_id: int | None, bot: BallsDexBot
) -> tuple[BallInstance, str, discord.File | None, int]:
    target_level = await validate_merge_batch(player, instances)
    cfg = get_merge_level_config(target_level)
    merge_special = await get_merge_special_for_level(target_level)
    result_ball = await get_ball(instances[0])

    instance_ids = [instance.pk for instance in instances]
    await consume_merge_inputs(instance_ids)
    for instance in instances:
        instance.deleted = True

    new_instance = await BallInstance.objects.acreate(
        ball=result_ball,
        player=player,
        special=merge_special,
        attack_bonus=cfg.attack_bonus,
        health_bonus=cfg.health_bonus,
        server_id=guild_id,
    )

    await MergeLog.objects.acreate(
        player=player,
        source_ball1=instances[0],
        source_ball2=instances[1] if len(instances) > 1 else None,
        result_ball=new_instance,
        merge_level=target_level,
        source_ids=instance_ids,
    )
    await increment_stat(player, "merges_completed")
    from fcdex_3_1.fcdex_ext.quest_logic import bump_quest

    await bump_quest(player, "merge_once")

    card_file: discord.File | None = None
    try:
        with ThreadPoolExecutor() as pool:
            buffer = await bot.loop.run_in_executor(pool, new_instance.draw_card)
        card_file = discord.File(buffer, "card.webp")
    except Exception:
        log.exception("Merge card render failed for instance %s", new_instance.pk)

    result_label = await format_instance(new_instance)
    _, _, final_attack, final_health = preview_merge_stats(result_ball, target_level)
    level_tag = get_merge_level_emoji(target_level)
    summary = (
        f"{level_tag} **{merge_special.name}** · forge **L{target_level}** complete!\n"
        f"You forged `{result_label}` — **`+{cfg.attack_bonus}%` ATK / `+{cfg.health_bonus}%` HP** "
        f"(≈ **{final_attack}** ATK · **{final_health}** HP)."
    )
    return new_instance, summary, card_file, target_level
