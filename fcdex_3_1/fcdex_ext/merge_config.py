from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

log = logging.getLogger("fcdex_3_1.merge.config")

MAX_MERGE_LEVEL = 7
DEFAULT_WEEKLY_CAP = 5
DEFAULT_PERIOD_DAYS = 7


_BUILTIN_LEVEL_EMOJIS: dict[int, str] = {1: "🔨", 2: "🔥", 3: "💠", 4: "⭐", 5: "🌟", 6: "👑", 7: "🏆"}


@dataclass(frozen=True, slots=True)
class MergeLevelConfig:
    level: int
    input_count: int
    attack_bonus: int
    health_bonus: int
    requires_common_inputs: bool
    ball_country: str = ""
    emoji: str = ""


_BUILTIN_LEVELS: dict[int, MergeLevelConfig] = {
    1: MergeLevelConfig(
        level=1,
        input_count=10,
        attack_bonus=8,
        health_bonus=8,
        requires_common_inputs=False,
        emoji=_BUILTIN_LEVEL_EMOJIS[1],
    ),
    2: MergeLevelConfig(
        level=2,
        input_count=9,
        attack_bonus=20,
        health_bonus=20,
        requires_common_inputs=False,
        emoji=_BUILTIN_LEVEL_EMOJIS[2],
    ),
    3: MergeLevelConfig(
        level=3,
        input_count=7,
        attack_bonus=40,
        health_bonus=40,
        requires_common_inputs=False,
        emoji=_BUILTIN_LEVEL_EMOJIS[3],
    ),
    4: MergeLevelConfig(
        level=4,
        input_count=5,
        attack_bonus=65,
        health_bonus=65,
        requires_common_inputs=False,
        emoji=_BUILTIN_LEVEL_EMOJIS[4],
    ),
    5: MergeLevelConfig(
        level=5,
        input_count=4,
        attack_bonus=95,
        health_bonus=95,
        requires_common_inputs=False,
        emoji=_BUILTIN_LEVEL_EMOJIS[5],
    ),
    6: MergeLevelConfig(
        level=6,
        input_count=3,
        attack_bonus=130,
        health_bonus=130,
        requires_common_inputs=False,
        emoji=_BUILTIN_LEVEL_EMOJIS[6],
    ),
    7: MergeLevelConfig(
        level=7,
        input_count=2,
        attack_bonus=170,
        health_bonus=170,
        requires_common_inputs=False,
        emoji=_BUILTIN_LEVEL_EMOJIS[7],
    ),
}


def merge_cards_path() -> Path:
    return Path(str(files("fcdex_3_1").joinpath("media/merge_cards.toml")))


def _parse_level_row(row: dict) -> MergeLevelConfig | None:
    try:
        level = int(row["level"])
        if level < 1 or level > MAX_MERGE_LEVEL:
            return None
        emoji = str(row.get("emoji") or "").strip() or _BUILTIN_LEVEL_EMOJIS.get(level, "✨")
        return MergeLevelConfig(
            level=level,
            input_count=int(row["input_count"]),
            attack_bonus=int(row["attack_bonus"]),
            health_bonus=int(row["health_bonus"]),
            requires_common_inputs=bool(row.get("requires_common", False)),
            ball_country=str(row.get("ball_country") or "").strip(),
            emoji=emoji,
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_merge_cards_config() -> tuple[dict[int, MergeLevelConfig], int, int]:
    """Load level table and default quota from merge_cards.toml, with safe fallbacks."""
    path = merge_cards_path()
    weekly_cap = DEFAULT_WEEKLY_CAP
    period_days = DEFAULT_PERIOD_DAYS
    levels = dict(_BUILTIN_LEVELS)

    if not path.is_file():
        log.warning("merge_cards.toml missing at %s — using built-in defaults.", path)
        return levels, weekly_cap, period_days

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("Failed to parse merge_cards.toml — using built-in defaults.")
        return levels, weekly_cap, period_days

    quota = data.get("quota") or {}
    try:
        weekly_cap = max(1, int(quota.get("weekly_cap", weekly_cap)))
        period_days = max(1, int(quota.get("period_days", period_days)))
    except (TypeError, ValueError):
        pass

    parsed: dict[int, MergeLevelConfig] = {}
    for row in data.get("level") or []:
        if not isinstance(row, dict):
            continue
        cfg = _parse_level_row(row)
        if cfg is not None:
            parsed[cfg.level] = cfg

    if len(parsed) == MAX_MERGE_LEVEL and all(level in parsed for level in range(1, MAX_MERGE_LEVEL + 1)):
        levels = parsed
    else:
        log.warning("merge_cards.toml must define levels 1–7 — using built-in level table.")

    return levels, weekly_cap, period_days


MERGE_LEVELS, DEFAULT_WEEKLY_CAP, DEFAULT_PERIOD_DAYS = load_merge_cards_config()
INPUT_COUNT_TO_LEVEL: dict[int, int] = {cfg.input_count: level for level, cfg in MERGE_LEVELS.items()}
