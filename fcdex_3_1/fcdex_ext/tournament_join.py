"""Join or leave a tournament straight from its public announcement, no slash command needed."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import discord
from discord.ui import ActionRow, Button, DynamicItem, Separator, TextDisplay

from ballsdex.core.discord import Container, LayoutView
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.services import decrement_stat, increment_stat
from fcdex_3_1.fcdex_ext.tournament_schedule import (
    registration_closed_reason,
    registration_is_open,
    registration_status_label,
    schedule_summary_lines,
)
from fcdex_3_1.fcdex_ext.views import truncate_text
from fcdex_3_1.models import Tournament, TournamentRegistration

log = logging.getLogger("fcdex_3_1.tournament.join")

BUTTON_ID_PREFIX = "fcdex:tournament"
BUTTON_TEMPLATE = rf"{BUTTON_ID_PREFIX}:(?P<tournament_id>[0-9]+):(?P<action>legacy|main|leave|hub)"

# action -> (label, emoji, style)
ACTIONS: dict[str, tuple[str, str, discord.ButtonStyle]] = {
    "legacy": ("Join Legacy", "\N{SHIELD}\N{VARIATION SELECTOR-16}", discord.ButtonStyle.primary),
    "main": ("Join Main", "\N{CROSSED SWORDS}\N{VARIATION SELECTOR-16}", discord.ButtonStyle.primary),
    "leave": ("Leave", "\N{DOOR}", discord.ButtonStyle.secondary),
    "hub": ("Details", "\N{STADIUM}\N{VARIATION SELECTOR-16}", discord.ButtonStyle.secondary),
}


@dataclass(frozen=True, slots=True)
class JoinOutcome:
    ok: bool
    message: str


async def join_tournament(player: Player, tournament: Tournament, group: str) -> JoinOutcome:
    """Register `player` in `group`. Shared by the hub menu and the announcement buttons."""
    if reason := registration_closed_reason(tournament):
        return JoinOutcome(False, reason)

    # Register first (the unique (tournament, player) constraint is the real lock), then check the cap. Two
    # concurrent joins can no longer both slip past a pre-check and both get seated once the cap is reached.
    registration, created = await TournamentRegistration.objects.aget_or_create(
        tournament=tournament, player=player, defaults={"group": group}
    )
    if not created:
        return JoinOutcome(False, f"You're already in the **{registration.get_group_display()}** group.")

    if tournament.max_participants:
        total = await TournamentRegistration.objects.filter(tournament=tournament).acount()
        if total > tournament.max_participants:
            await registration.adelete()
            return JoinOutcome(False, f"❌ This tournament is full (**{tournament.max_participants}** player slots).")

    await increment_stat(player, "tournament_participations")
    return JoinOutcome(True, f"✅ Joined **{group.title()}** group!")


async def leave_tournament(player: Player, tournament: Tournament) -> JoinOutcome:
    if not registration_is_open(tournament):
        return JoinOutcome(
            False, "You can only leave while **registration** is still open (before the host starts group stage)."
        )
    deleted, _ = await TournamentRegistration.objects.filter(tournament=tournament, player=player).adelete()
    if not deleted:
        return JoinOutcome(False, "You aren't registered in this tournament.")
    # joining counted a participation, so leaving takes it back (no farming achievements by rejoining)
    await decrement_stat(player, "tournament_participations")
    return JoinOutcome(True, "You left the tournament. Pick **Legacy** or **Main** to rejoin.")


class TournamentActionButton(DynamicItem[Button], template=BUTTON_TEMPLATE):
    """A persistent button on a tournament announcement. The custom id carries the tournament and the action,
    so it keeps working after restarts and long after the announcement view itself is gone."""

    def __init__(self, tournament_id: int, action: str):
        label, emoji, style = ACTIONS[action]
        super().__init__(
            Button(label=label, emoji=emoji, style=style, custom_id=f"{BUTTON_ID_PREFIX}:{tournament_id}:{action}")
        )
        self.tournament_id = tournament_id
        self.action = action

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str], /):
        return cls(int(match["tournament_id"]), match["action"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await interaction.client.blacklist_check(interaction)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            tournament = await Tournament.objects.aget(pk=self.tournament_id)
        except Tournament.DoesNotExist:
            await interaction.response.send_message("This tournament no longer exists.", ephemeral=True)
            return

        if self.action == "hub":
            from fcdex_3_1.fcdex_ext.tournament_player_views import build_tournament_player_menu

            layout = await build_tournament_player_menu(interaction.user.id, tournament.pk, mode="overview")
            await interaction.response.send_message(view=layout, ephemeral=True)
            return

        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        if self.action == "leave":
            outcome = await leave_tournament(player, tournament)
        else:
            outcome = await join_tournament(player, tournament, self.action)
        await interaction.response.send_message(outcome.message, ephemeral=True)


class TournamentAnnouncementRow(ActionRow):
    def __init__(self, tournament_id: int):
        super().__init__()
        for action in ACTIONS:
            self.add_item(TournamentActionButton(tournament_id, action))


async def build_announcement_layout(tournament: Tournament, host_discord_id: int) -> LayoutView:
    """The public signup post. It never times out: the buttons are persistent dynamic items."""
    cap_text = "unlimited" if not tournament.max_participants else f"{tournament.max_participants:,}"
    schedule_lines = schedule_summary_lines(tournament)
    details = (
        f"**Status:** {tournament.get_status_display()}\n"
        f"**Registration:** {registration_status_label(tournament)}\n"
        f"**Host:** <@{host_discord_id}>\n"
        f"**Max participants:** {cap_text}\n"
        f"**Semifinal cutoff:** {tournament.semifinal_cutoff} points\n"
        f"**Betting:** {'enabled' if tournament.betting_enabled else 'disabled'}\n"
        + ("\n".join(schedule_lines) + "\n" if schedule_lines else "")
        + f"\n{tournament.description or 'No description provided.'}"
    )
    layout = LayoutView(timeout=None)
    container = Container()
    container.add_item(TextDisplay(truncate_text(f"# 🏟️ {tournament.name}")))
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(details)))
    container.add_item(Separator())
    container.add_item(
        TextDisplay(
            "### Join with one tap\n"
            "Pick **Join Legacy** or **Join Main** below. **Leave** works while registration is open, "
            "**Details** shows standings and the bracket.\n"
            "-# Prefer commands? `/tournament view` · `/tournament match` · `/tournament bet`"
        )
    )
    container.add_item(TournamentAnnouncementRow(tournament.pk))
    layout.add_item(container)
    return layout
