"""Bot-owner panel for twin and match spawn rates (`/fcdex admin` -> Spawns)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from fcdex_3_1.fcdex_ext.spawn_events import get_spawn_config, invalidate_spawn_config, spawn_rates
from fcdex_3_1.fcdex_ext.views import AdminHubBackRow, truncate_text
from fcdex_3_1.models import SpawnEventConfig

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.spawn.admin")

OWNERS_ONLY = "Only the bot owners can change spawn rates, they apply to every server."


async def _deny_unless_owner(interaction: Interaction, owner_id: int) -> bool:
    """True (after replying) when the user may not use this panel."""
    if interaction.user.id != owner_id:
        await interaction.response.send_message("This panel is not yours.", ephemeral=True)
        return True
    if not await interaction.client.is_owner(interaction.user):
        await interaction.response.send_message(OWNERS_ONLY, ephemeral=True)
        return True
    return False


def _parse_percent(raw: str, label: str) -> float:
    try:
        value = float(raw.strip().rstrip("%").replace(",", "."))
    except ValueError:
        raise ValueError(f"{label} must be a number between 0 and 100.") from None
    if not 0 <= value <= 100:
        raise ValueError(f"{label} must be a number between 0 and 100.")
    return value


def _parse_difficulty(raw: str) -> int:
    try:
        value = int(raw.strip().rstrip("%"))
    except ValueError:
        raise ValueError("Difficulty must be a whole number between 10 and 1000.") from None
    if not 10 <= value <= 1000:
        raise ValueError("Difficulty must be a whole number between 10 and 1000.")
    return value


class SpawnRatesModal(Modal, title="Spawn rates"):
    twin_chance = TextInput(label="Twin spawn chance (%)", placeholder="10", max_length=6)
    match_chance = TextInput(label="Match spawn chance (%)", placeholder="2", max_length=6)
    difficulty = TextInput(label="Match difficulty (% of opponent stats)", placeholder="110", max_length=5)

    def __init__(self, owner_id: int, config: SpawnEventConfig):
        super().__init__()
        self.owner_id = owner_id
        self.twin_chance.default = f"{config.twin_chance:g}"
        self.match_chance.default = f"{config.match_chance:g}"
        self.difficulty.default = str(config.match_difficulty)

    async def on_submit(self, interaction: Interaction) -> None:
        if await _deny_unless_owner(interaction, self.owner_id):
            return
        try:
            twin = _parse_percent(self.twin_chance.value, "Twin chance")
            match = _parse_percent(self.match_chance.value, "Match chance")
            difficulty = _parse_difficulty(self.difficulty.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if twin + match > 100:
            await interaction.response.send_message(
                "Twin and match chances together cannot exceed 100%.", ephemeral=True
            )
            return

        config = await get_spawn_config(max_age=0)
        config.twin_chance, config.match_chance, config.match_difficulty = twin, match, difficulty
        await config.asave(update_fields=("twin_chance", "match_chance", "match_difficulty"))
        invalidate_spawn_config()
        layout = await build_spawn_admin_layout(self.owner_id, notice="Spawn rates saved.")
        await interaction.response.edit_message(view=layout)


class SpawnAdminControls(ActionRow):
    def __init__(self, owner_id: int, config: SpawnEventConfig):
        super().__init__()
        self.owner_id = owner_id
        self.config = config
        self.toggle_twin.label = "Disable twin" if config.twin_enabled else "Enable twin"
        self.toggle_match.label = "Disable match" if config.match_enabled else "Enable match"

    async def _toggle(self, interaction: Interaction, field: str, label: str) -> None:
        if await _deny_unless_owner(interaction, self.owner_id):
            return
        config = await get_spawn_config(max_age=0)
        enabled = not getattr(config, field)
        setattr(config, field, enabled)
        await config.asave(update_fields=(field,))
        invalidate_spawn_config()
        layout = await build_spawn_admin_layout(
            self.owner_id, notice=f"{label} spawns are now **{'on' if enabled else 'off'}**."
        )
        await interaction.response.edit_message(view=layout)

    @button(label="Disable twin", style=discord.ButtonStyle.secondary, emoji="\N{SCALES}")
    async def toggle_twin(self, interaction: Interaction, button: Button) -> None:
        await self._toggle(interaction, "twin_enabled", "Twin")

    @button(label="Disable match", style=discord.ButtonStyle.secondary, emoji="\N{SOCCER BALL}")
    async def toggle_match(self, interaction: Interaction, button: Button) -> None:
        await self._toggle(interaction, "match_enabled", "Match")

    @button(label="Edit rates", style=discord.ButtonStyle.primary, emoji="\N{GAME DIE}")
    async def edit_rates(self, interaction: Interaction, button: Button) -> None:
        if await _deny_unless_owner(interaction, self.owner_id):
            return
        config = await get_spawn_config(max_age=0)
        await interaction.response.send_modal(SpawnRatesModal(self.owner_id, config))


async def build_spawn_admin_layout(owner_id: int, *, notice: str = "") -> LayoutView:
    config = await get_spawn_config(max_age=0)
    rates = spawn_rates(config)
    normal = max(0.0, 100.0 - rates.twin - rates.match)

    def state(enabled: bool) -> str:
        return "\N{WHITE HEAVY CHECK MARK} on" if enabled else "\N{NO ENTRY SIGN} off"

    body = (
        f"**Twin spawn** · {state(config.twin_enabled)} · **{config.twin_chance:g}%** of natural spawns\n"
        "-# Two clubballs side by side, the first correct guess catches the one it names.\n\n"
        f"**Match spawn** · {state(config.match_enabled)} · **{config.match_chance:g}%** of natural spawns · "
        f"difficulty **{config.match_difficulty}%**\n"
        "-# Win a match against the spawned clubball to earn a rarer one.\n\n"
        f"**Normal spawns** · about **{normal:g}%**\n"
        "-# Changes reach the bot within about 30 seconds. They apply to every server."
    )
    if notice:
        body = f"**{notice}**\n\n{body}"

    layout = LayoutView(timeout=600)
    container = Container()
    container.add_item(
        TextDisplay(
            truncate_text(
                "# \N{GAME DIE} Spawn events\n"
                "-# Twin and match spawns replace some natural spawns. Bot owners only.\n"
                "-# Test one right now with `/fcdex spawn`."
            )
        )
    )
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(body)))
    container.add_item(Separator())
    container.add_item(SpawnAdminControls(owner_id, config))
    container.add_item(Separator())
    container.add_item(AdminHubBackRow(owner_id))
    layout.add_item(container)
    return layout
