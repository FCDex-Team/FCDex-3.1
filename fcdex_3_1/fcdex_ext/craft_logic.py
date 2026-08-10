from __future__ import annotations

from bd_models.models import BallInstance, Player, Special
from fcdex_3_1.models import SBCRecipe, SBCRecipeType

CUSTOM_SPECIAL_NAME = "FCDex Custom"
CARD_SPECIAL_NAME = "FCDex Card"


class CraftError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def get_or_create_craft_special(name: str) -> Special:
    special, _ = await Special.objects.aget_or_create(
        name=name, defaults={"rarity": 0.0, "start_date": None, "end_date": None, "hidden": True, "tradeable": True}
    )
    return special


async def _inputs_for_recipe(player: Player, recipe: SBCRecipe):
    if recipe.recipe_type == SBCRecipeType.CUSTOM_TO_CARD:
        custom_special = await get_or_create_craft_special(CUSTOM_SPECIAL_NAME)
        return [
            inst
            async for inst in BallInstance.objects.filter(
                player=player, special_id=custom_special.pk, deleted=False
            ).order_by("pk")[: recipe.required_count]
        ], CUSTOM_SPECIAL_NAME

    return [
        inst
        async for inst in BallInstance.objects.filter(
            player=player, ball_id=recipe.required_ball_id, deleted=False
        ).order_by("pk")[: recipe.required_count]
    ], recipe.required_ball.country


async def complete_sbc(player: Player, recipe: SBCRecipe, *, guild_id: int | None) -> str:
    owned, input_label = await _inputs_for_recipe(player, recipe)
    if len(owned) < recipe.required_count:
        raise CraftError(f"You need **{recipe.required_count}× {input_label}** (you have **{len(owned)}**).")

    ids = [inst.pk for inst in owned]
    updated = await BallInstance.objects.filter(pk__in=ids, player=player, deleted=False).aupdate(deleted=True)
    if updated != len(ids):
        raise CraftError("Some cards were already used — try again.")

    special = None
    if recipe.recipe_type == SBCRecipeType.CLUBBALL_TO_CUSTOM:
        special = await get_or_create_craft_special(CUSTOM_SPECIAL_NAME)
    elif recipe.recipe_type == SBCRecipeType.CUSTOM_TO_CARD:
        special = await get_or_create_craft_special(CARD_SPECIAL_NAME)

    await BallInstance.objects.acreate(
        ball_id=recipe.reward_ball_id,
        player=player,
        attack_bonus=0,
        health_bonus=0,
        server_id=guild_id,
        special=special,
    )
    if recipe.reward_money:
        await player.add_money(recipe.reward_money)

    reward = recipe.reward_ball
    reward_name = reward.country if hasattr(reward, "country") else f"ball #{recipe.reward_ball_id}"
    tag = ""
    if recipe.recipe_type == SBCRecipeType.CLUBBALL_TO_CUSTOM:
        tag = " (Custom)"
    elif recipe.recipe_type == SBCRecipeType.CUSTOM_TO_CARD:
        tag = " (Card)"
    parts = [f"**{recipe.name}** complete! Received **{reward_name}{tag}**"]
    if recipe.reward_money:
        parts.append(f"**+{recipe.reward_money:,}** coins")
    return " · ".join(parts)
