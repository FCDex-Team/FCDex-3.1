from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ballsdex.core.utils.transformers import BallEnabledTransform
from bd_models.models import Ball, Player, balls
from fcdex_3_1.fcdex_ext.admin_hub_views import build_admin_hub_layout
from fcdex_3_1.fcdex_ext.boss_views import build_boss_player_layout
from fcdex_3_1.fcdex_ext.leaderboard_logic import (
    LeaderboardMetric,
    LeaderboardScope,
    normalize_metric_for_scope,
    resolve_scope,
)
from fcdex_3_1.fcdex_ext.leaderboard_views import build_leaderboard_layout
from fcdex_3_1.fcdex_ext.quest_logic import claim_quest, ensure_daily_quests, list_quest_specs
from fcdex_3_1.fcdex_ext.rarity_views import (
    CATEGORY_MODES,
    build_ball_rarity_layout,
    build_rarity_menu,
    build_rarity_value_layout,
)
from fcdex_3_1.fcdex_ext.regime_data import REGIMES, regime_by_key
from fcdex_3_1.fcdex_ext.shop_views import build_shop_layout
from fcdex_3_1.fcdex_ext.views import build_panel_layout

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


def _admin_access_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return True
        return bool(interaction.user.guild_permissions.manage_guild)

    return app_commands.check(predicate)


class FcdexCog(commands.GroupCog, group_name="fcdex"):
    """FCDex 3.1 feature directory."""

    def __init__(self, bot: BallsDexBot):
        self.bot = bot

    @app_commands.command(name="menu", description="FCDex 3.1 hub — packs, craft, battles, tournaments, and more")
    async def menu(self, interaction: discord.Interaction):
        layout = build_panel_layout(
            title="FCDex 3.1",
            subtitle="Official extra · Components v2",
            sections=[
                "### 📦 Packs\n`/pack menu` — all packs, cooldowns & claim status\n"
                "`/pack daily` (24h) · `/pack weekly` (7d) — stat rolls on each card\n"
                "-# **Exclusive Pack** — admins only via `/fcdex admin` → **Packs**",
                "### 🧪 Craft (SBC)\n`/craft menu` · `/craft complete name:<SBC>`",
                "### ⚔️ Battles\n"
                "`/battle challenge` — lineup panel\n"
                "`/battle random` — instant random 5v5\n"
                "`/battle all` — every clubball you own · `skip_commentary:true`",
                "### 🏟️ Tournaments\n`/tournament view` · `/tournament start` · `/tournament match` · `/tournament bet`",
                "### ✨ Merge · 🏅 Achievements · 📊 Rarity · 🏆 Leaderboard",
                "### 📋 List regime\n`/fcdex list regime:<name>` — browse clubballs by regime",
                "### 🛒 Shop\n`/fcdex shop` — buy bundles with coins",
                "### 👑 Boss · 📜 Quests\n`/fcdex boss` — guild raid · `/fcdex quests` · `/fcdex quest claim`",
                "### 🛡️ Admin\n`/fcdex admin` — shop, craft, quests, achievements, merge, boss, "
                "**Announce**, owners (Manage Server · ephemeral)\n"
                "`/broadcast dm` · `/broadcast server` — same broadcasts via slash (confirm · rate-limited)",
            ],
            footer="-# Configure SBCs, achievements, quests & more in `/fcdex admin` · FCDex 3.1",
        )
        await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]

    @app_commands.command(name="list", description="List clubballs in a football regime")
    @app_commands.describe(regime="Regime key or name (e.g. ucl, Premier League)")
    @app_commands.choices(
        regime=[app_commands.Choice(name=r.label, value=r.key) for r in REGIMES]
        + [app_commands.Choice(name="All regimes", value="all")]
    )
    async def list_regime(self, interaction: discord.Interaction, regime: app_commands.Choice[str]):
        if regime.value == "all":
            lines = [f"**{r.label}** (`{r.key}`) — {r.description}" for r in REGIMES]
            body = "\n".join(lines)
            layout = build_panel_layout(
                title="FCDex 3.1 · Regimes",
                subtitle="Football league groupings",
                sections=[body, "-# `/fcdex list regime:<key>` for clubballs in one regime"],
            )
            await interaction.response.send_message(view=layout, ephemeral=True)  # pyright: ignore[reportArgumentType]
            return

        entry = regime_by_key(regime.value)
        if entry is None:
            await interaction.response.send_message("Unknown regime.", ephemeral=True)
            return

        cached = {b.country.lower(): b for b in balls.values()} if balls else {}
        if not cached:
            async for b in Ball.objects.all():
                cached[b.country.lower()] = b

        found: list[str] = []
        missing: list[str] = []
        for name in entry.ball_names:
            ball = cached.get(name.lower())
            if ball:
                found.append(f"{ball.country} · spawn `{ball.rarity}` · {'✅' if ball.enabled else '🚫'}")
            else:
                missing.append(name)

        body = f"### {entry.label}\n{entry.description}\n\n" + (
            "\n".join(found) if found else "*No matches in dex cache.*"
        )
        if missing:
            body += "\n\n-# Not in cache: " + ", ".join(missing)
        layout = build_panel_layout(title=entry.label, subtitle=entry.description, sections=[body])
        await interaction.response.send_message(view=layout, ephemeral=True)  # pyright: ignore[reportArgumentType]

    @app_commands.command(
        name="admin", description="FCDex admin hub — shop, craft, quests, achievements, merge, boss, announce, owners"
    )
    @_admin_access_check()
    async def admin(self, interaction: discord.Interaction):
        if interaction.channel_id is None:
            await interaction.response.send_message("This command must be used in a channel.", ephemeral=True)
            return
        guild_id = interaction.guild_id
        layout = build_admin_hub_layout(interaction.user.id, guild_id, interaction.channel_id)
        await interaction.response.send_message(view=layout, ephemeral=True)  # pyright: ignore[reportArgumentType]

    @app_commands.command(name="boss", description="Boss raid — join, pick clubballs, track damage")
    async def boss(self, interaction: discord.Interaction):
        from fcdex_3_1.fcdex_ext.interaction_context import admin_context

        ctx = admin_context(interaction)
        layout = await build_boss_player_layout(ctx, interaction.user.id, notice="")
        await interaction.response.send_message(view=layout, ephemeral=True)  # pyright: ignore[reportArgumentType]

    @app_commands.command(name="quests", description="Daily quest progress")
    async def quests(self, interaction: discord.Interaction):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        rows = await ensure_daily_quests(player)
        labels = {spec.quest_key: spec.label for spec in await list_quest_specs(enabled_only=False)}
        lines: list[str] = []
        for row in rows:
            status = "✅ claimed" if row.claimed_at else ("🎁 ready" if row.completed_at else "⏳")
            lines.append(f"{status} **{labels.get(row.quest_key, row.quest_key)}** · `{row.progress}/{row.target}`")
        layout = build_panel_layout(
            title="FCDex 3.1 · Daily quests",
            subtitle="Resets at midnight (server time)",
            sections=["\n".join(lines), "-# `/fcdex quest claim key:<key>` when complete"],
        )
        await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]

    async def _quest_key_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        specs = await list_quest_specs(enabled_only=True)
        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for spec in specs:
            if current_lower and current_lower not in spec.quest_key and current_lower not in spec.label.lower():
                continue
            choices.append(app_commands.Choice(name=spec.label[:100], value=spec.quest_key))
        return choices[:25]

    @app_commands.command(name="quest", description="Claim a completed daily quest")
    @app_commands.describe(key="Quest key from `/fcdex quests`")
    @app_commands.autocomplete(key=_quest_key_autocomplete)
    async def quest_claim(self, interaction: discord.Interaction, key: str):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        await ensure_daily_quests(player)
        ok, message = await claim_quest(player, key.strip())
        if ok:
            layout = build_panel_layout(title="FCDex 3.1 · Quest claimed", sections=[message])
            await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="rarity", description="Live BallsDex spawn weights, rarity lookup, and clubball browse")
    @app_commands.describe(
        clubball="Look up one clubball's dex spawn weight",
        rarity="Show spawnable clubballs at this spawn weight (lower = rarer)",
        category="Browse spawnable or unspawnable clubballs",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="Spawnable (obtainable)", value="spawnable"),
            app_commands.Choice(name="Unspawnable", value="unspawnable"),
            app_commands.Choice(name="Specials", value="specials"),
        ]
    )
    async def rarity(
        self,
        interaction: discord.Interaction,
        clubball: BallEnabledTransform | None = None,
        rarity: float | None = None,
        category: app_commands.Choice[str] | None = None,
    ):
        if clubball is not None and rarity is not None:
            await interaction.response.send_message("Pick either **clubball** or **rarity**, not both.", ephemeral=True)
            return
        if clubball is not None:
            layout = await build_ball_rarity_layout(clubball)
            await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]
            return
        if rarity is not None:
            layout = await build_rarity_value_layout(rarity)
            await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]
            return
        mode = category.value if category else "overview"
        if mode not in CATEGORY_MODES and mode != "overview":
            await interaction.response.send_message("Unknown rarity category.", ephemeral=True)
            return
        layout = await build_rarity_menu(interaction.user.id, mode=mode)
        await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]

    @app_commands.command(name="leaderboard", description="Rank players by clubballs or FCDex stats")
    @app_commands.describe(
        scope="Server rankings (clubballs caught here) or global worldwide",
        sort="Metric to rank by",
        top="How many players to include",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="This server", value="server"),
            app_commands.Choice(name="Global", value="global"),
        ],
        sort=[
            app_commands.Choice(name="Clubballs", value="clubballs"),
            app_commands.Choice(name="Battles won", value="battles_won"),
            app_commands.Choice(name="Merges", value="merges"),
            app_commands.Choice(name="Tournament wins", value="tournament_wins"),
        ],
        top=[app_commands.Choice(name="Top 10", value="10"), app_commands.Choice(name="Top 20", value="20")],
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        scope: app_commands.Choice[str] | None = None,
        sort: app_commands.Choice[str] | None = None,
        top: app_commands.Choice[str] | None = None,
    ):
        in_guild = interaction.guild is not None
        in_dm = interaction.guild is None
        requested_scope = LeaderboardScope(scope.value) if scope else None
        effective_scope, scope_notice = resolve_scope(requested_scope, in_guild=in_guild, in_dm=in_dm)

        metric = LeaderboardMetric(sort.value) if sort else LeaderboardMetric.CLUBBALLS
        metric, metric_notice = normalize_metric_for_scope(metric, effective_scope)
        limit = int(top.value) if top else 10

        notices = [msg for msg in (scope_notice, metric_notice) if msg]
        if notices:
            await interaction.response.send_message("\n".join(notices), ephemeral=True)

        guild_id = interaction.guild.id if interaction.guild else None
        guild_name = interaction.guild.name if interaction.guild else None
        layout = await build_leaderboard_layout(
            interaction.client,
            interaction.user.id,
            scope=effective_scope,
            metric=metric,
            page=0,
            top=limit,
            guild_id=guild_id,
            guild_name=guild_name,
        )
        if notices:
            await interaction.followup.send(view=layout)  # pyright: ignore[reportArgumentType]
        else:
            await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]

    @app_commands.command(name="shop", description="Browse coin shop bundles and purchase rewards")
    async def shop(self, interaction: discord.Interaction):
        layout = await build_shop_layout(interaction.user.id)
        await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]
