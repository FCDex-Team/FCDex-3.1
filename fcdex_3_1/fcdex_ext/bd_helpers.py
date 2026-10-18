from __future__ import annotations

from bd_models.models import Ball, BallInstance, balls


async def get_ball(instance: BallInstance) -> Ball:
    if cached := balls.get(instance.ball_id):
        return cached
    return await Ball.objects.aget(pk=instance.ball_id)


def stat_with_bonus(base: int, bonus_percent: int) -> int:
    """A base stat plus its percent bonus, rounded toward zero like BallsDex does."""
    return base + int(base * bonus_percent * 0.01)


def instance_attack(instance: BallInstance, ball: Ball) -> int:
    return stat_with_bonus(ball.attack, instance.attack_bonus)


def instance_health(instance: BallInstance, ball: Ball) -> int:
    return stat_with_bonus(ball.health, instance.health_bonus)


async def format_instance(instance: BallInstance) -> str:
    ball = await get_ball(instance)
    return f"#{instance.pk:0X} {ball.country}"
