from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from django.db.models import Count, F, Q, Value
from django.db.models.functions import Coalesce

from bd_models.models import BallInstance, Player

ENTRIES_PER_PAGE = 5

# Optional Discord user IDs to exclude (bots, test accounts).
EXCLUDE_IDS: list[int] = []

UNKNOWN_USER = "Unknown User"


def resolve_leaderboard_display_name(*, username: str) -> str:
    """Return the Discord username shown on leaderboard rows."""
    return username


class LeaderboardScope(StrEnum):
    SERVER = "server"
    GLOBAL = "global"


class LeaderboardMetric(StrEnum):
    CLUBBALLS = "clubballs"
    BATTLES_WON = "battles_won"
    MERGES = "merges"
    TOURNAMENT_WINS = "tournament_wins"
    DERBY_WINS = "derby_wins"


METRIC_LABELS: dict[LeaderboardMetric, str] = {
    LeaderboardMetric.CLUBBALLS: "Clubballs",
    LeaderboardMetric.BATTLES_WON: "Battles won",
    LeaderboardMetric.MERGES: "Merges",
    LeaderboardMetric.TOURNAMENT_WINS: "Tournament wins",
    LeaderboardMetric.DERBY_WINS: "Derby wins",
}

METRIC_UNITS: dict[LeaderboardMetric, str] = {
    LeaderboardMetric.CLUBBALLS: "clubballs",
    LeaderboardMetric.BATTLES_WON: "wins",
    LeaderboardMetric.MERGES: "merges",
    LeaderboardMetric.TOURNAMENT_WINS: "tournament wins",
    LeaderboardMetric.DERBY_WINS: "derby wins",
}

STAT_FIELDS: dict[LeaderboardMetric, str] = {
    LeaderboardMetric.BATTLES_WON: "battles_won",
    LeaderboardMetric.MERGES: "merges_completed",
    LeaderboardMetric.TOURNAMENT_WINS: "tournament_wins",
    LeaderboardMetric.DERBY_WINS: "wins",
}

# Related name of the stats row that holds each metric (everything else lives on `fcdex_stats`).
STAT_RELATIONS: dict[LeaderboardMetric, str] = {LeaderboardMetric.DERBY_WINS: "derby_stats"}


def stat_relation(metric: LeaderboardMetric) -> str:
    return STAT_RELATIONS.get(metric, "fcdex_stats")


def stat_lookup(metric: LeaderboardMetric) -> str:
    """ORM lookup from a Player to the stat behind `metric`."""
    return f"{stat_relation(metric)}__{STAT_FIELDS[metric]}"


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    rank: int
    discord_id: int
    score: int


@dataclass(frozen=True, slots=True)
class LeaderboardProfile:
    display_name: str
    avatar_url: str


def resolve_default_scope(*, in_guild: bool) -> LeaderboardScope:
    return LeaderboardScope.SERVER if in_guild else LeaderboardScope.GLOBAL


def resolve_scope(
    requested: LeaderboardScope | None, *, in_guild: bool, in_dm: bool
) -> tuple[LeaderboardScope, str | None]:
    """Return effective scope and an optional notice when the request was adjusted."""
    if in_dm:
        if requested == LeaderboardScope.SERVER:
            return (
                LeaderboardScope.GLOBAL,
                "Server rankings are only available inside a Discord server — showing **global** instead.",
            )
        return LeaderboardScope.GLOBAL, None
    if requested is not None:
        return requested, None
    return resolve_default_scope(in_guild=in_guild), None


def server_metric_allowed(metric: LeaderboardMetric) -> bool:
    return metric == LeaderboardMetric.CLUBBALLS


def normalize_metric_for_scope(
    metric: LeaderboardMetric, scope: LeaderboardScope
) -> tuple[LeaderboardMetric, str | None]:
    if scope == LeaderboardScope.SERVER and not server_metric_allowed(metric):
        return (
            LeaderboardMetric.CLUBBALLS,
            (
                "Server rankings only track **clubballs caught here**. "
                "Switch to **Global** for battle, merge, and tournament stats."
            ),
        )
    return metric, None


def page_count(total: int, *, per_page: int = ENTRIES_PER_PAGE) -> int:
    if total <= 0:
        return 1
    return (total + per_page - 1) // per_page


def slice_page(
    entries: list[LeaderboardEntry], page: int, *, per_page: int = ENTRIES_PER_PAGE
) -> list[LeaderboardEntry]:
    start = max(0, page) * per_page
    return entries[start : start + per_page]


def default_avatar_url(discord_id: int) -> str:
    index = (discord_id >> 22) % 6
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


def default_profile(discord_id: int) -> LeaderboardProfile:
    return LeaderboardProfile(display_name=UNKNOWN_USER, avatar_url=default_avatar_url(discord_id))


def format_entry_line(entry: LeaderboardEntry, metric: LeaderboardMetric, *, display_name: str) -> str:
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(entry.rank, "")
    prefix = medal if medal else f"`#{entry.rank}`"
    unit = METRIC_UNITS[metric]
    return f"{prefix} **{display_name}** · **{entry.score:,}** {unit}"


def format_leaderboard_header(
    *, scope: LeaderboardScope, metric: LeaderboardMetric, total: int, guild_name: str | None = None
) -> str:
    scope_label = f"**{guild_name}**" if scope == LeaderboardScope.SERVER and guild_name else "**Global**"
    return f"# 🏆 Leaderboard · {METRIC_LABELS[metric]}\n-# {scope_label} · top **{total}**"


def format_leaderboard_page_footer(page: int, total: int) -> str:
    pages = page_count(total)
    return f"-# Page **{page + 1}/{pages}**"


def format_leaderboard_body(
    entries: list[LeaderboardEntry],
    *,
    scope: LeaderboardScope,
    metric: LeaderboardMetric,
    page: int,
    total: int,
    guild_name: str | None = None,
    display_names: dict[int, str] | None = None,
) -> str:
    header = format_leaderboard_header(scope=scope, metric=metric, total=total, guild_name=guild_name)
    if not entries:
        return f"{header}\n\n*No ranked players yet.*"
    names = display_names or {}
    lines = [
        format_entry_line(entry, metric, display_name=names.get(entry.discord_id, UNKNOWN_USER)) for entry in entries
    ]
    footer = format_leaderboard_page_footer(page, total)
    return f"{header}\n\n" + "\n".join(lines) + f"\n\n{footer}"


def format_viewer_footer(rank: int | None, score: int, metric: LeaderboardMetric) -> str:
    unit = METRIC_UNITS[metric]
    if rank is None or score <= 0:
        return f"You: unranked · **0** {unit}"
    return f"You: **#{rank}** · **{score:,}** {unit}"


def _exclude_bots(qs):
    if EXCLUDE_IDS:
        return qs.exclude(discord_id__in=EXCLUDE_IDS)
    return qs


async def _fetch_server_clubballs(guild_id: int, *, limit: int) -> list[LeaderboardEntry]:
    qs = (
        _exclude_bots(Player.objects.all())
        .annotate(ball_count=Count("balls", filter=Q(balls__deleted=False, balls__server_id=guild_id)))
        .filter(ball_count__gt=0)
        .order_by("-ball_count", "pk")
        .values("discord_id", "ball_count")[:limit]
    )
    entries: list[LeaderboardEntry] = []
    rank = 0
    async for row in qs:
        rank += 1
        entries.append(LeaderboardEntry(rank=rank, discord_id=row["discord_id"], score=row["ball_count"]))
    return entries


async def _fetch_global_clubballs(*, limit: int) -> list[LeaderboardEntry]:
    qs = (
        _exclude_bots(Player.objects.all())
        .annotate(ball_count=Count("balls", filter=Q(balls__deleted=False)))
        .filter(ball_count__gt=0)
        .order_by("-ball_count", "pk")
        .values("discord_id", "ball_count")[:limit]
    )
    entries: list[LeaderboardEntry] = []
    rank = 0
    async for row in qs:
        rank += 1
        entries.append(LeaderboardEntry(rank=rank, discord_id=row["discord_id"], score=row["ball_count"]))
    return entries


async def _fetch_global_stats(metric: LeaderboardMetric, *, limit: int) -> list[LeaderboardEntry]:
    qs = (
        _exclude_bots(Player.objects.all())
        .annotate(score=Coalesce(F(stat_lookup(metric)), Value(0)))
        .filter(score__gt=0)
        .order_by("-score", "pk")
        .values("discord_id", "score")[:limit]
    )
    entries: list[LeaderboardEntry] = []
    rank = 0
    async for row in qs:
        rank += 1
        entries.append(LeaderboardEntry(rank=rank, discord_id=row["discord_id"], score=row["score"]))
    return entries


async def fetch_leaderboard(
    *, scope: LeaderboardScope, metric: LeaderboardMetric, guild_id: int | None, limit: int
) -> list[LeaderboardEntry]:
    if scope == LeaderboardScope.SERVER:
        if guild_id is None:
            return []
        return await _fetch_server_clubballs(guild_id, limit=limit)
    if metric == LeaderboardMetric.CLUBBALLS:
        return await _fetch_global_clubballs(limit=limit)
    return await _fetch_global_stats(metric, limit=limit)


async def _viewer_server_clubballs(viewer_discord_id: int, guild_id: int) -> tuple[int | None, int]:
    player = await Player.objects.filter(discord_id=viewer_discord_id).afirst()
    if player is None:
        return None, 0
    score = await BallInstance.objects.filter(player=player, deleted=False, server_id=guild_id).acount()
    if score <= 0:
        return None, 0
    higher = (
        await _exclude_bots(Player.objects.all())
        .annotate(ball_count=Count("balls", filter=Q(balls__deleted=False, balls__server_id=guild_id)))
        .filter(ball_count__gt=score)
        .acount()
    )
    return higher + 1, score


async def _viewer_global_clubballs(viewer_discord_id: int) -> tuple[int | None, int]:
    player = await Player.objects.filter(discord_id=viewer_discord_id).afirst()
    if player is None:
        return None, 0
    score = await BallInstance.objects.filter(player=player, deleted=False).acount()
    if score <= 0:
        return None, 0
    higher = (
        await _exclude_bots(Player.objects.all())
        .annotate(ball_count=Count("balls", filter=Q(balls__deleted=False)))
        .filter(ball_count__gt=score)
        .acount()
    )
    return higher + 1, score


async def _viewer_global_stats(viewer_discord_id: int, metric: LeaderboardMetric) -> tuple[int | None, int]:
    field = STAT_FIELDS[metric]
    relation = stat_relation(metric)
    player = await Player.objects.filter(discord_id=viewer_discord_id).select_related(relation).afirst()
    if player is None:
        return None, 0
    stats = getattr(player, relation, None)
    score = getattr(stats, field, 0) if stats is not None else 0
    if score <= 0:
        return None, 0
    higher = (
        await _exclude_bots(Player.objects.all())
        .annotate(score=Coalesce(F(stat_lookup(metric)), Value(0)))
        .filter(score__gt=score)
        .acount()
    )
    return higher + 1, score


async def fetch_viewer_placement(
    viewer_discord_id: int, *, scope: LeaderboardScope, metric: LeaderboardMetric, guild_id: int | None
) -> tuple[int | None, int]:
    if viewer_discord_id in EXCLUDE_IDS:
        return None, 0
    if scope == LeaderboardScope.SERVER:
        if guild_id is None:
            return None, 0
        return await _viewer_server_clubballs(viewer_discord_id, guild_id)
    if metric == LeaderboardMetric.CLUBBALLS:
        return await _viewer_global_clubballs(viewer_discord_id)
    return await _viewer_global_stats(viewer_discord_id, metric)
