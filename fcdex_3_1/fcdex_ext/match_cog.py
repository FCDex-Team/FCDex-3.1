from __future__ import annotations

import random
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ballsdex.core.utils.transformers import BallEnabledTransform
from bd_models.models import Ball, BallInstance, Player
from fcdex_3_1.fcdex_ext.views import build_panel_layout

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


def _card_power(instance: BallInstance, ball: Ball) -> int:
    attack = instance.attack + ball.attack
    health = instance.health + ball.health
    return attack * 2 + health


class MatchCog(commands.GroupCog, group_name="match"):
    """Play a clubball match to win a rare clubball."""

    def __init__(self, bot: BallsDexBot):
        self.bot = bot

    @app_commands.command(name="challenge", description="Challenge a rare clubball to a match")
    @app_commands.describe(clubball="The rare clubball you want to win")
    async def challenge(self, interaction: discord.Interaction, clubball: BallEnabledTransform):
        if interaction.guild is None:
            await interaction.response.send_message("Matches can only be played in a server.", ephemeral=True)
            return

        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        owned = [
            inst
            async for inst in BallInstance.objects.filter(player=player, deleted=False)
            .select_related("ball")
            .order_by("-attack_bonus", "-health_bonus")
        ]
        if not owned:
            await interaction.response.send_message("You need at least one clubball to play a match.", ephemeral=True)
            return

        user_instance = owned[0]
        user_ball = user_instance.ball
        user_power = _card_power(user_instance, user_ball)
        target_power = clubball.attack * 2 + clubball.health

        user_roll = int(user_power * random.uniform(0.8, 1.2))
        target_roll = int(target_power * random.uniform(0.8, 1.2))

        if user_roll >= target_roll:
            await BallInstance.objects.acreate(
                ball=clubball, player=player, attack_bonus=0, health_bonus=0, server_id=interaction.guild_id
            )
            result_text = (
                f"🏆 **Match won!**\n"
                f"Your **{user_ball.country}** scored **{user_roll}** vs **{clubball.country}** **{target_roll}**.\n"
                f"You caught **{clubball.country}**!"
            )
        else:
            result_text = (
                f"❌ **Match lost.**\n"
                f"Your **{user_ball.country}** scored **{user_roll}** vs **{clubball.country}** **{target_roll}**.\n"
                f"Better luck next time!"
            )

        layout = build_panel_layout(
            title="FCDex 3.1 · Club match",
            subtitle=f"{user_ball.country} vs {clubball.country}",
            sections=[result_text],
        )
        await interaction.response.send_message(view=layout)  # pyright: ignore[reportArgumentType]
