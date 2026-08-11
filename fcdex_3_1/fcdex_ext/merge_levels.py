from __future__ import annotations

from fcdex_3_1.fcdex_ext.merge_config import (
    DEFAULT_PERIOD_DAYS,
    DEFAULT_WEEKLY_CAP,
    INPUT_COUNT_TO_LEVEL,
    MAX_MERGE_LEVEL,
    MERGE_LEVELS,
    MergeLevelConfig,
)

__all__ = [
    "DEFAULT_PERIOD_DAYS",
    "DEFAULT_WEEKLY_CAP",
    "INPUT_COUNT_TO_LEVEL",
    "MAX_MERGE_LEVEL",
    "MERGE_LEVELS",
    "MergeLevelConfig",
    "detect_target_level",
    "format_level_table_row",
    "format_merge_count_mismatch",
    "format_merge_input_requirement",
    "get_merge_level_config",
    "get_merge_level_emoji",
    "level_requires_ball_country",
    "resolve_merge_level_from_bonuses",
]


def get_merge_level_config(level: int) -> MergeLevelConfig:
    try:
        return MERGE_LEVELS[level]
    except KeyError as exc:
        raise ValueError(f"Invalid merge level: {level}") from exc


def detect_target_level(card_count: int) -> int | None:
    """Map a card count to an output forge level (used for hints and legacy checks)."""
    return INPUT_COUNT_TO_LEVEL.get(card_count)


def get_merge_level_emoji(level: int) -> str:
    cfg = get_merge_level_config(level)
    return cfg.emoji or "✨"


def format_merge_input_requirement(input_level: int, target_level: int) -> str:
    cfg = get_merge_level_config(target_level)
    target_tag = f"{get_merge_level_emoji(target_level)} **Forge L{target_level}**"
    if input_level == 0:
        return f"Pick **{cfg.input_count}** plain (no-special) clubballs of the **same clubball** for {target_tag}."
    input_tag = f"{get_merge_level_emoji(input_level)} **L{input_level}**"
    return f"Pick **{cfg.input_count}** forge {input_tag} cards of the **same clubball** to create {target_tag}."


def format_merge_count_mismatch(input_level: int, target_level: int, selected_count: int) -> str:
    cfg = get_merge_level_config(target_level)
    requirement = format_merge_input_requirement(input_level, target_level)
    return f"{requirement} You selected **{selected_count}** (need **{cfg.input_count}**)."


def resolve_merge_level_from_bonuses(attack_bonus: int, health_bonus: int) -> int | None:
    for level in range(MAX_MERGE_LEVEL, 0, -1):
        cfg = MERGE_LEVELS[level]
        if attack_bonus == cfg.attack_bonus and health_bonus == cfg.health_bonus:
            return level
    return None


def format_level_table_row(level: int) -> str:
    cfg = MERGE_LEVELS[level]
    tier_emoji = get_merge_level_emoji(level)
    if cfg.requires_common_inputs or level == 1:
        inputs = f"{cfg.input_count}× plain (no-special)"
    else:
        inputs = f"{cfg.input_count}× {get_merge_level_emoji(level - 1)} L{level - 1}"
    ball_note = f" · **{cfg.ball_country}** only" if cfg.ball_country else ""
    return f"{tier_emoji} **L{level}** · {inputs} → `+{cfg.attack_bonus}%` ATK / `+{cfg.health_bonus}%` HP{ball_note}"


def level_requires_ball_country(level: int) -> str | None:
    cfg = get_merge_level_config(level)
    return cfg.ball_country or None
