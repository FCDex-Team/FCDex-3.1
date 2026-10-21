"""Bot-owner panel for FC Derby rewards (`/fcdex admin` -> Derby)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from fcdex_3_1.fcdex_ext.currency import currency_noun
from fcdex_3_1.fcdex_ext.derby_service import get_derby_config, invalidate_derby_config
from fcdex_3_1.fcdex_ext.views import AdminHubBackRow, truncate_text
from fcdex_3_1.models import DerbyConfig

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.derby.admin")

OWNERS_ONLY = "Only the bot owners can change derby rewards, they apply to every server."
MAX_AMOUNT = 1_000_000


def parse_range(raw: str, label: str) -> tuple[int, int]:
    """`150-300` (or a single `200`) as a low/high pair."""
    text = raw.strip().replace(" ", "").replace("–", "-")
    parts = text.split("-") if text else []
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        numbers = []
    if len(numbers) not in (1, 2) or any(n < 0 or n > MAX_AMOUNT for n in numbers):
        raise ValueError(f"{label} must look like `150-300` (whole numbers, 0 to {MAX_AMOUNT:,}).")
    low, high = numbers[0], numbers[-1]
    if low > high:
        raise ValueError(f"{label}: the minimum cannot be above the maximum.")
    return low, high


def parse_amount(raw: str, label: str, *, minimum: int = 0, maximum: int = MAX_AMOUNT) -> int:
    try:
        value = int(raw.strip().replace(",", ""))
    except ValueError:
        raise ValueError(f"{label} must be a whole number.") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum:,}.")
    return value


async def _deny_unless_owner(interaction: Interaction, owner_id: int) -> bool:
    """True (after replying) when the user may not use this panel."""
    if interaction.user.id != owner_id:
        await interaction.response.send_message("This panel is not yours.", ephemeral=True)
        return True
    if not await interaction.client.is_owner(interaction.user):
        await interaction.response.send_message(OWNERS_ONLY, ephemeral=True)
        return True
    return False


class DerbyConfigModal(Modal, title="Derby rewards"):
    winner_coins = TextInput(label="Winner coins (min-max)", placeholder="150-300", max_length=20)
    loser_coins = TextInput(label="Loser coins", placeholder="50", max_length=10)
    winner_xp = TextInput(label="Winner Club Pass XP (min-max)", placeholder="20-30", max_length=20)
    loser_xp = TextInput(label="Loser Club Pass XP", placeholder="10", max_length=10)
    daily_limit = TextInput(label="Derbies per player per UTC day", placeholder="12", max_length=4)

    def __init__(self, owner_id: int, config: DerbyConfig):
        super().__init__()
        self.owner_id = owner_id
        self.winner_coins.default = f"{config.winner_coins_min}-{config.winner_coins_max}"
        self.loser_coins.default = str(config.loser_coins)
        self.winner_xp.default = f"{config.winner_xp_min}-{config.winner_xp_max}"
        self.loser_xp.default = str(config.loser_xp)
        self.daily_limit.default = str(config.daily_limit)

    async def on_submit(self, interaction: Interaction) -> None:
        if await _deny_unless_owner(interaction, self.owner_id):
            return
        try:
            coins_low, coins_high = parse_range(self.winner_coins.value, "Winner coins")
            xp_low, xp_high = parse_range(self.winner_xp.value, "Winner XP")
            loser_coins = parse_amount(self.loser_coins.value, "Loser coins")
            loser_xp = parse_amount(self.loser_xp.value, "Loser XP")
            limit = parse_amount(self.daily_limit.value, "Daily limit", minimum=1, maximum=1000)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        config = await get_derby_config(max_age=0)
        config.winner_coins_min, config.winner_coins_max = coins_low, coins_high
        config.winner_xp_min, config.winner_xp_max = xp_low, xp_high
        config.loser_coins, config.loser_xp, config.daily_limit = loser_coins, loser_xp, limit
        await config.asave()
        invalidate_derby_config()
        layout = await build_derby_admin_layout(self.owner_id, notice="Derby rewards saved.")
        await interaction.response.edit_message(view=layout)


class DerbyAdminControls(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="Edit rewards", style=discord.ButtonStyle.primary, emoji="\N{SOCCER BALL}")
    async def edit_rewards(self, interaction: Interaction, button: Button) -> None:
        if await _deny_unless_owner(interaction, self.owner_id):
            return
        config = await get_derby_config(max_age=0)
        await interaction.response.send_modal(DerbyConfigModal(self.owner_id, config))


async def build_derby_admin_layout(owner_id: int, *, notice: str = "") -> LayoutView:
    config = await get_derby_config(max_age=0)
    coins = currency_noun(2)
    body = (
        f"**Winner** · **{config.winner_coins_min}-{config.winner_coins_max}** {coins} · "
        f"**{config.winner_xp_min}-{config.winner_xp_max}** XP\n"
        f"**Loser** · **{config.loser_coins}** {coins} · **{config.loser_xp}** XP\n"
        f"**Daily limit** · **{config.daily_limit}** derbies per player per UTC day (both sides count)\n"
        "-# Changes reach the bot within about 30 seconds. They apply to every server."
    )
    if notice:
        body = f"**{notice}**\n\n{body}"

    layout = LayoutView(timeout=600)
    container = Container()
    container.add_item(
        TextDisplay(
            truncate_text(
                "# \N{SOCCER BALL} FC Derby\n"
                "-# Rewards for `/fc derby challenge`. Club Pass XP needs the Club Pass. Bot owners only."
            )
        )
    )
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(body)))
    container.add_item(Separator())
    container.add_item(DerbyAdminControls(owner_id))
    container.add_item(Separator())
    container.add_item(AdminHubBackRow(owner_id))
    layout.add_item(container)
    return layout
