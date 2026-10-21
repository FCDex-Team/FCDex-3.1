"""Thin adapter between FC Derby and the Club Pass (`club_pass_logic`).

The Club Pass lives in its own module that may not exist in every build, so it is imported on first use and every
call degrades to "Club Pass not available" instead of failing. The attributes read from its results are all optional.

Expected from `fcdex_3_1.fcdex_ext.club_pass_logic`:
    grant_pass_xp(player, amount) -> PassXpResult      (async)   reads: level / new_level, levels_gained, xp
    get_pass_progress(player)                          (async or sync)
        reads: level, xp, xp_to_next / xp_needed, and optionally `upcoming` / `milestones`: a list of objects (or
        dicts) with `level` and one of `label` / `name` / `reward` / `description`.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("fcdex_3_1.derby.pass")

MODULE_NAME = "fcdex_3_1.fcdex_ext.club_pass_logic"
UNAVAILABLE = "Club Pass not available"


@dataclass(frozen=True, slots=True)
class PassXpOutcome:
    available: bool
    xp: int = 0
    level: int | None = None
    levels_gained: int = 0

    @property
    def text(self) -> str:
        if not self.available:
            return UNAVAILABLE
        from fcdex_3_1.fcdex_ext.derby_logic import format_xp_level_text

        return format_xp_level_text(self.xp, self.levels_gained, self.level)


@dataclass(frozen=True, slots=True)
class PassMilestone:
    level: int
    label: str


@dataclass(frozen=True, slots=True)
class PassStatus:
    available: bool
    level: int | None = None
    xp: int | None = None
    xp_to_next: int | None = None
    milestones: list[PassMilestone] = field(default_factory=list)


def _load() -> Any | None:
    try:
        return importlib.import_module(MODULE_NAME)
    except ImportError:
        return None
    except Exception:
        log.exception("Club Pass module failed to import")
        return None


def _pick(source: Any, *names: str) -> Any:
    for name in names:
        value = source.get(name) if isinstance(source, dict) else getattr(source, name, None)
        if value is not None:
            return value
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def grant_derby_xp(player: Any, amount: int) -> PassXpOutcome:
    """Give Club Pass XP for a derby. Never raises, a missing or broken Club Pass just reports unavailable."""
    module = _load()
    grant = getattr(module, "grant_pass_xp", None) if module else None
    if grant is None:
        return PassXpOutcome(available=False)
    try:
        result = await _maybe_await(grant(player, amount))
    except Exception:
        log.exception("Club Pass XP grant failed for player %s", getattr(player, "pk", "?"))
        return PassXpOutcome(available=False)
    return PassXpOutcome(
        available=True,
        xp=amount,
        level=_as_int(_pick(result, "level", "new_level")),
        levels_gained=_as_int(_pick(result, "levels_gained", "levels_up")) or 0,
    )


def _milestones(raw: Any) -> list[PassMilestone]:
    out: list[PassMilestone] = []
    for entry in raw or []:
        level = _as_int(_pick(entry, "level"))
        if level is None:
            continue
        label = _pick(entry, "label", "name", "reward", "description")
        out.append(PassMilestone(level=level, label=str(label) if label else f"Level {level}"))
    return out


async def club_pass_status(player: Any) -> PassStatus:
    """Level, XP and upcoming reward levels of a player's Club Pass, or `available=False`."""
    module = _load()
    get_progress = getattr(module, "get_pass_progress", None) if module else None
    if get_progress is None:
        return PassStatus(available=False)
    try:
        progress = await _maybe_await(get_progress(player))
    except Exception:
        log.exception("Club Pass progress failed for player %s", getattr(player, "pk", "?"))
        return PassStatus(available=False)
    if progress is None:
        return PassStatus(available=False)
    return PassStatus(
        available=True,
        level=_as_int(_pick(progress, "level")),
        xp=_as_int(_pick(progress, "xp", "total_xp")),
        xp_to_next=_as_int(_pick(progress, "xp_to_next", "xp_needed")),
        milestones=_milestones(_pick(progress, "upcoming", "milestones")),
    )
