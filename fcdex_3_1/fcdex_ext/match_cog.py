from __future__ import annotations

import random
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ballsdex.core.utils.transformers import BallEnabledTransform, BallInstanceTransform
from bd_models.models import Ball, BallInstance, Player
from fcdex_3_1.fcdex_ext.bd_helpers import get_ball
from fcdex_3_1.fcdex_ext.tournament_loot import _pick_random_common_ball
from fcdex_3_1.fcdex_ext.views import build_panel_layout

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

MATCH_CHALLENGE_COST = 1000


def _card_power(instance: BallInstance, ball: Ball) -> int:
    attack = instance.attack + ball.attack
    health = instance.health + ball.health
    return attack * 2 + health


class MatchCog(commands.GroupCog, group_name="match"):
    """Play a clubball match to win a rare clubball."""

    def __init__(self, bot: BallsDexBot):
        self.bot = bot

    @app_commands.command(name="challenge", description="Challenge a rare clubball to a match (costs coins)")
    @app_commands.describe(
        clubball="The rare clubball you want to win", my_clubball="Your clubball to play the match with"
    )
    async def challenge(
        self, interaction: discord.Interaction, clubball: BallEnabledTransform, my_clubball: BallInstanceTransform
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Matches can only be played in a server.", ephemeral=True)
            return

        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)

        if my_clubball.deleted:
            await interaction.response.send_message("That clubball is no longer available.", ephemeral=True)
            return
        if my_clubball.player_id != player.pk:
            await interaction.response.send_message("That clubball doesn't belong to you.", ephemeral=True)
            return

        player = await Player.objects.aget(pk=player.pk)
        if not player.can_afford(MATCH_CHALLENGE_COST):
            await interaction.response.send_message(
                f"You need **{MATCH_CHALLENGE_COST:,}** coins to play a match (balance: **{player.money:,}**).",
                ephemeral=True,
            )
            return
        await player.remove_money(MATCH_CHALLENGE_COST)

        user_ball = await get_ball(my_clubball)
        user_power = _card_power(my_clubball, user_ball)
        target_power = clubball.attack * 2 + clubball.health

        user_roll = int(user_power * random.uniform(0.8, 1.2))
        target_roll = int(target_power * random.uniform(0.8, 1.2))

        if user_roll >= target_roll:
            reward_ball = await _pick_random_common_ball()
            if reward_ball is None:
                await interaction.response.send_message(
                    "No enabled common clubballs are available for rewards.", ephemeral=True
                )
                return
            await BallInstance.objects.acreate(
                ball=reward_ball, player=player, attack_bonus=0, health_bonus=0, server_id=interaction.guild_id
            )
            result_text = (
                f"🏆 **Match won!**\n"
                f"Your **{user_ball.country}** scored **{user_roll}** vs **{clubball.country}** **{target_roll}**.\n"
                f"You won a random **{reward_ball.country}** clubball!\n"
                f"-# Paid **{MATCH_CHALLENGE_COST:,}** coins · Balance: **{player.money:,}**"
            )
        else:
            result_text = (
                f"❌ **Match lost.**\n"
                f"Your **{user_ball.country}** scored **{user_roll}** vs **{clubball.country}** **{target_roll}**.\n"
                f"Better luck next time!\n"
                f"-# Paid **{MATCH_CHALLENGE_COST:,}** coins · Balance: **{player.money:,}**"
            )

        layout = build_panel_layout(
            title="FCDex 3.1 · Club match",
            subtitle=f"{user_ball.country} vs {clubball.country}",
            sections=[result_text],
        )
        await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]
