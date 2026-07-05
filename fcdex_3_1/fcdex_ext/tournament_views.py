from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, cast

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.tournament_schedule import (
    format_for_input,
    parse_optional_datetime,
    parse_status,
    schedule_summary_lines,
)
from fcdex_3_1.fcdex_ext.views import build_tournament_layout, truncate_text
from fcdex_3_1.models import Tournament, TournamentGroup, TournamentStatus

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.tournament.views")

ManageMode = Literal["edit", "delete", "announce", "host", "settings"]


async def load_manageable_tournaments() -> list[Tournament]:
    return [t async for t in Tournament.objects.all().order_by("-created_at")[:25]]


async def load_active_tournaments() -> list[Tournament]:
    return [t async for t in Tournament.objects.exclude(status=TournamentStatus.COMPLETED).order_by("-created_at")[:25]]


def _owner_mismatch(interaction: Interaction, owner_id: int) -> bool:
    return interaction.user.id != owner_id


async def _deny_owner(interaction: Interaction) -> None:
    await interaction.response.send_message(
        "Only the admin who opened this panel can use these controls.", ephemeral=True
    )


def _require_manage_guild(interaction: Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return bool(interaction.user.guild_permissions.manage_guild)


async def _deny_manage_guild(interaction: Interaction) -> None:
    await interaction.response.send_message("You need **Manage Server** to run host actions.", ephemeral=True)


class TournamentManageView(LayoutView):
    def __init__(self, owner_id: int, *, notice: str = ""):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.notice = notice
        self._build()

    def _build(self) -> None:
        self.clear_items()
        container = Container()
        body = (
            "# 🏟️ Tournament admin panel\n"
            "-# Private · only you can see this\n\n"
            "▸ **Create** — full tournament setup\n"
            "▸ **Edit** — description, schedule, cutoff, status\n"
            "▸ **Settings** — max participants, betting, rules\n"
            "▸ **Host** — start group stage or advance rounds\n"
            "▸ **Bounty vault** — loot pools, rules, and betting\n"
            "▸ **Rewards** — participation prizes for match participants\n"
            "▸ **Delete** — permanently remove a tournament\n"
            "▸ **Announce** — public signup post in this channel"
        )
        if self.notice:
            body = f"{self.notice}\n\n{body}"
        container.add_item(TextDisplay(truncate_text(body)))
        container.add_item(Separator())
        container.add_item(TournamentManageControls(self.owner_id))
        container.add_item(TournamentManageExtraRow(self.owner_id))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        return True


class TournamentManageControls(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="Create", style=discord.ButtonStyle.success, emoji="➕")
    async def create_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        await interaction.response.send_modal(TournamentCreateModal(self.owner_id))

    @button(label="Edit", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        tournaments = await load_manageable_tournaments()
        if not tournaments:
            await interaction.response.send_message("No tournaments exist yet.", ephemeral=True)
            return
        view = TournamentPickView(self.owner_id, cast(ManageMode, "edit"), tournaments)
        await interaction.response.edit_message(view=view)

    @button(label="Host", style=discord.ButtonStyle.primary, emoji="🎮")
    async def host_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        tournaments = await load_active_tournaments()
        if not tournaments:
            await interaction.response.send_message("No active tournaments to host.", ephemeral=True)
            return
        view = TournamentPickView(self.owner_id, cast(ManageMode, "host"), tournaments)
        await interaction.response.edit_message(view=view)

    @button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        tournaments = await load_manageable_tournaments()
        if not tournaments:
            await interaction.response.send_message("No tournaments exist yet.", ephemeral=True)
            return
        view = TournamentPickView(self.owner_id, cast(ManageMode, "delete"), tournaments)
        await interaction.response.edit_message(view=view)

    @button(label="Announce", style=discord.ButtonStyle.secondary, emoji="📢")
    async def announce_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        tournaments = await load_active_tournaments()
        if not tournaments:
            await interaction.response.send_message("No active tournaments to announce.", ephemeral=True)
            return
        view = TournamentPickView(self.owner_id, cast(ManageMode, "announce"), tournaments)
        await interaction.response.edit_message(view=view)


class TournamentManageExtraRow(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="Settings", style=discord.ButtonStyle.primary, emoji="⚙️")
    async def settings_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        tournaments = await load_manageable_tournaments()
        if not tournaments:
            await interaction.response.send_message("No tournaments exist yet.", ephemeral=True)
            return
        view = TournamentPickView(self.owner_id, cast(ManageMode, "settings"), tournaments)
        await interaction.response.edit_message(view=view)

    @button(label="Bounty vault", style=discord.ButtonStyle.secondary, emoji="🎁")
    async def bounty_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        if not _require_manage_guild(interaction):
            await _deny_manage_guild(interaction)
            return
        from fcdex_3_1.fcdex_ext.tournament_bounty_views import build_bounty_pick_view

        view = await build_bounty_pick_view(self.owner_id)
        await interaction.response.edit_message(view=view)

    @button(label="Rewards", style=discord.ButtonStyle.secondary, emoji="🎖️")
    async def rewards_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        if not _require_manage_guild(interaction):
            await _deny_manage_guild(interaction)
            return
        from fcdex_3_1.fcdex_ext.tournament_rewards_views import build_rewards_pick_view

        view = await build_rewards_pick_view(self.owner_id)
        await interaction.response.edit_message(view=view)


class TournamentPickView(LayoutView):
    def __init__(self, owner_id: int, mode: ManageMode, tournaments: list[Tournament]):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.mode: ManageMode = mode
        self.tournaments = tournaments
        self._build()

    def _build(self) -> None:
        self.clear_items()
        container = Container()
        titles = {
            "edit": "✏️ Edit tournament",
            "delete": "🗑️ Delete tournament",
            "announce": "📢 Post announcement",
            "host": "🎮 Host controls",
            "settings": "⚙️ Tournament settings",
        }
        container.add_item(TextDisplay(f"# {titles[self.mode]}\n-# Select a tournament below"))
        container.add_item(Separator())
        container.add_item(TournamentSelectRow(self.owner_id, self.mode, self.tournaments))
        container.add_item(TournamentBackRow(self.owner_id))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        return True


class TournamentSelectRow(ActionRow):
    def __init__(self, owner_id: int, mode: ManageMode, tournaments: list[Tournament]):
        super().__init__()
        self.owner_id = owner_id
        self.mode: ManageMode = mode
        options = [
            discord.SelectOption(label=t.name[:100], value=str(t.pk), description=f"{t.get_status_display()}"[:100])
            for t in tournaments[:25]
        ]
        self.add_item(
            TournamentSelect(owner_id=owner_id, mode=mode, options=options, placeholder="Choose a tournament…")
        )


class TournamentSelect(discord.ui.Select):
    def __init__(self, *, owner_id: int, mode: ManageMode, options: list[discord.SelectOption], placeholder: str):
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)
        self.owner_id = owner_id
        self.mode: ManageMode = mode

    async def callback(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return

        tournament = await Tournament.objects.aget(pk=int(self.values[0]))

        if self.mode == "edit":
            await interaction.response.send_modal(TournamentEditModal(self.owner_id, tournament))
            return

        if self.mode == "settings":
            await interaction.response.send_modal(TournamentSettingsModal(self.owner_id, tournament))
            return

        if self.mode == "delete":
            view = TournamentDeleteConfirmView(self.owner_id, tournament.pk, tournament.name)
            await interaction.response.edit_message(view=view)
            return

        if self.mode == "host":
            view = TournamentHostView(self.owner_id, tournament.pk, tournament.name, tournament.status)
            await interaction.response.edit_message(view=view)
            return

        if self.mode == "announce":
            if not interaction.guild or interaction.channel is None:
                await interaction.response.send_message(
                    "Announcements can only be posted in a server channel.", ephemeral=True
                )
                return
            await post_tournament_announcement(interaction, tournament)
            view = TournamentManageView(self.owner_id, notice=f"📢 Posted announcement for **{tournament.name}**.")
            await interaction.response.edit_message(view=view)
            return


class TournamentBackRow(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        await interaction.response.edit_message(view=TournamentManageView(self.owner_id))


class TournamentDeleteConfirmView(LayoutView):
    def __init__(self, owner_id: int, tournament_id: int, tournament_name: str):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self.tournament_name = tournament_name
        self._build()

    def _build(self) -> None:
        self.clear_items()
        container = Container()
        container.add_item(
            TextDisplay(
                f"# ⚠️ Delete tournament?\n"
                f"**{self.tournament_name}** will be permanently removed, including registrations and matches."
            )
        )
        container.add_item(TournamentDeleteControls(self.owner_id, self.tournament_id))
        container.add_item(TournamentBackRow(self.owner_id))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        return True


class TournamentDeleteControls(ActionRow):
    def __init__(self, owner_id: int, tournament_id: int):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    @button(label="Confirm delete", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        name = tournament.name
        await tournament.adelete()
        view = TournamentManageView(self.owner_id, notice=f"🗑️ Deleted **{name}**.")
        await interaction.response.edit_message(view=view)

    @button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        await interaction.response.edit_message(view=TournamentManageView(self.owner_id))


class TournamentCreateModal(Modal, title="Create tournament"):
    name = TextInput(label="Name", max_length=64, required=True)
    description = TextInput(label="Description", style=discord.TextStyle.paragraph, required=False, max_length=2000)
    semifinal_cutoff = TextInput(label="Semifinal cutoff (points)", default="0", required=False, max_length=4)
    starts_at = TextInput(
        label="Scheduled start", required=False, placeholder="YYYY-MM-DD or YYYY-MM-DD HH:MM", max_length=32
    )
    ends_at = TextInput(
        label="Scheduled end", required=False, placeholder="YYYY-MM-DD or YYYY-MM-DD HH:MM", max_length=32
    )

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await interaction.response.send_message(
                "Only the admin who opened this panel can submit this form.", ephemeral=True
            )
            return

        name = self.name.value.strip()
        if await Tournament.objects.filter(name__iexact=name).aexists():
            await interaction.response.send_message("A tournament with that name already exists.", ephemeral=True)
            return

        try:
            semifinal_cutoff = int(self.semifinal_cutoff.value.strip() or "0")
            if semifinal_cutoff < 0:
                raise ValueError
            scheduled_start = parse_optional_datetime(self.starts_at.value)
            scheduled_end = parse_optional_datetime(self.ends_at.value)
        except ValueError as exc:
            message = str(exc) if str(exc) else "Semifinal cutoff must be a non-negative number."
            await interaction.response.send_message(message, ephemeral=True)
            return

        if scheduled_start and scheduled_end and scheduled_start >= scheduled_end:
            await interaction.response.send_message("Scheduled start must be before scheduled end.", ephemeral=True)
            return

        host, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        tournament = await Tournament.objects.acreate(
            name=name,
            description=self.description.value or "",
            host=host,
            semifinal_cutoff=semifinal_cutoff,
            scheduled_start_at=scheduled_start,
            scheduled_end_at=scheduled_end,
        )

        view = TournamentManageView(
            self.owner_id, notice=f"✅ Created **{tournament.name}**. Use **Announce** to post a public signup message."
        )
        await interaction.response.edit_message(view=view)


class TournamentEditModal(Modal, title="Edit tournament"):
    def __init__(self, owner_id: int, tournament: Tournament):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament.pk

        self.description = TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=2000,
            default=tournament.description[:2000] if tournament.description else None,
        )
        self.semifinal_cutoff = TextInput(
            label="Semifinal cutoff (points)", required=False, max_length=4, default=str(tournament.semifinal_cutoff)
        )
        self.starts_at = TextInput(
            label="Scheduled start",
            required=False,
            max_length=32,
            default=format_for_input(tournament.scheduled_start_at),
            placeholder="Leave empty to clear",
        )
        self.ends_at = TextInput(
            label="Scheduled end",
            required=False,
            max_length=32,
            default=format_for_input(tournament.scheduled_end_at),
            placeholder="Leave empty to clear",
        )
        self.status = TextInput(
            label="Status",
            required=False,
            max_length=16,
            default=tournament.status,
            placeholder="registration, group_stage, semifinals, finals, completed",
        )
        self.add_item(self.description)
        self.add_item(self.semifinal_cutoff)
        self.add_item(self.starts_at)
        self.add_item(self.ends_at)
        self.add_item(self.status)

    async def on_submit(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await interaction.response.send_message(
                "Only the admin who opened this panel can submit this form.", ephemeral=True
            )
            return

        tournament = await Tournament.objects.aget(pk=self.tournament_id)

        try:
            semifinal_cutoff = int(self.semifinal_cutoff.value.strip() or "0")
            if semifinal_cutoff < 0:
                raise ValueError
            scheduled_start = parse_optional_datetime(self.starts_at.value)
            scheduled_end = parse_optional_datetime(self.ends_at.value)
            status = parse_status(self.status.value) or tournament.status
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if scheduled_start and scheduled_end and scheduled_start >= scheduled_end:
            await interaction.response.send_message("Scheduled start must be before scheduled end.", ephemeral=True)
            return

        tournament.description = self.description.value or ""
        tournament.semifinal_cutoff = semifinal_cutoff
        tournament.scheduled_start_at = scheduled_start
        tournament.scheduled_end_at = scheduled_end
        tournament.status = status
        await tournament.asave(
            update_fields=("description", "semifinal_cutoff", "scheduled_start_at", "scheduled_end_at", "status")
        )

        view = TournamentManageView(self.owner_id, notice=f"✅ Updated **{tournament.name}**.")
        await interaction.response.edit_message(view=view)


class TournamentSettingsModal(Modal, title="Tournament settings"):
    max_participants = TextInput(
        label="Max participants (0 = unlimited)",
        required=True,
        max_length=6,
        default="0",
    )

    def __init__(self, owner_id: int, tournament: Tournament):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament.pk
        self.max_participants.default = str(tournament.max_participants or 0)

    async def on_submit(self, interaction: Interaction) -> None:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        try:
            max_participants = int(self.max_participants.value.strip() or "0")
            if max_participants < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Max participants must be 0 or a positive number.", ephemeral=True)
            return

        tournament.max_participants = max_participants
        await tournament.asave(update_fields=("max_participants",))

        cap_text = "unlimited" if max_participants == 0 else f"{max_participants:,}"
        notice = f"✅ Updated **{tournament.name}** · max participants: **{cap_text}**."
        view = TournamentManageView(self.owner_id, notice=notice)
        await interaction.response.edit_message(view=view)


async def post_tournament_announcement(interaction: Interaction, tournament: Tournament) -> None:
    channel = interaction.channel
    if not isinstance(channel, discord.abc.Messageable):
        raise RuntimeError("Missing channel for tournament announcement.")

    host_discord_id = await Player.objects.values_list("discord_id", flat=True).aget(pk=tournament.host_id)
    schedule_lines = schedule_summary_lines(tournament)
    cap_text = "unlimited" if not tournament.max_participants else f"{tournament.max_participants:,}"
    sections = [
        f"**Status:** {tournament.get_status_display()}\n"
        f"**Host:** <@{host_discord_id}>\n"
        f"**Max participants:** {cap_text}\n"
        f"**Semifinal cutoff:** {tournament.semifinal_cutoff} points\n"
        f"**Betting:** {'enabled' if tournament.betting_enabled else 'disabled'}\n"
        + ("\n".join(schedule_lines) + "\n" if schedule_lines else "")
        + f"\n{tournament.description or 'No description provided.'}\n\n"
        f"-# `/tournament view` · `/tournament match` · `/tournament bet`"
    ]
    layout = build_tournament_layout(f"🏟️ {tournament.name}", sections)
    await channel.send(view=layout)


class TournamentHostView(LayoutView):
    def __init__(self, owner_id: int, tournament_id: int, tournament_name: str, status: str):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.tournament_id = tournament_id
        self.tournament_name = tournament_name
        self.status = status
        self._build()

    def _build(self) -> None:
        self.clear_items()
        container = Container()
        container.add_item(
            TextDisplay(
                truncate_text(
                    f"# 🎮 Host · **{self.tournament_name}**\n"
                    f"-# Status: `{self.status}`\n\n"
                    "▸ **Start** — open group stage (host only; ≥2 players in a group; also `/tournament start`)\n"
                    "▸ **Advance** — move to semifinals, finals, or complete\n"
                    "▸ **Sync bracket** — repair missing semifinal/final pairings"
                )
            )
        )
        container.add_item(Separator())
        container.add_item(TournamentHostControls(self.owner_id, self.tournament_id))
        container.add_item(TournamentBackRow(self.owner_id))
        self.add_item(container)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return False
        return True


class TournamentHostControls(ActionRow):
    def __init__(self, owner_id: int, tournament_id: int):
        super().__init__()
        self.owner_id = owner_id
        self.tournament_id = tournament_id

    @button(label="Start group stage", style=discord.ButtonStyle.success, emoji="▶")
    async def start_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return

        from fcdex_3_1.fcdex_ext.tournament_host import viewer_is_host

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        if not await viewer_is_host(interaction, tournament):
            await interaction.response.send_message(
                "Only the tournament **host** can start the group stage.", ephemeral=True
            )
            return

        from fcdex_3_1.fcdex_ext.tournament_cog import run_tournament_start
        from fcdex_3_1.fcdex_ext.tournament_host import registration_counts_by_group
        from fcdex_3_1.fcdex_ext.tournament_pairings import planned_group_stage_match_count

        if error := await run_tournament_start(tournament):
            await interaction.response.send_message(error, ephemeral=True)
            return
        counts = await registration_counts_by_group(tournament)
        match_count = planned_group_stage_match_count(
            counts[TournamentGroup.LEGACY.value], counts[TournamentGroup.MAIN.value]
        )
        view = TournamentManageView(
            self.owner_id, notice=f"▶ **{tournament.name}** group stage started — **{match_count}** match(es) created."
        )
        await interaction.response.edit_message(view=view)

    @button(label="Advance round", style=discord.ButtonStyle.primary, emoji="⏭")
    async def advance_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        if not _require_manage_guild(interaction):
            await _deny_manage_guild(interaction)
            return
        from fcdex_3_1.fcdex_ext.tournament_cog import run_tournament_advance

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        ok, message = await run_tournament_advance(tournament)
        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return
        view = TournamentManageView(self.owner_id, notice=message)
        await interaction.response.edit_message(view=view)

    @button(label="Sync bracket", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def sync_button(self, interaction: Interaction, button: Button):
        if _owner_mismatch(interaction, self.owner_id):
            await _deny_owner(interaction)
            return
        if not _require_manage_guild(interaction):
            await _deny_manage_guild(interaction)
            return
        from fcdex_3_1.fcdex_ext.tournament_bracket import sync_bracket_for_status

        tournament = await Tournament.objects.aget(pk=self.tournament_id)
        semis, final = await sync_bracket_for_status(tournament)
        if not semis and not final:
            await interaction.response.send_message("Bracket is already synced — no missing pairings.", ephemeral=True)
            return
        parts: list[str] = []
        if semis:
            parts.append(f"**{semis}** semifinal pairing(s)")
        if final:
            parts.append("**grand final**")
        view = TournamentManageView(
            self.owner_id, notice=f"🔄 Created {' and '.join(parts)}. Semifinalists use `/tournament match`."
        )
        await interaction.response.edit_message(view=view)
