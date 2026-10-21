"""`/fc derby ...`: build a squad in a formation and play derbies for coins and Club Pass XP.

Discord shape: a top-level `fc` group with a `derby` subgroup, so the commands are `/fc derby add`, `/fc derby layouts`,
`/fc derby show`, `/fc derby status`, `/fc derby challenge` and `/fc derby remove`.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ballsdex.core.utils.transformers import BallInstanceTransform
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.bd_helpers import get_ball
from fcdex_3_1.fcdex_ext.currency import format_money
from fcdex_3_1.fcdex_ext.derby_logic import (
    ActiveDerbies,
    DerbyRewards,
    LayoutPicker,
    check_add,
    daily_limit_message,
    daily_limit_reached,
    derby_highlights,
    format_missing,
    get_formation,
    is_complete,
    roll_rewards,
    validate_challenge,
    winner_side,
)
from fcdex_3_1.fcdex_ext.derby_pass_bridge import UNAVAILABLE, PassXpOutcome, club_pass_status, grant_derby_xp
from fcdex_3_1.fcdex_ext.derby_service import (
    claim_derby,
    clear_slot,
    derbies_used_today,
    get_derby_ranges,
    get_formation_key,
    load_slots,
    place_clubball,
    record_draw,
    record_result,
)
from fcdex_3_1.fcdex_ext.derby_views import (
    DerbyChallengeView,
    build_layouts_panel,
    build_result_layout,
    build_show_panel,
    build_status_panel,
    closed_view,
)
from settings.models import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("fcdex_3_1.derby")

POSITION_CHOICES = [
    app_commands.Choice(name="Goalkeeper (GK)", value="GK"),
    app_commands.Choice(name="Defender (DF)", value="DF"),
    app_commands.Choice(name="Midfielder (MF)", value="MF"),
    app_commands.Choice(name="Striker (ST)", value="ST"),
]


@dataclass(frozen=True, slots=True)
class _SideReport:
    member: discord.Member
    won: bool
    rewards: DerbyRewards
    coins_paid: int
    xp: PassXpOutcome


class DerbyCog(commands.Cog):
    """FC Derby."""

    fc = app_commands.Group(name="fc", description="FC commands")
    derby = app_commands.Group(name="derby", description="Build a derby squad and play for coins and XP", parent=fc)

    def __init__(self, bot: BallsDexBot):
        self.bot = bot
        self._active = ActiveDerbies()

    def release(self, *discord_ids: int) -> None:
        self._active.finish(*discord_ids)

    # -- squad ----------------------------------------------------------------------------------------------------

    @derby.command(name="add", description="Put one of your clubballs into a slot of your derby formation")
    @app_commands.describe(
        position="Where to play it", clubball="The clubball to add", slot="Slot number to replace (default: first free)"
    )
    @app_commands.choices(position=POSITION_CHOICES)
    async def add(
        self,
        interaction: discord.Interaction,
        position: app_commands.Choice[str],
        clubball: BallInstanceTransform,
        slot: app_commands.Range[int, 1, 5] | None = None,
    ):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        if clubball.deleted or clubball.player_id != player.pk:
            await interaction.response.send_message(
                f"That {settings.collectible_name} isn't yours to add.", ephemeral=True
            )
            return

        formation = get_formation(await get_formation_key(player))
        rows = await load_slots(player)
        squad = {(row.position, row.slot): row.ball_id for row in rows}
        ball = await get_ball(clubball)
        verdict = check_add(formation, squad, position.value, ball.pk, slot=slot)
        if not verdict.ok:
            await interaction.response.send_message(verdict.reason, ephemeral=True)
            return
        if not await place_clubball(player, position.value, verdict.slot, clubball, ball):
            await interaction.response.send_message("That club is already in your squad.", ephemeral=True)
            return

        size = len(squad) + (0 if verdict.replaces else 1)
        verb = "Replaced" if verdict.replaces else "Added"
        await interaction.response.send_message(
            f"{verb} **{ball.country}** at **{position.value}{verdict.slot + 1}** "
            f"({formation.key}, {size}/{formation.total} slots filled).",
            ephemeral=True,
        )

    @derby.command(name="remove", description="Take a clubball out of a slot of your derby formation")
    @app_commands.describe(position="Position of the slot", slot="Slot number")
    @app_commands.choices(position=POSITION_CHOICES)
    async def remove(
        self, interaction: discord.Interaction, position: app_commands.Choice[str], slot: app_commands.Range[int, 1, 5]
    ):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        if await clear_slot(player, position.value, slot - 1):
            await interaction.response.send_message(f"Cleared **{position.value}{slot}**.", ephemeral=True)
        else:
            await interaction.response.send_message(f"**{position.value}{slot}** is already empty.", ephemeral=True)

    @derby.command(name="layouts", description="Browse formations and pick the one your derby squad plays in")
    async def layouts(self, interaction: discord.Interaction):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        picker = LayoutPicker.starting_at(await get_formation_key(player))
        await interaction.response.defer(ephemeral=True)
        layout, file = await build_layouts_panel(interaction.user.id, picker)
        await interaction.followup.send(view=layout, file=file, ephemeral=True)  # pyright: ignore[reportArgumentType]

    @derby.command(name="show", description="Show your derby squad on the pitch")
    async def show(self, interaction: discord.Interaction):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        await interaction.response.defer()
        layout, file = await build_show_panel(player, owner_name=interaction.user.display_name)
        await interaction.followup.send(view=layout, file=file)  # pyright: ignore[reportArgumentType]

    async def _milestone_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        status = await club_pass_status(player)
        needle = current.lower()
        choices = [
            app_commands.Choice(name=f"Level {m.level} · {m.label}"[:100], value=str(m.level))
            for m in status.milestones
            if not needle or needle in m.label.lower() or needle in str(m.level)
        ]
        return choices[:25]

    @derby.command(name="status", description="Your derby record and Club Pass level")
    @app_commands.describe(milestone="Look at one upcoming Club Pass reward level (when the Club Pass is available)")
    @app_commands.autocomplete(milestone=_milestone_autocomplete)
    async def status(self, interaction: discord.Interaction, milestone: str | None = None):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        selected = int(milestone) if milestone and milestone.strip().isdigit() else None
        layout = await build_status_panel(player, milestone=selected)
        await interaction.response.send_message(view=layout, ephemeral=True)  # pyright: ignore[reportArgumentType]

    # -- challenge ------------------------------------------------------------------------------------------------

    async def _readiness_problem(
        self, member: discord.Member | discord.User, player: Player, *, you: bool
    ) -> str | None:
        subject, verb = ("Your", "You've") if you else (f"{member.display_name}'s", f"{member.display_name} has")
        formation = get_formation(await get_formation_key(player))
        squad = {(row.position, row.slot): row.ball_id for row in await load_slots(player)}
        if not is_complete(formation, squad):
            return (
                f"{subject} derby squad isn't complete (empty: {format_missing(formation, squad)}). "
                f"Fill every slot with `/fc derby add`."
            )
        config = await get_derby_ranges()
        if daily_limit_reached(await derbies_used_today(player), config.daily_limit):
            from django.utils import timezone

            return daily_limit_message(timezone.now(), limit=config.daily_limit, who=verb)
        return None

    @derby.command(name="challenge", description="Challenge a player to a derby for coins and Club Pass XP")
    @app_commands.describe(challenger="The player to play against")
    async def challenge(self, interaction: discord.Interaction, challenger: discord.Member):
        # The option is named for the user's `/fc derby [Challenger]` wording, it is the player being challenged.
        author = interaction.user
        if not isinstance(author, discord.Member):
            await interaction.response.send_message("Derbies can only be played in a server.", ephemeral=True)
            return
        if problem := validate_challenge(author.id, challenger.id, opponent_is_bot=challenger.bot):
            await interaction.response.send_message(problem, ephemeral=True)
            return
        if self._active.busy(author.id, challenger.id):
            await interaction.response.send_message("One of you is already in a derby.", ephemeral=True)
            return

        mine, _ = await Player.objects.aget_or_create(discord_id=author.id)
        theirs, _ = await Player.objects.aget_or_create(discord_id=challenger.id)
        for member, player, you in ((author, mine, True), (challenger, theirs, False)):
            if problem := await self._readiness_problem(member, player, you=you):
                await interaction.response.send_message(problem, ephemeral=True)
                return

        if not self._active.start(author.id, challenger.id):
            await interaction.response.send_message("One of you is already in a derby.", ephemeral=True)
            return
        view = DerbyChallengeView(self, author, challenger)
        try:
            await interaction.response.send_message(view=view)  # pyright: ignore[reportArgumentType]
            view.message = await interaction.original_response()  # pyright: ignore[reportAttributeAccessIssue]
        except discord.HTTPException:
            self.release(author.id, challenger.id)
            raise

    async def play(
        self, interaction: discord.Interaction, challenger: discord.Member, opponent: discord.Member
    ) -> None:
        """Run an accepted derby. Called from the Accept button, which has already deferred."""
        ids = (challenger.id, opponent.id)
        try:
            await self._play(interaction, challenger, opponent)
        except Exception:
            log.exception("Derby between %s and %s failed", *ids)
            await self._edit(interaction, "Something went wrong with this derby. No result was recorded.")
        finally:
            self.release(*ids)

    async def _edit(self, interaction: discord.Interaction, text: str) -> None:
        if interaction.message:
            await interaction.message.edit(view=closed_view(text), attachments=[])

    async def _play(self, interaction: discord.Interaction, challenger: discord.Member, opponent: discord.Member):
        from django.utils import timezone

        from fcdex_3_1.fcdex_ext.battle_cog import ball_instance_to_battle_ball
        from fcdex_3_1.fcdex_ext.battle_engine import BattleInstance, gen_battle

        first, _ = await Player.objects.aget_or_create(discord_id=challenger.id)
        second, _ = await Player.objects.aget_or_create(discord_id=opponent.id)

        # Squads may have changed while the challenge waited.
        for member, player in ((challenger, first), (opponent, second)):
            problem = await self._squad_problem(member, player)
            if problem:
                await self._edit(interaction, problem)
                return

        ranges = await get_derby_ranges()
        blocked = await claim_derby([first, second], limit=ranges.daily_limit)
        if blocked is not None:
            who = challenger if blocked.pk == first.pk else opponent
            await self._edit(
                interaction,
                daily_limit_message(timezone.now(), limit=ranges.daily_limit, who=f"**{who.display_name}** has"),
            )
            return

        decks = []
        for member, player in ((challenger, first), (opponent, second)):
            formation = get_formation(await get_formation_key(player))
            rows = {(row.position, row.slot): row for row in await load_slots(player)}
            deck = [
                await ball_instance_to_battle_ball(rows[key].instance, member.display_name, self.bot)
                for key in formation.slot_keys()
                if key in rows
            ]
            decks.append(deck)
        match = BattleInstance(p1_balls=decks[0], p2_balls=decks[1])
        log_lines = list(gen_battle(match))

        side = winner_side(sum(1 for b in match.p1_balls if not b.dead), sum(1 for b in match.p2_balls if not b.dead))
        reports: list[_SideReport] = []
        pairs = ((challenger, first, 1), (opponent, second, 2))
        for member, player, number in pairs:
            won = side == number
            rewards = roll_rewards(ranges, won=won) if side is not None else DerbyRewards(coins=0, xp=ranges.loser_xp)
            reports.append(await self._pay(member, player, won=won, rewards=rewards))

        if side == 1:
            await record_result(first, second)
        elif side == 2:
            await record_result(second, first)
        else:
            await record_draw(first, second)

        layout = build_result_layout(
            challenger,
            opponent,
            winner=(challenger, opponent)[side - 1] if side else None,
            highlights=derby_highlights(log_lines),
            reports=[self._report_line(r) for r in reports],
            turns=match.turns,
        )
        file = discord.File(io.BytesIO("\n".join(log_lines).encode()), filename="derby-commentary.txt")
        if interaction.message:
            await interaction.message.edit(view=layout, attachments=[file])

    async def _squad_problem(self, member: discord.Member, player: Player) -> str | None:
        formation = get_formation(await get_formation_key(player))
        squad = {(row.position, row.slot): row.ball_id for row in await load_slots(player)}
        if is_complete(formation, squad):
            return None
        return f"**{member.display_name}**'s squad is no longer complete, the derby was called off."

    async def _pay(self, member: discord.Member, player: Player, *, won: bool, rewards: DerbyRewards) -> _SideReport:
        paid = 0
        if rewards.coins > 0:
            try:
                await player.add_money(rewards.coins)
                paid = rewards.coins
            except Exception:
                log.exception("Derby coins failed for player %s", player.pk)
        xp = await grant_derby_xp(player, rewards.xp) if rewards.xp > 0 else PassXpOutcome(available=True)
        return _SideReport(member=member, won=won, rewards=rewards, coins_paid=paid, xp=xp)

    def _report_line(self, report: _SideReport) -> str:
        parts = []
        if report.coins_paid > 0:
            parts.append(f"+{format_money(report.coins_paid, self.bot)}")
        if report.xp.available:
            parts.append(report.xp.text)
        else:
            parts.append(f"+{report.rewards.xp} XP ({UNAVAILABLE})")
        tag = "\N{TROPHY} Winner" if report.won else "Played"
        return f"**{report.member.display_name}** · {tag} · " + " · ".join(parts)
