"""Twin spawn: two clubballs appear side by side and the first correct guess catches the one it names."""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, MediaGallery, TextDisplay, TextInput, button

from ballsdex.core.discord import Container, LayoutView, Modal
from bd_models.models import Player
from fcdex_3_1.fcdex_ext import compat
from fcdex_3_1.fcdex_ext.club_pass_logic import schedule_catch_xp
from fcdex_3_1.fcdex_ext.rarity_logic import fetch_all_balls
from fcdex_3_1.fcdex_ext.spawn_common import (
    ACCENT_TWIN,
    attachment_name,
    can_post_spawn,
    collectible_names,
    new_engine,
    post_spawn,
    prompt_message,
)
from fcdex_3_1.fcdex_ext.spawn_events import TWIN_TIMEOUT_SECONDS, pick_distinct_pair

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot
    from ballsdex.packages.countryballs.countryball import BallSpawnView

log = logging.getLogger("fcdex_3_1.spawn.twin")

SIDES = ("left", "right")
UNKNOWN_INTERACTION = 10062


class TwinCatchModal(Modal):
    def __init__(self, twin: TwinSpawnView, slot: int):
        collectible, _ = collectible_names()
        super().__init__(title=f"Catch the {SIDES[slot]} {collectible}!"[:45])  # Discord caps modal titles
        self.twin = twin
        self.slot = slot
        self.name = TextInput(
            label=f"Name of the {SIDES[slot]} {collectible}"[:45],
            style=discord.TextStyle.short,
            placeholder="Your guess",
        )
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction[BallsDexBot]) -> None:
        await interaction.response.defer(thinking=True)
        await self.twin.handle_guess(interaction, self.slot, self.name.value)

    async def on_error(self, interaction: discord.Interaction[BallsDexBot], error: Exception) -> None:
        if isinstance(error, discord.NotFound) and error.code == UNKNOWN_INTERACTION:
            return
        log.exception("An error occurred in the twin spawn catch prompt", exc_info=error)
        collectible, _ = collectible_names()
        message = f"An error occurred with this {collectible}."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class TwinCatchRow(ActionRow["TwinSpawnView"]):
    """The catch buttons, one per clubball. Components v2 wants buttons wrapped in an action row."""

    def __init__(self, twin: TwinSpawnView):
        super().__init__()
        self.twin = twin
        for slot, item in enumerate((self.left, self.right)):
            item.disabled = twin.closed
            if twin.caught_slot is not None:
                won = slot == twin.caught_slot
                item.label = "Caught!" if won else "Got away"
                item.style = discord.ButtonStyle.success if won else discord.ButtonStyle.secondary
            elif twin.expired:
                item.label = "Got away"
                item.style = discord.ButtonStyle.secondary

    @button(label="Catch left", emoji="\N{LEFTWARDS BLACK ARROW}\N{VARIATION SELECTOR-16}")
    async def left(self, interaction: discord.Interaction[BallsDexBot], button: Button) -> None:
        await self.twin.open_prompt(interaction, 0)

    @button(label="Catch right", emoji="\N{BLACK RIGHTWARDS ARROW}\N{VARIATION SELECTOR-16}")
    async def right(self, interaction: discord.Interaction[BallsDexBot], button: Button) -> None:
        await self.twin.open_prompt(interaction, 1)


class TwinSpawnView(LayoutView):
    """Two spawned clubballs on one message. Each side has its own catch engine; only one side can be caught."""

    def __init__(
        self, bot: BallsDexBot, engines: tuple[BallSpawnView, BallSpawnView], file_names: tuple[str, str]
    ) -> None:
        super().__init__(timeout=TWIN_TIMEOUT_SECONDS)
        self.bot = bot
        self.engines = engines
        self.file_names = file_names
        self.message: discord.Message = discord.utils.MISSING
        self.caught_slot: int | None = None
        self.catcher_mention = ""
        self.expired = False
        self._render()

    @property
    def caught(self) -> bool:
        return self.caught_slot is not None

    @property
    def closed(self) -> bool:
        return self.caught or self.expired

    def _status_line(self) -> str:
        if self.caught_slot is not None:
            return f"\N{WHITE HEAVY CHECK MARK} {self.catcher_mention} caught the **{SIDES[self.caught_slot]}** one!"
        if self.expired:
            return "\N{HOURGLASS WITH FLOWING SAND} Nobody picked one in time, both got away."
        return ""

    def _render(self) -> None:
        self.clear_items()
        _, plural = collectible_names()
        container = Container(accent_colour=ACCENT_TWIN)
        container.add_item(
            TextDisplay(
                f"# \N{SCALES} Twin spawn!\n"
                f"Two wild {plural} appeared side by side. Pick one and name it to catch it, "
                "only one of them can be caught."
            )
        )
        container.add_item(
            MediaGallery(*(discord.MediaGalleryItem(f"attachment://{name}") for name in self.file_names))
        )
        if status := self._status_line():
            container.add_item(TextDisplay(status))
        container.add_item(TwinCatchRow(self))
        self.add_item(container)

    def _slow_message(self, interaction: discord.Interaction[BallsDexBot], slot: int) -> str:
        return prompt_message(
            "SLOW",
            mention=interaction.user.mention,
            model=self.engines[slot].model,
            bot=interaction.client,
            fallback=f"{interaction.user.mention} Too slow, this twin spawn was already caught!",
        )

    async def open_prompt(self, interaction: discord.Interaction[BallsDexBot], slot: int) -> None:
        if self.closed:
            await interaction.response.send_message(self._slow_message(interaction, slot), ephemeral=True)
            return
        await interaction.response.send_modal(TwinCatchModal(self, slot))

    async def handle_guess(self, interaction: discord.Interaction[BallsDexBot], slot: int, guess: str) -> None:
        """Everything after the catch prompt was submitted. The interaction is already deferred."""
        engine = self.engines[slot]
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        allowed = discord.AllowedMentions(users=player.can_be_mentioned)
        if self.closed:
            await interaction.followup.send(
                self._slow_message(interaction, slot), ephemeral=True, allowed_mentions=allowed
            )
            return

        if not engine.is_name_valid(guess):
            wrong = guess[:500] + "..." if len(guess) > 500 else guess
            message = prompt_message(
                "WRONG",
                mention=interaction.user.mention,
                model=engine.model,
                bot=interaction.client,
                fallback=f"{interaction.user.mention} Wrong name!",
                wrong=wrong,
            )
            await interaction.followup.send(message, allowed_mentions=allowed, ephemeral=False)
            return

        pre_catch = await compat.run_hook(
            interaction.client, "PreCatchContext", view=engine, interaction=interaction, player=player, guess=guess
        )
        if pre_catch is not None and pre_catch.cancelled:
            collectible, _ = collectible_names()
            await interaction.followup.send(
                pre_catch.reason or f"You cannot catch this {collectible} right now.", ephemeral=True
            )
            return
        # hooks may have taken a while, somebody else could have won in the meantime
        if self.closed:
            await interaction.followup.send(
                self._slow_message(interaction, slot), ephemeral=True, allowed_mentions=allowed
            )
            return

        # claim the spawn before the first await so two simultaneous correct guesses cannot both win
        self.caught_slot = slot
        self.catcher_mention = interaction.user.mention
        try:
            ball, is_new = await engine.catch_ball(interaction.user, player=player, guild=interaction.guild)
        except BaseException:
            self.caught_slot = None
            engine.caught = False
            raise
        schedule_catch_xp(ball, player)  # one payment per instance, even if the catch event pays it too

        content = engine.get_catch_message(ball, is_new, interaction.user.mention)
        catch_message = await compat.run_hook(
            interaction.client,
            "CatchMessageContext",
            view=engine,
            interaction=interaction,
            player=player,
            ball_instance=ball,
            is_new=is_new,
            content=content,
        )
        if catch_message is not None:
            content = catch_message.content
        await interaction.followup.send(content, allowed_mentions=allowed)

        self._render()
        try:
            await interaction.followup.edit_message(self.message.id, view=self)
        except discord.HTTPException:
            log.warning("Could not update the twin spawn message after a catch.", exc_info=True)

    async def on_timeout(self) -> None:
        if self.caught:
            return
        self.expired = True
        self._render()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


async def spawn_twin(
    bot: BallsDexBot, channel: discord.abc.GuildChannel, *, algo: str | None = None, rng: random.Random | None = None
) -> bool:
    """Post a twin spawn in `channel`. Returns False (after logging) if it could not be posted."""
    try:
        first, second = pick_distinct_pair(await fetch_all_balls(), rng)
    except ValueError:
        log.info("Not enough spawnable clubballs for a twin spawn.")
        return False
    if not can_post_spawn(channel):
        log.warning("Missing permission to post a twin spawn in channel %s.", channel)
        return False

    label = f"{algo or 'fcdex'}:twin"
    engines = (new_engine(bot, first, algo=label), new_engine(bot, second, algo=label))
    file_names = (attachment_name(first), attachment_name(second))
    view = TwinSpawnView(bot, engines, file_names)
    message = await post_spawn(channel, view, (first, second), file_names)  # type: ignore[arg-type]
    if message is None:
        return False
    view.message = message
    for engine in engines:
        engine.message = message
        compat.dispatch_ball_spawned(bot, engine, channel)
    return True
