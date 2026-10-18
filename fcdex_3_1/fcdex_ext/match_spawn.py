"""Match spawn: win a match against the spawned clubball to earn a rarer one."""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, MediaGallery, Select, Separator, TextDisplay, button

from ballsdex.core.discord import Container, LayoutView
from bd_models.models import BallInstance, Player
from fcdex_3_1.fcdex_ext import compat
from fcdex_3_1.fcdex_ext.bd_helpers import stat_with_bonus
from fcdex_3_1.fcdex_ext.match_logic import card_power, roll_match
from fcdex_3_1.fcdex_ext.rarity_logic import fetch_all_balls
from fcdex_3_1.fcdex_ext.spawn_common import (
    ACCENT_MATCH,
    attachment_name,
    can_post_spawn,
    collectible_names,
    new_engine,
    post_spawn,
)
from fcdex_3_1.fcdex_ext.spawn_events import (
    MATCH_TIMEOUT_SECONDS,
    get_spawn_config,
    match_target_power,
    pick_match_original,
    pick_match_reward,
)
from fcdex_3_1.fcdex_ext.views import build_panel_layout

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot
    from ballsdex.packages.countryballs.countryball import BallSpawnView

log = logging.getLogger("fcdex_3_1.spawn.match")

CARD_CHOICES = 25  # a Discord select menu holds at most 25 options
PICKER_TIMEOUT_SECONDS = 120

PlayCallback = Callable[[discord.Interaction, int], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class MatchCard:
    instance_id: int
    country: str
    attack: int
    health: int

    @property
    def power(self) -> int:
        return card_power(self.attack, self.health)

    @property
    def label(self) -> str:
        return f"#{self.instance_id:X} {self.country}"


_CARD_FIELDS = ("pk", "attack_bonus", "health_bonus", "ball__attack", "ball__health", "ball__country")


def _card_from_row(row: tuple[int, int, int, int, int, str]) -> MatchCard:
    pk, attack_bonus, health_bonus, attack, health, country = row
    return MatchCard(pk, country, stat_with_bonus(attack, attack_bonus), stat_with_bonus(health, health_bonus))


async def strongest_cards(player: Player, limit: int = CARD_CHOICES) -> list[MatchCard]:
    """The player's `limit` strongest clubballs, strongest first."""
    rows = BallInstance.objects.filter(player=player, deleted=False).values_list(*_CARD_FIELDS)
    cards = [_card_from_row(row) async for row in rows]  # type: ignore[arg-type]
    cards.sort(key=lambda card: card.power, reverse=True)
    return cards[:limit]


async def load_card(player: Player, instance_id: int) -> MatchCard | None:
    queryset = BallInstance.objects.filter(player=player, deleted=False, pk=instance_id)
    row = await queryset.values_list(*_CARD_FIELDS).afirst()
    return _card_from_row(row) if row is not None else None  # type: ignore[arg-type]


class MatchCardSelect(Select):
    def __init__(self, cards: list[MatchCard], on_pick: PlayCallback):
        options = [
            discord.SelectOption(
                label=card.label[:100],
                value=str(card.instance_id),
                description=f"ATK {card.attack:,} · HP {card.health:,} · power {card.power:,}"[:100],
            )
            for card in cards
        ]
        super().__init__(placeholder="Pick your clubball…", options=options, min_values=1, max_values=1)
        self.on_pick = on_pick

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.on_pick(interaction, int(self.values[0]))


class MatchPickerRow(ActionRow):
    def __init__(self, cards: list[MatchCard], on_pick: PlayCallback):
        super().__init__()
        self.add_item(MatchCardSelect(cards, on_pick))


class MatchBestRow(ActionRow):
    def __init__(self, best: MatchCard, on_pick: PlayCallback):
        super().__init__()
        self.best = best
        self.on_pick = on_pick

    @button(label="Play with my strongest", style=discord.ButtonStyle.success, emoji="\N{FLEXED BICEPS}")
    async def strongest(self, interaction: discord.Interaction, button: Button) -> None:
        await self.on_pick(interaction, self.best.instance_id)


class MatchPickerView(LayoutView):
    """The private panel where a player chooses which clubball plays the match."""

    def __init__(self, match: MatchSpawnView, user_id: int, cards: list[MatchCard]):
        super().__init__(timeout=PICKER_TIMEOUT_SECONDS)
        self.match = match
        self.restrict_author(user_id)
        container = Container(accent_colour=ACCENT_MATCH)
        container.add_item(
            TextDisplay(
                "# \N{SOCCER BALL} Choose your clubball\n"
                f"Opponent power is about **{match.target_power:,}**, each side rolls within ±20%.\n"
                f"-# Showing your {len(cards)} strongest. You only get one try."
            )
        )
        container.add_item(Separator())
        container.add_item(MatchPickerRow(cards, self.play))
        container.add_item(MatchBestRow(cards[0], self.play))
        self.add_item(container)

    async def play(self, interaction: discord.Interaction, instance_id: int) -> None:
        self.stop()
        await self.match.play(interaction, instance_id)


class MatchPlayRow(ActionRow):
    def __init__(self, match: MatchSpawnView):
        super().__init__()
        self.match = match
        self.play.disabled = match.closed
        if match.winner_id is not None:
            self.play.label = "Won!"
        elif match.expired:
            self.play.label = "Over"

    @button(label="Play match", style=discord.ButtonStyle.success, emoji="\N{SOCCER BALL}")
    async def play(self, interaction: discord.Interaction, button: Button) -> None:
        await self.match.open_picker(interaction)


class MatchSpawnView(LayoutView):
    """A spawn where the prize is earned by winning a match instead of guessing a name."""

    def __init__(
        self, bot: BallsDexBot, engine: BallSpawnView, file_name: str, *, target_power: int, algo: str | None
    ) -> None:
        super().__init__(timeout=MATCH_TIMEOUT_SECONDS)
        self.bot = bot
        self.engine = engine
        self.file_name = file_name
        self.target_power = target_power
        self.algo = algo
        self.message: discord.Message = discord.utils.MISSING
        self.attempted: set[int] = set()
        self.winner_id: int | None = None
        self.winner_mention = ""
        self.prize_name = ""
        self.expired = False
        self._render()

    @property
    def closed(self) -> bool:
        return self.winner_id is not None or self.expired

    def _status_line(self) -> str:
        if self.winner_id is not None:
            prize = f"**{self.prize_name}**" if self.prize_name else "the prize"
            return f"\N{TROPHY} {self.winner_mention} won the match and earned {prize}!"
        if self.expired:
            return "\N{HOURGLASS WITH FLOWING SAND} Nobody won this match."
        return ""

    def _render(self) -> None:
        self.clear_items()
        collectible, _ = collectible_names()
        container = Container(accent_colour=ACCENT_MATCH)
        container.add_item(
            TextDisplay(
                "# \N{SOCCER BALL} Match spawn!\n"
                f"A rival club wants a match. **Win it** to earn a **rarer {collectible}** than this one.\n"
                "-# Everyone gets one try, the first win takes the prize."
            )
        )
        container.add_item(MediaGallery(discord.MediaGalleryItem(f"attachment://{self.file_name}")))
        if status := self._status_line():
            container.add_item(TextDisplay(status))
        container.add_item(MatchPlayRow(self))
        self.add_item(container)

    @staticmethod
    def _notice(text: str) -> LayoutView:
        return build_panel_layout(title="Match spawn", sections=[text])

    async def open_picker(self, interaction: discord.Interaction) -> None:
        if self.closed:
            await interaction.response.send_message("This match is already over.", ephemeral=True)
            return
        if interaction.user.id in self.attempted:
            await interaction.response.send_message("You already played this match.", ephemeral=True)
            return
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        cards = await strongest_cards(player)
        if not cards:
            collectible, _ = collectible_names()
            await interaction.response.send_message(
                f"You don't own any {collectible} to play with yet.", ephemeral=True
            )
            return
        await interaction.response.send_message(view=MatchPickerView(self, interaction.user.id, cards), ephemeral=True)

    async def play(self, interaction: discord.Interaction, instance_id: int) -> None:
        """Play the match with one of the player's clubballs and show the outcome on their private panel."""
        user = interaction.user
        await interaction.response.defer()
        if self.closed:
            await interaction.edit_original_response(view=self._notice("This match is already over."))
            return
        if user.id in self.attempted:
            await interaction.edit_original_response(view=self._notice("You already played this match."))
            return

        # one try per player, taken before any await so a double click cannot play twice
        self.attempted.add(user.id)
        try:
            panel = await self._resolve(interaction, instance_id)
        except BaseException:
            self.attempted.discard(user.id)
            raise
        await interaction.edit_original_response(view=panel)

    async def _resolve(self, interaction: discord.Interaction, instance_id: int) -> LayoutView:
        user = interaction.user
        player, _ = await Player.objects.aget_or_create(discord_id=user.id)
        card = await load_card(player, instance_id)
        if card is None:
            self.attempted.discard(user.id)
            return self._notice("That clubball isn't yours or no longer exists.")

        opponent = self.engine.model.country
        roll = roll_match(card.power, self.target_power)
        score = f"Your **{card.country}** scored **{roll.user_roll:,}** vs **{opponent}** **{roll.target_roll:,}**."
        if not roll.won:
            return self._notice(f"\N{CROSS MARK} **Match lost.**\n{score}\n-# Someone else can still win it.")

        reward_ball = pick_match_reward(self.engine.model, await fetch_all_balls())
        reward = new_engine(self.bot, reward_ball, algo=self.algo)
        reward.message = self.message
        pre_catch = await compat.run_hook(
            self.bot, "PreCatchContext", view=reward, interaction=interaction, player=player, guess=reward_ball.country
        )
        if pre_catch is not None and pre_catch.cancelled:
            self.attempted.discard(user.id)
            return self._notice(pre_catch.reason or "You cannot claim this prize right now.")
        if self.closed:
            return self._notice(f"\N{CROSS MARK} **Too slow.** {score}\nSomeone else won this match first.")

        # claim the prize before the next await so two simultaneous winners cannot both be paid
        self.winner_id = user.id
        self.winner_mention = user.mention
        try:
            instance, is_new = await reward.catch_ball(user, player=player, guild=interaction.guild)
        except BaseException:
            self.winner_id = None
            self.winner_mention = ""
            raise

        self.prize_name = reward_ball.country
        content = reward.get_catch_message(instance, is_new, user.mention)
        catch_message = await compat.run_hook(
            self.bot,
            "CatchMessageContext",
            view=reward,
            interaction=interaction,
            player=player,
            ball_instance=instance,
            is_new=is_new,
            content=content,
        )
        if catch_message is not None:
            content = catch_message.content
        await self._announce_win(user, player, opponent, content)
        return self._notice(f"\N{TROPHY} **Match won!**\n{score}\nYou earned **{reward_ball.country}**!\n\n{content}")

    async def _announce_win(
        self, user: discord.User | discord.Member, player: Player, opponent: str, catch_message: str
    ) -> None:
        """Update the spawn message and tell the channel. Failures here never undo the prize."""
        self._render()
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            log.warning("Could not update the match spawn message.", exc_info=True)
        try:
            await self.message.channel.send(
                f"\N{TROPHY} {user.mention} won the match against **{opponent}**!\n{catch_message}",
                allowed_mentions=discord.AllowedMentions(users=player.can_be_mentioned),
            )
        except discord.HTTPException:
            log.warning("Could not announce the match spawn winner.", exc_info=True)

    async def on_timeout(self) -> None:
        if self.winner_id is not None:
            return
        self.expired = True
        self._render()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


async def spawn_match(
    bot: BallsDexBot, channel: discord.abc.GuildChannel, *, algo: str | None = None, rng: random.Random | None = None
) -> bool:
    """Post a match spawn in `channel`. Returns False (after logging) if it could not be posted."""
    try:
        original = pick_match_original(await fetch_all_balls(), rng)
    except ValueError:
        log.info("No spawnable clubball for a match spawn.")
        return False
    if not can_post_spawn(channel):
        log.warning("Missing permission to post a match spawn in channel %s.", channel)
        return False

    config = await get_spawn_config()
    label = f"{algo or 'fcdex'}:match"
    engine = new_engine(bot, original, algo=label)
    file_name = attachment_name(original)
    target_power = match_target_power(original.attack, original.health, config.match_difficulty)
    view = MatchSpawnView(bot, engine, file_name, target_power=target_power, algo=label)
    message = await post_spawn(channel, view, (original,), (file_name,))  # type: ignore[arg-type]
    if message is None:
        return False
    view.message = message
    engine.message = message
    compat.dispatch_ball_spawned(bot, engine, channel)
    return True
