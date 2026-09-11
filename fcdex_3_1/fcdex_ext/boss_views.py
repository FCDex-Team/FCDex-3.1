from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, View, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Ball, BallInstance, Player
from fcdex_3_1.fcdex_ext import boss_raid
from fcdex_3_1.fcdex_ext.bd_resolve import resolve_ball_input
from fcdex_3_1.fcdex_ext.boss_raid import get_raid
from fcdex_3_1.fcdex_ext.interaction_context import AdminContext, admin_context
from fcdex_3_1.fcdex_ext.views import AdminHubBackRow, truncate_text

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.boss.views")


async def _post_raid_announcement(
    interaction: Interaction, *, boss_ball: Ball, raid: boss_raid.BossRaid, scope_id: int
) -> None:
    emoji = interaction.client.get_emoji(boss_ball.emoji_id) if boss_ball.emoji_id else "👹"
    view = BossJoinView(scope_id)
    file = None
    if boss_ball.collection_card:
        try:
            ext = boss_ball.collection_card.name.split(".")[-1]
            file = discord.File(str(boss_ball.collection_card.path), filename=f"boss.{ext}")
        except Exception:
            log.warning("Could not load collection card for boss ball %s — posting without image.", boss_ball.pk)
    content = (
        f"# Boss raid — {emoji} **{boss_ball.country}**\n"
        f"-# HP: **{raid.current_hp:,}** · Join below · admins: `/fcdex admin` → Boss"
    )
    msg = await interaction.channel.send(content=content, file=file, view=view)  # type: ignore[union-attr]
    raid.announcement_message_id = msg.id
    view.message = msg


class BossJoinView(View):
    def __init__(self, scope_id: int):
        super().__init__(timeout=900)
        self.scope_id = scope_id

    @discord.ui.button(label="Join boss raid", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def join(self, interaction: Interaction, button: discord.ui.Button):
        ctx = admin_context(interaction)
        raid = get_raid(ctx.scope_id) or get_raid(self.scope_id)
        if raid is None:
            await interaction.response.send_message("This raid has ended.", ephemeral=True)
            return
        ok, message = boss_raid.join_raid(raid, interaction.user.id)
        await interaction.response.send_message(message, ephemeral=True)


class StartBossModal(Modal, title="Start boss raid"):
    hp = TextInput(label="Boss HP", placeholder="10000", max_length=12, default="10000")
    reward_clubball = TextInput(
        label="Reward clubball (optional)",
        required=False,
        placeholder="PK or country — defaults to boss clubball",
        max_length=128,
    )

    def __init__(self, owner_id: int, boss_ball: Ball):
        super().__init__()
        self.owner_id = owner_id
        self.boss_ball = boss_ball

    async def on_submit(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        ctx = admin_context(interaction)
        try:
            hp = int(self.hp.value.strip().replace(",", ""))
            if hp < 100:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("HP must be at least 100.", ephemeral=True)
            return
        reward_ball = self.boss_ball
        raw_reward = (self.reward_clubball.value or "").strip()
        if raw_reward:
            resolved = await resolve_ball_input(raw_reward)
            if resolved is None:
                await interaction.response.send_message("Reward clubball not found.", ephemeral=True)
                return
            reward_ball = resolved
        await interaction.response.defer(ephemeral=True)
        try:
            raid = boss_raid.start_raid(
                scope_id=ctx.scope_id,
                channel_id=ctx.channel_id,
                boss_ball=self.boss_ball,
                hp=hp,
                reward_ball=reward_ball if reward_ball.pk != self.boss_ball.pk else None,
                reward_server_id=ctx.reward_server_id,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        try:
            await _post_raid_announcement(interaction, boss_ball=self.boss_ball, raid=raid, scope_id=ctx.scope_id)
        except Exception:
            log.exception("Failed to post boss announcement")
        layout = await build_boss_admin_layout(ctx, self.owner_id, notice="Raid started in this channel.")
        await interaction.edit_original_response(view=layout)


class StartBossInputModal(Modal, title="Start boss by PK / name"):
    clubball = TextInput(label="Boss clubball", placeholder="PK or country name (e.g. 42)", max_length=128)
    hp = TextInput(label="Boss HP", placeholder="10000", max_length=12, default="10000")
    reward_clubball = TextInput(
        label="Reward clubball (optional)", required=False, placeholder="PK or country — winner prize", max_length=128
    )

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        boss_ball = await resolve_ball_input(self.clubball.value)
        if boss_ball is None:
            await interaction.response.send_message("Boss clubball not found.", ephemeral=True)
            return
        ctx = admin_context(interaction)
        try:
            hp = int(self.hp.value.strip().replace(",", ""))
            if hp < 100:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("HP must be at least 100.", ephemeral=True)
            return
        reward_ball: Ball | None = None
        raw_reward = (self.reward_clubball.value or "").strip()
        if raw_reward:
            reward_ball = await resolve_ball_input(raw_reward)
            if reward_ball is None:
                await interaction.response.send_message("Reward clubball not found.", ephemeral=True)
                return
        await interaction.response.defer(ephemeral=True)
        try:
            raid = boss_raid.start_raid(
                scope_id=ctx.scope_id,
                channel_id=ctx.channel_id,
                boss_ball=boss_ball,
                hp=hp,
                reward_ball=reward_ball,
                reward_server_id=ctx.reward_server_id,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        try:
            await _post_raid_announcement(interaction, boss_ball=boss_ball, raid=raid, scope_id=ctx.scope_id)
        except Exception:
            log.exception("Failed to post boss announcement")
        layout = await build_boss_admin_layout(ctx, self.owner_id, notice="Raid started in this channel.")
        await interaction.edit_original_response(view=layout)


class BossPlayerJoinRow(ActionRow):
    def __init__(self, user_id: int, ctx: AdminContext):
        super().__init__()
        self.user_id = user_id
        self.ctx = ctx

    @button(label="Join raid", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def join_btn(self, interaction: Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This panel is private to you.", ephemeral=True)
            return
        ctx = admin_context(interaction)
        raid = get_raid(ctx.scope_id)
        if raid is None:
            await interaction.response.send_message("This raid has ended.", ephemeral=True)
            return
        ok, msg = boss_raid.join_raid(raid, interaction.user.id)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        layout = await build_boss_player_layout(ctx, self.user_id, notice=msg)
        await interaction.response.edit_message(view=layout)


class BossPlayerCardSelect(discord.ui.Select):
    def __init__(self, owner_id: int, instances: list[BallInstance]):
        self.owner_id = owner_id
        options = [
            discord.SelectOption(
                label=f"#{inst.pk}",
                value=str(inst.pk),
                description=(inst.ball.country if hasattr(inst, "ball") else "?")[:100],
            )
            for inst in instances[:25]
        ]
        super().__init__(placeholder="Pick a clubball for this round…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: Interaction) -> None:
        ctx = admin_context(interaction)
        raid = get_raid(ctx.scope_id)
        if raid is None:
            await interaction.response.send_message("No active raid.", ephemeral=True)
            return
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu is private to you.", ephemeral=True)
            return
        inst = await BallInstance.objects.select_related("ball", "player").aget(pk=int(self.values[0]))
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        if inst.player_id != player.pk:
            await interaction.response.send_message("That card is not yours.", ephemeral=True)
            return
        _ok, message = await boss_raid.submit_card(raid, interaction.user.id, inst)
        layout = await build_boss_player_layout(ctx, interaction.user.id, notice=message)
        await interaction.response.edit_message(view=layout)


class BossStartBallSelect(discord.ui.Select):
    def __init__(self, owner_id: int, balls: list[Ball]):
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label=b.country[:100], value=str(b.pk), description=f"r:{b.rarity}"[:100])
            for b in balls[:25]
        ]
        super().__init__(placeholder="Choose clubball as boss…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        ball = await Ball.objects.aget(pk=int(self.values[0]))
        await interaction.response.send_modal(StartBossModal(self.owner_id, ball))


class BossAdminControls(ActionRow):
    def __init__(self, owner_id: int, ctx: AdminContext):
        super().__init__()
        self.owner_id = owner_id
        self.ctx = ctx

    @button(label="Start round", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def start_round(self, interaction: Interaction, button: Button):
        await self._start_round(interaction)

    @button(label="Resolve", style=discord.ButtonStyle.primary, emoji="✅")
    async def resolve(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        raid = get_raid(ctx.scope_id)
        if raid is None:
            await interaction.response.send_message("No active raid.", ephemeral=True)
            return
        log_text = await boss_raid.resolve_round(raid)
        layout = await build_boss_admin_layout(ctx, self.owner_id, notice=log_text)
        await interaction.response.edit_message(view=layout)

    @button(label="Conclude", style=discord.ButtonStyle.success, emoji="🏁")
    async def conclude(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        raid = get_raid(ctx.scope_id)
        if raid is None:
            await interaction.response.send_message("No active raid.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        result = await boss_raid.conclude_raid(raid, grant_reward=True)
        notice = result.admin_summary
        if result.announce_publicly:
            try:
                channel = await interaction.client.fetch_channel(result.channel_id)
                await channel.send(result.public_message)
                notice += f"\n\n📢 **Announced** results in <#{result.channel_id}>."
            except Exception:
                log.exception("Failed to post boss raid results to channel %s", result.channel_id)
                notice += f"\n\n⚠️ Could not post results to <#{result.channel_id}> — check bot permissions."
        else:
            notice += "\n\n-# DM raids: results stay in this panel only (no public channel)."
        layout = await build_boss_admin_layout(ctx, self.owner_id, notice=notice)
        await interaction.edit_original_response(view=layout)

    async def _start_round(self, interaction: Interaction) -> None:
        ctx = admin_context(interaction)
        raid = get_raid(ctx.scope_id)
        if raid is None:
            await interaction.response.send_message("No active raid.", ephemeral=True)
            return
        ok, message = boss_raid.begin_round(raid)
        if ok:
            message += f"\n-# **{len(raid.participants)}** joined — players lock cards in `/fcdex boss`."
        layout = await build_boss_admin_layout(ctx, self.owner_id, notice=message)
        await interaction.response.edit_message(view=layout)


class BossStartByInputRow(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="Start by PK / name", style=discord.ButtonStyle.success, emoji="📝")
    async def start_input(self, interaction: Interaction, button: Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        await interaction.response.send_modal(StartBossInputModal(self.owner_id))


async def build_boss_player_layout(ctx: AdminContext, user_id: int, *, notice: str = "") -> LayoutView:
    raid = get_raid(ctx.scope_id)
    layout = LayoutView(timeout=300)
    container = Container()

    if raid is None:
        scope_hint = "this server" if ctx.guild_id else "this DM"
        container.add_item(TextDisplay(f"# 👑 Boss raid\n*No active raid in {scope_hint}.*"))
        layout.add_item(container)
        return layout

    boss = await Ball.objects.aget(pk=raid.boss_ball_id)
    participant = raid.participants.get(user_id)
    joined = len(raid.participants)
    header = (
        f"# 👑 {boss.country}\n"
        f"HP **{raid.current_hp:,}** / **{raid.max_hp:,}** · "
        f"Round **{raid.round}/{boss_raid.MAX_ROUNDS}** · phase `{raid.phase}` · **{joined}** joined"
    )
    if notice:
        header += f"\n\n{notice}"
    if participant:
        header += f"\n\nYour damage: **{participant.total_damage:,}**"
        if participant.disqualified:
            header += "\n\n🚫 **Knocked out** — your clubball couldn't survive the boss counter-attack."
        elif participant.round_boss_damage > 0 and raid.phase == "resolve":
            header += f"\n\nLast boss hit: **{participant.round_boss_damage:,}**"
    if raid.phase == "pick" and participant and participant.selected_instance_id is not None:
        header += f"\n\n-# Locked card `#{participant.selected_instance_id}` — boss counter-attacks on **Resolve**."
    elif raid.phase == "pick" and participant and not participant.disqualified:
        header += "\n\n-# Pick a strong clubball — boss counter-attacks locked cards each round."
    container.add_item(TextDisplay(truncate_text(header)))

    if raid.phase == "join":
        container.add_item(Separator())
        container.add_item(BossPlayerJoinRow(user_id, ctx))
        container.add_item(TextDisplay("-# Or tap **Join** on the raid announcement message."))
    elif raid.phase == "pick" and participant and not participant.disqualified:
        player = await Player.objects.filter(discord_id=user_id).afirst()
        if player and participant.selected_instance_id is None:
            instances = [
                i
                async for i in BallInstance.objects.filter(player=player, deleted=False)
                .select_related("ball", "player")
                .order_by("-pk")[:25]
                if i.pk not in raid.used_instance_ids
            ]
            if instances:
                container.add_item(Separator())
                row = ActionRow()
                row.add_item(BossPlayerCardSelect(user_id, instances))
                container.add_item(row)

    layout.add_item(container)
    return layout


async def build_boss_admin_layout(ctx: AdminContext, owner_id: int, *, notice: str = "") -> LayoutView:
    raid = get_raid(ctx.scope_id)
    layout = LayoutView(timeout=600)
    container = Container()

    if raid is None:
        scope_hint = "this server" if ctx.guild_id else "this DM"
        body = (
            f"*No raid in {scope_hint} — pick a boss below or use **Start by PK / name** "
            "(clubball PK, country, optional reward collectible).*"
        )
    else:
        boss = await Ball.objects.aget(pk=raid.boss_ball_id)
        reward = await Ball.objects.aget(pk=raid.reward_ball_id_effective)
        reward_line = f"\n-# Fight reward: **{reward.country}**"
        body = (
            f"**{boss.country}** · HP **{raid.current_hp:,}** / **{raid.max_hp:,}**{reward_line}\n"
            f"Round **{raid.round}/{boss_raid.MAX_ROUNDS}** · phase `{raid.phase}` · "
            f"**{len(raid.participants)}** joined · **{len(raid.alive_participant_ids)}** active\n\n"
            f"{boss_raid.standings(raid)}"
        )
    if notice:
        body = f"{notice}\n\n{body}"

    container.add_item(
        TextDisplay(
            truncate_text(
                "# 👑 Boss admin\n"
                "-# Works in servers and DMs · Components v2.\n"
                "-# Set boss + optional **reward clubball** · **Start round** → pick in `/fcdex boss` "
                "→ **Resolve** → **Conclude**.\n"
                "-# **Conclude** grants the reward and posts results in the raid channel (server raids only).\n"
                "-# Boss counter-attacks locked clubballs each round — knocked-out players can't fight on.\n"
                "-# Needs **Boss** special for tagged wins."
            )
        )
    )
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(body)))
    if raid is not None:
        container.add_item(Separator())
        container.add_item(BossAdminControls(owner_id, ctx))
    else:
        balls = [b async for b in Ball.objects.filter(enabled=True).order_by("country")[:25]]
        container.add_item(Separator())
        container.add_item(BossStartByInputRow(owner_id))
        if balls:
            row = ActionRow()
            row.add_item(BossStartBallSelect(owner_id, balls))
            container.add_item(row)
    container.add_item(Separator())
    container.add_item(AdminHubBackRow(owner_id))
    layout.add_item(container)
    return layout
