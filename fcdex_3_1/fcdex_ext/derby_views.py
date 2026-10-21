"""Components v2 panels for FC Derby: formation picker, squad picture, status and the challenge flow."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, MediaGallery, Separator, TextDisplay, button

from ballsdex.core.discord import LayoutView
from bd_models.models import Player
from fcdex_3_1.fcdex_ext.derby_images import SlotCard, ball_art_path, render_formation_preview, render_squad_image
from fcdex_3_1.fcdex_ext.derby_logic import (
    CHALLENGE_TIMEOUT_SECONDS,
    POSITION_LABELS,
    LayoutPicker,
    format_missing,
    get_formation,
    squad_size,
)
from fcdex_3_1.fcdex_ext.derby_pass_bridge import UNAVAILABLE, PassMilestone, club_pass_status
from fcdex_3_1.fcdex_ext.derby_service import get_derby_stats, get_formation_key, load_slots, set_formation
from fcdex_3_1.fcdex_ext.views import truncate_text

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.derby.views")

IMAGE_NAME = "derby.png"


def _png_file(data: bytes) -> discord.File:
    return discord.File(io.BytesIO(data), filename=IMAGE_NAME)


def _picture_container(text: str, *, description: str) -> Container:
    container = Container()
    container.add_item(TextDisplay(truncate_text(text)))
    container.add_item(MediaGallery(discord.MediaGalleryItem(f"attachment://{IMAGE_NAME}", description=description)))
    return container


# -- layouts ---------------------------------------------------------------------------------------------------


class LayoutPickerControls(ActionRow):
    def __init__(self, owner_id: int, picker: LayoutPicker, *, active: bool = True):
        super().__init__()
        self.owner_id = owner_id
        self.picker = picker
        self.next_button.disabled = not active
        self.accept_button.disabled = not active

    async def _own(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return False
        return True

    @button(label="Next", style=discord.ButtonStyle.secondary, emoji="\N{BLACK RIGHT-POINTING TRIANGLE}")
    async def next_button(self, interaction: Interaction, button: Button) -> None:
        if not await self._own(interaction):
            return
        self.picker.next()
        layout, file = await build_layouts_panel(self.owner_id, self.picker)
        await interaction.response.edit_message(view=layout, attachments=[file])

    @button(label="Accept", style=discord.ButtonStyle.success, emoji="\N{WHITE HEAVY CHECK MARK}")
    async def accept_button(self, interaction: Interaction, button: Button) -> None:
        if not await self._own(interaction):
            return
        key = self.picker.accept()
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        dropped = await set_formation(player, key)
        notice = f"Formation set to **{key}**."
        if dropped:
            names = ", ".join(f"{position}{slot + 1}" for position, slot in sorted(dropped))
            notice += f"\n-# Removed from your squad because this formation has no such slot: {names}."
        layout, file = await build_layouts_panel(self.owner_id, self.picker, notice=notice, active=False)
        await interaction.response.edit_message(view=layout, attachments=[file])


async def build_layouts_panel(
    owner_id: int, picker: LayoutPicker, *, notice: str = "", active: bool = True
) -> tuple[LayoutView, discord.File]:
    formation = get_formation(picker.current)
    image = await asyncio.to_thread(render_formation_preview, formation.key)
    head = f"# \N{SOCCER BALL} Derby layouts\n-# Formation {picker.position_text} · {formation.summary()}"
    if notice:
        head += f"\n\n{notice}"
    container = _picture_container(head, description=f"{formation.key} formation")
    container.add_item(Separator())
    container.add_item(LayoutPickerControls(owner_id, picker, active=active))
    layout = LayoutView(timeout=600)
    layout.add_item(container)
    return layout, _png_file(image)


# -- show ------------------------------------------------------------------------------------------------------


async def build_show_panel(player: Player, *, owner_name: str) -> tuple[LayoutView, discord.File]:
    formation = get_formation(await get_formation_key(player))
    rows = await load_slots(player)
    squad = {(row.position, row.slot): row.ball_id for row in rows}
    cards = {
        (row.position, row.slot): SlotCard(label=row.ball.country, art_path=ball_art_path(row.ball)) for row in rows
    }
    image = await asyncio.to_thread(render_squad_image, formation, cards)

    size = squad_size(formation, squad)
    order = formation.slot_keys()
    placed = sorted(
        (row for row in rows if (row.position, row.slot) in order), key=lambda r: order.index((r.position, r.slot))
    )
    lines = [f"**{POSITION_LABELS[row.position]} {row.slot + 1}** · {row.ball.country}" for row in placed]
    head = (
        f"# \N{SOCCER BALL} {owner_name}'s derby squad\n-# {formation.key} · **{size}/{formation.total}** slots filled"
    )
    body = "\n".join(lines) if lines else "*Nobody yet. Use `/fc derby add`.*"
    missing = format_missing(formation, squad)
    if missing:
        body += f"\n\n-# Empty: {missing}"
    container = _picture_container(head, description=f"{formation.key} squad")
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(body)))
    layout = LayoutView(timeout=600)
    layout.add_item(container)
    return layout, _png_file(image)


# -- status ----------------------------------------------------------------------------------------------------


def _milestone_text(milestones: list[PassMilestone], selected: int | None) -> str:
    if not milestones:
        return ""
    if selected is not None:
        chosen = [m for m in milestones if m.level == selected]
        if chosen:
            return f"**Level {chosen[0].level}** · {chosen[0].label}"
    return "\n".join(f"Level **{m.level}** · {m.label}" for m in milestones[:5])


async def build_status_panel(player: Player, *, milestone: int | None = None) -> LayoutView:
    status = await club_pass_status(player)
    stats = await get_derby_stats(player)
    wins, losses, played = (stats.wins, stats.losses, stats.played) if stats else (0, 0, 0)

    if status.available:
        level = f"**{status.level}**" if status.level is not None else "?"
        xp = f"**{status.xp:,}** XP" if status.xp is not None else "XP unknown"
        pass_text = f"Level {level} · {xp}"
        if status.xp_to_next is not None:
            pass_text += f" · {status.xp_to_next:,} XP to the next level"
        upcoming = _milestone_text(status.milestones, milestone)
        if upcoming:
            pass_text += f"\n\n### Upcoming rewards\n{upcoming}"
    else:
        pass_text = f"-# {UNAVAILABLE}"

    layout = LayoutView(timeout=600)
    container = Container()
    container.add_item(
        TextDisplay(truncate_text("# \N{TROPHY} Derby status\n-# Derby XP counts toward your Club Pass."))
    )
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(f"### Club Pass\n{pass_text}")))
    container.add_item(Separator())
    container.add_item(
        TextDisplay(
            f"### Record\n**{wins}** won · **{losses}** lost · **{played}** played"
            + (f" · {wins * 100 // played}% win rate" if played else "")
        )
    )
    layout.add_item(container)
    return layout


# -- challenge -------------------------------------------------------------------------------------------------


class DerbyChallengeView(LayoutView):
    """Asks the opponent to accept. The match itself runs from the cog once they do."""

    def __init__(self, cog, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=CHALLENGE_TIMEOUT_SECONDS)
        self.cog = cog
        self.challenger = challenger
        self.opponent = opponent
        self.settled = False
        container = Container()
        container.add_item(
            TextDisplay(
                f"# \N{SOCCER BALL} FC Derby challenge\n"
                f"{challenger.mention} challenges {opponent.mention} to a derby!\n"
                "-# Saved squads and formations play. Coins and Club Pass XP only, no clubballs are won."
            )
        )
        container.add_item(Separator())
        self.controls = ChallengeControls(self)
        container.add_item(self.controls)
        self.add_item(container)

    async def on_timeout(self) -> None:
        if self.settled:
            return
        self.settled = True
        self.cog.release(self.challenger.id, self.opponent.id)
        message = getattr(self, "message", None)
        if message is not None:
            try:
                await message.edit(view=closed_view("The derby challenge expired."))
            except discord.HTTPException:
                log.debug("Could not close an expired derby challenge", exc_info=True)


def closed_view(text: str) -> LayoutView:
    layout = LayoutView(timeout=None)
    container = Container()
    container.add_item(TextDisplay(f"# \N{SOCCER BALL} FC Derby\n{text}"))
    layout.add_item(container)
    return layout


class ChallengeControls(ActionRow):
    def __init__(self, view: DerbyChallengeView):
        super().__init__()
        self.challenge = view

    @button(label="Accept", style=discord.ButtonStyle.success, emoji="\N{WHITE HEAVY CHECK MARK}")
    async def accept(self, interaction: Interaction, button: Button) -> None:
        view = self.challenge
        if interaction.user.id != view.opponent.id:
            await interaction.response.send_message("Only the challenged player can accept.", ephemeral=True)
            return
        if view.settled:
            await interaction.response.send_message("This challenge is over.", ephemeral=True)
            return
        view.settled = True
        view.stop()
        await interaction.response.defer()
        await view.cog.play(interaction, view.challenger, view.opponent)

    @button(label="Decline", style=discord.ButtonStyle.danger, emoji="\N{CROSS MARK}")
    async def decline(self, interaction: Interaction, button: Button) -> None:
        view = self.challenge
        if interaction.user.id not in (view.opponent.id, view.challenger.id):
            await interaction.response.send_message("This is not your challenge.", ephemeral=True)
            return
        if view.settled:
            await interaction.response.send_message("This challenge is over.", ephemeral=True)
            return
        view.settled = True
        view.stop()
        view.cog.release(view.challenger.id, view.opponent.id)
        who = "withdrawn" if interaction.user.id == view.challenger.id else "declined"
        await interaction.response.edit_message(view=closed_view(f"The derby challenge was {who}."))


def build_result_layout(
    challenger: discord.Member,
    opponent: discord.Member,
    *,
    winner: discord.Member | None,
    highlights: list[str],
    reports: list[str],
    turns: int,
) -> LayoutView:
    verdict = f"**Winner:** {winner.mention}" if winner else "**Draw.** Nobody wins."
    layout = LayoutView(timeout=None)
    container = Container()
    container.add_item(
        TextDisplay(
            truncate_text(
                f"# \N{SOCCER BALL} Derby full time\n{challenger.mention} **vs** {opponent.mention}\n"
                f"{verdict} · {turns} turns"
            )
        )
    )
    if highlights:
        container.add_item(Separator())
        container.add_item(TextDisplay(truncate_text("### \N{STUDIO MICROPHONE} Commentary\n" + "\n".join(highlights))))
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text("### \N{WRAPPED PRESENT} Rewards\n" + "\n".join(reports))))
    container.add_item(Separator())
    container.add_item(TextDisplay("-# Full commentary attached as `derby-commentary.txt`"))
    layout.add_item(container)
    return layout
