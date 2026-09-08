from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from bd_models.models import Player
from fcdex_3_1.models import PlayerQuestProgress, QuestDefinition

DAILY_QUESTS = (
    ("pack_daily", "Open your daily pack", 1, 500, "pack_daily"),
    ("battle_play", "Play a battle", 1, 300, "battle_play"),
    ("merge_once", "Complete a merge", 1, 400, "merge_once"),
)


@dataclass(frozen=True, slots=True)
class QuestSpec:
    quest_key: str
    label: str
    target: int
    reward_coins: int
    hook_key: str


def _spec_from_row(row: QuestDefinition) -> QuestSpec:
    return QuestSpec(
        quest_key=row.quest_key,
        label=row.label,
        target=row.target,
        reward_coins=row.reward_coins,
        hook_key=row.hook_key,
    )


def _fallback_specs() -> list[QuestSpec]:
    return [
        QuestSpec(quest_key=key, label=label, target=target, reward_coins=coins, hook_key=hook)
        for key, label, target, coins, hook in DAILY_QUESTS
    ]


async def list_quest_specs(*, enabled_only: bool = True) -> list[QuestSpec]:
    qs = QuestDefinition.objects.all().order_by("sort_order", "quest_key")
    if enabled_only:
        qs = qs.filter(enabled=True)
    rows = [row async for row in qs]
    if rows:
        return [_spec_from_row(row) for row in rows]
    return _fallback_specs()


async def get_quest_spec(quest_key: str) -> QuestSpec | None:
    row = await QuestDefinition.objects.filter(quest_key=quest_key).afirst()
    if row is not None:
        return _spec_from_row(row)
    for spec in _fallback_specs():
        if spec.quest_key == quest_key:
            return spec
    return None


async def quest_keys_for_hook(hook_key: str) -> list[str]:
    keys = [
        row.quest_key
        async for row in QuestDefinition.objects.filter(hook_key=hook_key, enabled=True).order_by(
            "sort_order", "quest_key"
        )
    ]
    if keys:
        return keys
    return [spec.quest_key for spec in _fallback_specs() if spec.hook_key == hook_key]


async def ensure_daily_quests(player: Player) -> list[PlayerQuestProgress]:
    today = timezone.localdate()
    rows: list[PlayerQuestProgress] = []
    for spec in await list_quest_specs(enabled_only=True):
        row, _ = await PlayerQuestProgress.objects.aget_or_create(
            player=player, quest_key=spec.quest_key, day=today, defaults={"target": spec.target, "progress": 0}
        )
        if row.target != spec.target and not row.claimed_at:
            row.target = spec.target
            await row.asave(update_fields=("target",))
        rows.append(row)
    return rows


async def bump_quest(player: Player, hook_key: str, amount: int = 1) -> None:
    today = timezone.localdate()
    for quest_key in await quest_keys_for_hook(hook_key):
        try:
            row = await PlayerQuestProgress.objects.aget(player=player, quest_key=quest_key, day=today)
        except PlayerQuestProgress.DoesNotExist:
            continue
        if row.claimed_at:
            continue
        row.progress = min(row.target, row.progress + amount)
        if row.progress >= row.target and not row.completed_at:
            row.completed_at = timezone.now()
        await row.asave(update_fields=("progress", "completed_at"))


async def claim_quest(player: Player, quest_key: str) -> tuple[bool, str]:
    today = timezone.localdate()
    try:
        row = await PlayerQuestProgress.objects.aget(player=player, quest_key=quest_key, day=today)
    except PlayerQuestProgress.DoesNotExist:
        return False, "Quest not found for today."

    if not row.completed_at:
        return False, f"Quest not complete ({row.progress}/{row.target})."
    if row.claimed_at:
        return False, "Already claimed today."

    locked = await PlayerQuestProgress.objects.filter(pk=row.pk, claimed_at__isnull=True).aupdate(
        claimed_at=timezone.now()
    )
    if not locked:
        return False, "Already claimed today."

    spec = await get_quest_spec(quest_key)
    reward = spec.reward_coins if spec else 0
    label = spec.label if spec else quest_key
    if reward:
        await player.add_money(reward)
    return True, f"Claimed **{label}** — **+{reward:,}** coins!"
