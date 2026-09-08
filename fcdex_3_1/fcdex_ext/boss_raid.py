from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Literal

from bd_models.models import Ball, BallInstance, Player, Special
from fcdex_3_1.fcdex_ext.bd_helpers import instance_attack, instance_health

log = logging.getLogger("fcdex_3_1.boss.raid")

BossPhase = Literal["join", "pick", "resolve", "ended"]
MAX_ROUNDS = 3
BOSS_SPECIAL_NAME = "Boss"


@dataclass
class BossParticipant:
    discord_id: int
    total_damage: int = 0
    round_damage: int = 0
    round_boss_damage: int = 0
    selected_instance_id: int | None = None
    disqualified: bool = False


@dataclass
class BossRaid:
    scope_id: int  # guild id in servers, DM channel id in DMs
    channel_id: int  # channel where the raid was announced
    boss_ball_id: int
    max_hp: int
    current_hp: int
    reward_ball_id: int | None = None
    reward_server_id: int | None = None  # BallsDex server_id on grants; None in DMs
    phase: BossPhase = "join"
    round: int = 0
    is_attack_round: bool = True
    participants: dict[int, BossParticipant] = field(default_factory=dict)
    used_instance_ids: set[int] = field(default_factory=set)
    announcement_message_id: int | None = None
    last_round_log: str = ""

    @property
    def alive_participant_ids(self) -> list[int]:
        return [uid for uid, p in self.participants.items() if not p.disqualified]

    @property
    def reward_ball_id_effective(self) -> int:
        return self.reward_ball_id if self.reward_ball_id is not None else self.boss_ball_id

    @property
    def rounds_complete(self) -> bool:
        return self.round >= MAX_ROUNDS and self.phase == "resolve"


def _raids() -> dict[int, BossRaid]:
    from fcdex_3_1.fcdex_ext import boss_raid as mod

    return mod._ACTIVE_RAIDS


_ACTIVE_RAIDS: dict[int, BossRaid] = {}


def raid_scope_id(guild_id: int | None, channel_id: int) -> int:
    """Server raids are guild-wide; DMs use the DM channel id."""
    return guild_id if guild_id is not None else channel_id


def get_raid(scope_id: int | None) -> BossRaid | None:
    if scope_id is None:
        return None
    return _ACTIVE_RAIDS.get(scope_id)


async def ensure_boss_special() -> Special | None:
    return await Special.objects.filter(name__iexact=BOSS_SPECIAL_NAME).afirst()


def start_raid(
    *,
    scope_id: int,
    channel_id: int,
    boss_ball: Ball,
    hp: int,
    reward_ball: Ball | None = None,
    reward_server_id: int | None = None,
) -> BossRaid:
    if scope_id in _ACTIVE_RAIDS:
        raise ValueError("A boss raid is already active here.")
    raid = BossRaid(
        scope_id=scope_id,
        channel_id=channel_id,
        boss_ball_id=boss_ball.pk,
        max_hp=hp,
        current_hp=hp,
        reward_ball_id=reward_ball.pk if reward_ball is not None else None,
        reward_server_id=reward_server_id,
    )
    _ACTIVE_RAIDS[scope_id] = raid
    return raid


def end_raid(scope_id: int) -> BossRaid | None:
    return _ACTIVE_RAIDS.pop(scope_id, None)


def join_raid(raid: BossRaid, user_id: int) -> tuple[bool, str]:
    if raid.phase not in ("join", "pick"):
        return False, "Registration is closed — wait for the next raid."
    if user_id in raid.participants:
        return False, "You already joined this raid."
    raid.participants[user_id] = BossParticipant(discord_id=user_id)
    return True, "You joined the boss raid!"


def can_start_round(raid: BossRaid) -> tuple[bool, str]:
    if raid.phase == "ended":
        return False, "This raid has ended."
    if raid.phase == "pick":
        return False, "Resolve the current round before starting another."
    if raid.rounds_complete:
        return False, "All 3 rounds complete — use **Conclude**."
    if raid.phase == "resolve" and raid.round >= MAX_ROUNDS:
        return False, "All 3 rounds complete — use **Conclude**."
    if raid.phase == "join" and raid.round == 0:
        return True, ""
    if raid.phase == "resolve" and raid.round < MAX_ROUNDS:
        return True, ""
    return False, "Cannot start a round right now."


def begin_round(raid: BossRaid) -> tuple[bool, str]:
    ok, message = can_start_round(raid)
    if not ok:
        return False, message
    if raid.round >= MAX_ROUNDS:
        return False, "All 3 rounds complete — use **Conclude**."
    raid.round += 1
    raid.is_attack_round = True
    raid.phase = "pick"
    for participant in raid.participants.values():
        participant.round_damage = 0
        participant.round_boss_damage = 0
        participant.selected_instance_id = None
    return (True, f"Round **{raid.round}/{MAX_ROUNDS}** — pick a clubball in `/fcdex boss`, then **Resolve**.")


async def submit_card(raid: BossRaid, user_id: int, instance: BallInstance) -> tuple[bool, str]:
    if raid.phase != "pick":
        return False, "You cannot select a clubball right now."
    participant = raid.participants.get(user_id)
    if participant is None or participant.disqualified:
        return False, "You are not in this raid (or were disqualified). Join during registration first."
    if instance.pk in raid.used_instance_ids:
        return False, "That clubball was already used in this raid."
    if participant.selected_instance_id is not None:
        return False, "You already locked a clubball this round."
    participant.selected_instance_id = instance.pk
    return (
        True,
        f"Locked **#{instance.pk}** for round **{raid.round}/{MAX_ROUNDS}** — boss will counter-attack on **Resolve**.",
    )


def _card_power(inst: BallInstance, ball: Ball) -> int:
    return instance_attack(inst, ball) + instance_health(inst, ball)


def _boss_strike(boss_ball: Ball, round_num: int) -> int:
    base = boss_ball.attack + boss_ball.health
    scale = 1.0 + (round_num - 1) * 0.15
    return max(1, int(base * scale * random.uniform(0.85, 1.15)))


async def resolve_round(raid: BossRaid) -> str:
    if raid.phase != "pick":
        return "Nothing to resolve — start a round first."
    try:
        boss_ball = await Ball.objects.aget(pk=raid.boss_ball_id)
    except Ball.DoesNotExist:
        raid.phase = "ended"
        return "The boss clubball no longer exists — raid cancelled."
    lines: list[str] = [f"### Round **{raid.round}/{MAX_ROUNDS}** results"]
    total = 0
    locked = 0
    skipped = 0
    for participant in raid.participants.values():
        if participant.disqualified:
            continue
        if participant.selected_instance_id is None:
            skipped += 1
            continue
        locked += 1
        try:
            inst = await BallInstance.objects.select_related("ball").aget(pk=participant.selected_instance_id)
        except BallInstance.DoesNotExist:
            skipped += 1
            log.warning(
                "Boss raid: missing instance %s for <@%s>", participant.selected_instance_id, participant.discord_id
            )
            continue
        ball = inst.ball
        power = _card_power(inst, ball)
        dmg = max(1, int(power * random.uniform(0.85, 1.15)))
        participant.round_damage = dmg
        participant.total_damage += dmg
        total += dmg
        raid.used_instance_ids.add(inst.pk)
        lines.append(f"<@{participant.discord_id}> dealt **{dmg:,}** with {ball.country}")

        boss_hit = _boss_strike(boss_ball, raid.round)
        participant.round_boss_damage = boss_hit
        card_hp = power
        if boss_hit >= card_hp:
            participant.disqualified = True
            lines.append(
                f"👹 Boss countered **#{inst.pk}** for **{boss_hit:,}** — <@{participant.discord_id}> **knocked out!**"
            )
        else:
            remaining = card_hp - boss_hit
            lines.append(
                f"👹 Boss hit **#{inst.pk}** for **{boss_hit:,}** "
                f"(**{remaining:,}** HP left) — <@{participant.discord_id}> survives."
            )
    raid.current_hp = max(0, raid.current_hp - total)
    if total == 0:
        if not raid.participants:
            lines.append("\n*No damage — nobody joined the raid yet.*")
        elif locked == 0:
            lines.append(
                f"\n*No damage — **{skipped}** player(s) did not lock a clubball in `/fcdex boss` "
                "(same server/DM as the announcement).*"
            )
        else:
            lines.append("\n*No damage — locked cards could not be resolved.*")
    lines.append(f"\nBoss HP: **{raid.current_hp:,}** / **{raid.max_hp:,}**")
    if raid.current_hp <= 0:
        lines.append("\n☠️ **Boss defeated!** Admins: **Conclude** to award the winner.")
    raid.phase = "resolve"
    if raid.rounds_complete:
        lines.append("\n-# All **3** rounds are done — admins: **Conclude** to award the winner.")
    raid.last_round_log = "\n".join(lines)
    return raid.last_round_log


def standings(raid: BossRaid) -> str:
    rows = sorted(raid.participants.values(), key=lambda p: p.total_damage, reverse=True)
    if not rows:
        return "*No participants yet — players must join during registration.*"
    return "\n".join(
        f"{'🚫' if p.disqualified else '▸'} <@{p.discord_id}> — **{p.total_damage:,}** total damage" for p in rows
    )


def pick_raid_winner_id(raid: BossRaid) -> int | None:
    eligible = [p for p in raid.participants.values() if p.total_damage > 0 and not p.disqualified]
    if not eligible:
        return None
    return max(eligible, key=lambda p: p.total_damage).discord_id


def top_damage_tie_ids(raid: BossRaid) -> list[int]:
    eligible = [p for p in raid.participants.values() if p.total_damage > 0 and not p.disqualified]
    if not eligible:
        return []
    top = max(p.total_damage for p in eligible)
    return sorted(p.discord_id for p in eligible if p.total_damage == top)


def top_damage_leaderboard(raid: BossRaid, *, limit: int = 5) -> str:
    rows = sorted(raid.participants.values(), key=lambda p: p.total_damage, reverse=True)
    if not rows:
        return "*No participants.*"
    lines = [
        f"{i}. {'🚫' if p.disqualified else '▸'} <@{p.discord_id}> — **{p.total_damage:,}**"
        for i, p in enumerate(rows[:limit], 1)
    ]
    if len(rows) > limit:
        lines.append(f"-# …and **{len(rows) - limit}** more")
    return "\n".join(lines)


def format_public_raid_results(
    raid: BossRaid, *, boss_country: str, winner_id: int | None, reward_line: str | None
) -> str:
    if raid.current_hp <= 0:
        outcome = "☠️ **Boss defeated!**"
    else:
        outcome = f"🛡️ **Boss survived** — **{raid.current_hp:,}** HP remaining."

    parts = [f"# 🏁 {boss_country} — raid results", outcome, f"Final HP: **{raid.current_hp:,}** / **{raid.max_hp:,}**"]

    if winner_id is not None:
        tied = top_damage_tie_ids(raid)
        if len(tied) > 1:
            tie_mentions = ", ".join(f"<@{uid}>" for uid in tied)
            parts.append(f"\n🏆 **Top damage (tie):** {tie_mentions}")
            parts.append(f"-# Winner for rewards: <@{winner_id}>")
        else:
            parts.append(f"\n🏆 **Winner:** <@{winner_id}>")
    elif not raid.participants:
        parts.append("\n🏆 **Winner:** *None* — no one joined.")
    else:
        parts.append("\n🏆 **Winner:** *None* — no eligible player (0 damage or all knocked out).")

    parts.append("\n### Top damage")
    parts.append(top_damage_leaderboard(raid))
    if reward_line:
        parts.append(f"\n{reward_line}")
    return "\n".join(parts)


@dataclass(frozen=True)
class RaidConcludeResult:
    admin_summary: str
    winner_id: int | None
    public_message: str
    channel_id: int
    announce_publicly: bool


async def conclude_raid(raid: BossRaid, *, grant_reward: bool) -> RaidConcludeResult:
    raid.phase = "ended"
    winner_id = pick_raid_winner_id(raid)
    reward_line: str | None = None

    lines = [f"### Raid concluded\n{standings(raid)}"]
    if winner_id and grant_reward:
        special = await ensure_boss_special()
        player = await Player.objects.filter(discord_id=winner_id).afirst()
        try:
            reward_ball = await Ball.objects.aget(pk=raid.reward_ball_id_effective)
        except Ball.DoesNotExist:
            reward_ball = None
        if reward_ball is None:
            lines.append(f"\n🏆 Top damage: <@{winner_id}> (reward clubball no longer exists — could not grant).")
            reward_line = f"🎁 Top damage: <@{winner_id}> (reward clubball missing — contact staff)."
        elif player and special:
            await BallInstance.objects.acreate(
                ball=reward_ball,
                player=player,
                special=special,
                attack_bonus=0,
                health_bonus=0,
                server_id=raid.reward_server_id,
            )
            lines.append(f"\n🏆 <@{winner_id}> received **{reward_ball.country}** ({special.name})!")
            reward_line = f"🎁 <@{winner_id}> received **{reward_ball.country}** ({special.name})!"
        elif player:
            await BallInstance.objects.acreate(
                ball=reward_ball, player=player, attack_bonus=0, health_bonus=0, server_id=raid.reward_server_id
            )
            lines.append(f"\n🏆 <@{winner_id}> received **{reward_ball.country}**!")
            reward_line = f"🎁 <@{winner_id}> received **{reward_ball.country}**!"
        else:
            lines.append(f"\n🏆 Top damage: <@{winner_id}> (no player record).")
            reward_line = f"🎁 Top damage: <@{winner_id}> (could not grant — no player record)."
    elif winner_id:
        lines.append(f"\n🏆 Top damage: <@{winner_id}> (no reward).")
    else:
        lines.append("\nNo winner recorded.")

    try:
        boss_ball = await Ball.objects.aget(pk=raid.boss_ball_id)
    except Ball.DoesNotExist:
        boss_ball = None
    boss_country = boss_ball.country if boss_ball is not None else "the boss"
    public_message = format_public_raid_results(
        raid, boss_country=boss_country, winner_id=winner_id, reward_line=reward_line
    )
    channel_id = raid.channel_id
    announce_publicly = raid.reward_server_id is not None

    end_raid(raid.scope_id)
    return RaidConcludeResult(
        admin_summary="\n".join(lines),
        winner_id=winner_id,
        public_message=public_message,
        channel_id=channel_id,
        announce_publicly=announce_publicly,
    )


def disqualify(raid: BossRaid, user_id: int) -> tuple[bool, str]:
    participant = raid.participants.get(user_id)
    if participant is None:
        return False, "That user is not in the raid."
    participant.disqualified = True
    return True, f"<@{user_id}> was disqualified."
