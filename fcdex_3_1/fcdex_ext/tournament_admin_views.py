from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from fcdex_3_1.fcdex_ext.interaction_context import AdminContext, admin_context
from fcdex_3_1.fcdex_ext.tournament_config import get_tournament_config
from fcdex_3_1.fcdex_ext.views import AdminHubBackRow, truncate_text

if TYPE_CHECKING:
    from discord import Interaction


class TournamentConfigModal(Modal, title="Tournament caps"):
    max_participants_cap = TextInput(
        label="Max participants cap (0 = unlimited)", required=True, max_length=6, default="0"
    )
    semifinal_cutoff_cap = TextInput(
        label="Semifinal cutoff cap (0 = unlimited)", required=True, max_length=6, default="0"
    )
    min_bet_cap = TextInput(label="Min bet cap (0 = unlimited)", required=True, max_length=12, default="0")
    max_bet_cap = TextInput(label="Max bet cap (0 = unlimited)", required=True, max_length=12, default="0")
    bet_payout_multiplier_cap = TextInput(
        label="Bet payout multiplier cap (0 = unlimited)", required=True, max_length=4, default="0"
    )

    def __init__(self, owner_id: int, *, config):
        super().__init__()
        self.owner_id = owner_id
        self.max_participants_cap.default = str(config.max_participants_cap or 0)
        self.semifinal_cutoff_cap.default = str(config.semifinal_cutoff_cap or 0)
        self.min_bet_cap.default = str(config.min_bet_cap or 0)
        self.max_bet_cap.default = str(config.max_bet_cap or 0)
        self.bet_payout_multiplier_cap.default = str(config.bet_payout_multiplier_cap or 0)

    async def on_submit(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        try:
            max_participants_cap = int(self.max_participants_cap.value.strip() or "0")
            semifinal_cutoff_cap = int(self.semifinal_cutoff_cap.value.strip() or "0")
            min_bet_cap = int(self.min_bet_cap.value.strip() or "0")
            max_bet_cap = int(self.max_bet_cap.value.strip() or "0")
            bet_payout_multiplier_cap = int(self.bet_payout_multiplier_cap.value.strip() or "0")
            if any(
                v < 0
                for v in (
                    max_participants_cap,
                    semifinal_cutoff_cap,
                    min_bet_cap,
                    max_bet_cap,
                    bet_payout_multiplier_cap,
                )
            ):
                raise ValueError
        except ValueError:
            await interaction.response.send_message("All caps must be 0 or positive integers.", ephemeral=True)
            return

        config = await get_tournament_config()
        config.max_participants_cap = max_participants_cap
        config.semifinal_cutoff_cap = semifinal_cutoff_cap
        config.min_bet_cap = min_bet_cap
        config.max_bet_cap = max_bet_cap
        config.bet_payout_multiplier_cap = bet_payout_multiplier_cap
        await config.asave(
            update_fields=(
                "max_participants_cap",
                "semifinal_cutoff_cap",
                "min_bet_cap",
                "max_bet_cap",
                "bet_payout_multiplier_cap",
            )
        )
        ctx = admin_context(interaction)
        layout = await build_tournament_admin_layout(self.owner_id, ctx, notice="Tournament caps updated.")
        await interaction.response.edit_message(view=layout)


class TournamentAdminControls(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="Edit caps", style=discord.ButtonStyle.primary, emoji="⚙️")
    async def edit_caps(self, interaction: Interaction, button: Button):
        config = await get_tournament_config()
        await interaction.response.send_modal(TournamentConfigModal(self.owner_id, config=config))

    @button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_tournament_admin_layout(self.owner_id, ctx)
        await interaction.response.edit_message(view=layout)


async def build_tournament_admin_layout(owner_id: int, ctx: AdminContext, *, notice: str = "") -> LayoutView:
    config = await get_tournament_config()

    def cap_text(value: int) -> str:
        return "unlimited" if value == 0 else str(value)

    body = (
        "**Tournament caps** (0 = unlimited)\n"
        f"• Max participants: **{cap_text(config.max_participants_cap)}**\n"
        f"• Semifinal cutoff: **{cap_text(config.semifinal_cutoff_cap)}**\n"
        f"• Min bet: **{cap_text(config.min_bet_cap)}**\n"
        f"• Max bet: **{cap_text(config.max_bet_cap)}**\n"
        f"• Bet payout multiplier: **{cap_text(config.bet_payout_multiplier_cap)}**"
    )
    if notice:
        body = f"**{notice}**\n\n{body}"

    layout = LayoutView(timeout=600)
    container = Container()
    container.add_item(
        TextDisplay(
            truncate_text(
                "# 🏟️ Tournament admin\n"
                "-# Set global caps that restrict values entered in `/tournament manage`.\n"
                "-# Default is unlimited (0)."
            )
        )
    )
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(body)))
    container.add_item(Separator())
    container.add_item(TournamentAdminControls(owner_id))
    container.add_item(Separator())
    container.add_item(AdminHubBackRow(owner_id))
    layout.add_item(container)
    return layout
