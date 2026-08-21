from __future__ import annotations

import logging
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from django.utils import timezone

from bd_models.models import Ball, BallInstance, Player, Special, balls
from fcdex_3_1.models import PackClaim, PackType

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.pack")

PACK_COOLDOWNS = {PackType.DAILY: timedelta(hours=24), PackType.WEEKLY: timedelta(days=7)}

PACK_REWARDS = {
    PackType.DAILY: {"coins_min": 250, "coins_max": 750, "balls": 3},
    PackType.WEEKLY: {"coins_min": 1_000, "coins_max": 2_500, "balls": 5},
}

EXCLUSIVE_REWARDS = {"coins_min": 15_000, "coins_max": 45_000, "balls": 5, "special_chance": 0.7}

USER_PACK_TYPES = frozenset({PackType.DAILY, PackType.WEEKLY})

PACK_STATUS_SUMMARIES = {
    PackType.DAILY: "3 clubballs · 250–750 coins · stat rolls",
    PackType.WEEKLY: "5 clubballs · 1,000–2,500 coins · stat rolls",
    PackType.EXCLUSIVE: "5 rare clubballs · 15k–45k coins · high stats · specials",
}

PACK_TYPE_LABELS = {PackType.DAILY: "Daily Pack", PackType.WEEKLY: "Weekly Pack", PackType.EXCLUSIVE: "Exclusive Pack"}


@dataclass(frozen=True)
class PackStatusEntry:
    pack_type: str
    label: str
    rewards_summary: str
    status_emoji: str
    status_text: str
    claimable: bool
    command: str | None


@dataclass(frozen=True)
class PackRewardLine:
    country: str
    attack_bonus: int
    health_bonus: int
    special_name: str | None = None


@dataclass(frozen=True)
class PackOpenSuccess:
    message: str
    instances: tuple[BallInstance, ...]
    balls: tuple[Ball, ...]
    reward_lines: tuple[PackRewardLine, ...] = ()


async def last_pack_claim(player: Player, pack_type: str) -> PackClaim | None:
    return await PackClaim.objects.filter(player=player, pack_type=pack_type).order_by("-claimed_at").afirst()


def cooldown_remaining(last: PackClaim | None, pack_type: str) -> timedelta | None:
    if last is None:
        return None
    now = timezone.now()
    if pack_type == PackType.DAILY:
        if last.claimed_at.date() == now.date():
            # Reset at next UTC midnight
            next_midnight = datetime.combine(
                now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.get_current_timezone()
            )
            return next_midnight - now
        return None

    if pack_type not in PACK_COOLDOWNS:
        return None
    delta = PACK_COOLDOWNS[PackType(pack_type)]
    ready_at = last.claimed_at + delta
    if now >= ready_at:
        return None
    return ready_at - now


def _server_bonus_caps() -> tuple[int, int]:
    try:
        from settings.models import settings as server_settings

        return max(1, int(server_settings.max_attack_bonus)), max(1, int(server_settings.max_health_bonus))
    except (ImportError, ModuleNotFoundError, AttributeError, TypeError, ValueError):
        return 10, 10


def roll_pack_stat_bonuses(pack_type: str) -> tuple[int, int]:
    max_atk, max_hp = _server_bonus_caps()
    if pack_type == PackType.EXCLUSIVE:
        return (random.randint(max(max_atk * 3 // 4, 1), max_atk), random.randint(max(max_hp * 3 // 4, 1), max_hp))
    if pack_type == PackType.WEEKLY:
        return (random.randint(-max_atk // 2, max_atk), random.randint(-max_hp // 2, max_hp))
    return (random.randint(-max_atk, max_atk), random.randint(-max_hp, max_hp))


def _special_is_active(special: Special, now: datetime, *, min_dt: datetime, max_dt: datetime) -> bool:
    start = special.start_date or min_dt
    end = special.end_date or max_dt
    return start <= now <= end


async def pick_random_special() -> Special | None:
    tz = timezone.get_current_timezone()
    now = timezone.now()
    min_dt = datetime.min.replace(tzinfo=tz)
    max_dt = datetime.max.replace(tzinfo=tz)
    population: list[Special] = []
    try:
        from bd_models.models import specials as specials_cache

        population = [
            special
            for special in specials_cache.values()
            if _special_is_active(special, now, min_dt=min_dt, max_dt=max_dt)
        ]
    except (ImportError, AttributeError):
        population = []
    if not population:
        population = [
            special
            async for special in Special.objects.all()
            if _special_is_active(special, now, min_dt=min_dt, max_dt=max_dt)
        ]
    if not population:
        return None
    common_weight = max(0.0, 1.0 - sum(special.rarity for special in population))
    weights = [special.rarity for special in population] + [common_weight]
    return random.choices(population=population + [None], weights=weights, k=1)[0]


def _spawnable_balls(*, rare_bias: bool = False) -> list[Ball]:
    cached = list(balls.values()) if balls else []
    pool = [ball for ball in cached if ball.enabled]
    if not pool and Ball.objects.exists():
        return []
    if not rare_bias or len(pool) < 3:
        return pool
    sorted_pool = sorted(pool, key=lambda ball: ball.rarity)
    cutoff = max(1, len(sorted_pool) // 3)
    return sorted_pool[:cutoff]


async def _resolve_ball_pool(*, rare_bias: bool = False) -> list[Ball]:
    pool = _spawnable_balls(rare_bias=rare_bias)
    if pool:
        return pool
    return [ball async for ball in Ball.objects.filter(enabled=True)]


async def _pick_pack_ball(*, rare_bias: bool = False) -> Ball | None:
    pool = await _resolve_ball_pool(rare_bias=rare_bias)
    if not pool:
        return None
    weights = [ball.rarity for ball in pool]
    if sum(weights) <= 0:
        return random.choice(pool)
    return random.choices(pool, weights=weights, k=1)[0]


async def grant_random_clubball(
    player: Player,
    *,
    guild_id: int | None,
    pack_type: str = PackType.DAILY,
    special_chance: float = 0.0,
    rare_bias: bool = False,
) -> PackRewardLine | None:
    ball = await _pick_pack_ball(rare_bias=rare_bias)
    if ball is None:
        return None
    attack_bonus, health_bonus = roll_pack_stat_bonuses(pack_type)
    special: Special | None = None
    if random.random() < special_chance:
        special = await pick_random_special()
    await BallInstance.objects.acreate(
        ball=ball,
        player=player,
        attack_bonus=attack_bonus,
        health_bonus=health_bonus,
        server_id=guild_id,
        special=special,
    )
    return PackRewardLine(
        country=ball.country,
        attack_bonus=attack_bonus,
        health_bonus=health_bonus,
        special_name=special.name if special else None,
    )


def _format_cooldown(remaining: timedelta) -> str:
    hours = int(remaining.total_seconds() // 3600)
    mins = int((remaining.total_seconds() % 3600) // 60)
    return f"{hours}h {mins}m"


async def pack_status_entries(player: Player) -> list[PackStatusEntry]:
    entries: list[PackStatusEntry] = []
    for pack_type in (PackType.DAILY, PackType.WEEKLY, PackType.EXCLUSIVE):
        label = PACK_TYPE_LABELS[pack_type]
        summary = PACK_STATUS_SUMMARIES[pack_type]
        if pack_type == PackType.EXCLUSIVE:
            entries.append(
                PackStatusEntry(
                    pack_type=pack_type,
                    label=label,
                    rewards_summary=summary,
                    status_emoji="🛡️",
                    status_text="Admin only — not claimable",
                    claimable=False,
                    command=None,
                )
            )
            continue

        last = await last_pack_claim(player, pack_type)
        remaining = cooldown_remaining(last, pack_type)
        command = f"/pack {pack_type}"
        if remaining is None:
            entries.append(
                PackStatusEntry(
                    pack_type=pack_type,
                    label=label,
                    rewards_summary=summary,
                    status_emoji="✅",
                    status_text="Ready to claim",
                    claimable=True,
                    command=command,
                )
            )
        else:
            entries.append(
                PackStatusEntry(
                    pack_type=pack_type,
                    label=label,
                    rewards_summary=summary,
                    status_emoji="⏳",
                    status_text=f"Cooldown — {_format_cooldown(remaining)}",
                    claimable=False,
                    command=command,
                )
            )
    return entries


def format_pack_open_message(pack_label: str, coins: int, reward_lines: list[PackRewardLine]) -> str:
    if not reward_lines:
        ball_text = "no clubballs (dex cache empty)"
    else:
        parts: list[str] = []
        for line in reward_lines:
            stats = f"`{line.attack_bonus:+}%` ATK · `{line.health_bonus:+}%` HP"
            tag = f" · **{line.special_name}**" if line.special_name else ""
            parts.append(f"**{line.country}** ({stats}){tag}")
        ball_text = "\n".join(parts)
    return f"**+{coins:,}** coins\n**{len(reward_lines)}** clubball(s):\n{ball_text}"


def collection_card_file(ball: Ball, *, index: int = 1) -> discord.File | None:
    card = ball.collection_card
    if not card:
        return None
    ext = card.name.rsplit(".", 1)[-1]
    return discord.File(str(card.path), filename=f"pack-card-{index}.{ext}")


async def render_pack_card_file(
    instance: BallInstance, ball: Ball, *, bot: BallsDexBot, index: int = 1
) -> discord.File | None:
    try:
        with ThreadPoolExecutor() as pool:
            buffer = await bot.loop.run_in_executor(pool, instance.draw_card)
        return discord.File(buffer, f"pack-card-{index}.webp")
    except Exception:
        log.debug("draw_card failed for pack reward, falling back to collection_card", exc_info=True)
        return collection_card_file(ball, index=index)


async def _grant_pack_rewards(
    player: Player,
    pack_type: str,
    *,
    guild_id: int | None,
    rewards: dict[str, int],
    rare_bias: bool,
    special_chance: float,
) -> PackOpenSuccess:
    coins = random.randint(rewards["coins_min"], rewards["coins_max"])
    if coins:
        await player.add_money(coins)

    granted_balls: list[Ball] = []
    granted_instances: list[BallInstance] = []
    reward_lines: list[PackRewardLine] = []

    for _ in range(rewards["balls"]):
        ball = await _pick_pack_ball(rare_bias=rare_bias)
        if ball is None:
            break
        attack_bonus, health_bonus = roll_pack_stat_bonuses(pack_type)
        special: Special | None = None
        if random.random() < special_chance:
            special = await pick_random_special()
        instance = await BallInstance.objects.acreate(
            ball=ball,
            player=player,
            attack_bonus=attack_bonus,
            health_bonus=health_bonus,
            server_id=guild_id,
            special=special,
        )
        granted_balls.append(ball)
        granted_instances.append(instance)
        reward_lines.append(
            PackRewardLine(
                country=ball.country,
                attack_bonus=attack_bonus,
                health_bonus=health_bonus,
                special_name=special.name if special else None,
            )
        )

    pack_label = PACK_TYPE_LABELS[pack_type]
    message = format_pack_open_message(pack_label, coins, reward_lines)
    return PackOpenSuccess(
        message=message,
        instances=tuple(granted_instances),
        balls=tuple(granted_balls),
        reward_lines=tuple(reward_lines),
    )


async def grant_player_pack(
    player: Player, pack_type: str, *, guild_id: int | None
) -> tuple[bool, str | PackOpenSuccess]:
    if pack_type not in USER_PACK_TYPES:
        return False, "**Exclusive Pack** can only be granted by admins — it is not available from `/pack`."

    pack_enum = PackType(pack_type)
    last = await last_pack_claim(player, pack_type)
    if remaining := cooldown_remaining(last, pack_type):
        hours = int(remaining.total_seconds() // 3600)
        mins = int((remaining.total_seconds() % 3600) // 60)
        return False, f"**{PACK_TYPE_LABELS[pack_type]}** is on cooldown — try again in **{hours}h {mins}m**."

    success = await _grant_pack_rewards(
        player, pack_type, guild_id=guild_id, rewards=PACK_REWARDS[pack_enum], rare_bias=False, special_chance=0.0
    )
    await PackClaim.objects.acreate(player=player, pack_type=pack_type)
    if pack_type == PackType.DAILY:
        from fcdex_3_1.fcdex_ext.quest_logic import bump_quest

        await bump_quest(player, "pack_daily")
    return True, success


async def grant_exclusive_pack(player: Player, *, guild_id: int | None) -> PackOpenSuccess:
    success = await _grant_pack_rewards(
        player,
        PackType.EXCLUSIVE,
        guild_id=guild_id,
        rewards=EXCLUSIVE_REWARDS,
        rare_bias=True,
        special_chance=EXCLUSIVE_REWARDS["special_chance"],
    )
    await PackClaim.objects.acreate(player=player, pack_type=PackType.EXCLUSIVE)
    return success
