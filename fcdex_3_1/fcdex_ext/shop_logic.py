from __future__ import annotations

import logging

from bd_models.models import BallInstance, Player
from fcdex_3_1.models import ShopBundle, ShopBundleItem, ShopPurchase

log = logging.getLogger("fcdex_3_1.shop")


async def list_shop_bundles(*, enabled_only: bool = True) -> list[ShopBundle]:
    qs = ShopBundle.objects.prefetch_related("items__ball")
    if enabled_only:
        qs = qs.filter(enabled=True)
    return [b async for b in qs.order_by("sort_order", "name")]


async def format_bundle_line_async(bundle: ShopBundle) -> str:
    lines: list[str] = []
    async for item in ShopBundleItem.objects.filter(bundle=bundle).select_related("ball", "special"):
        tag = f" ({item.special.name})" if item.special_id else ""
        lines.append(f"**{item.quantity}×** {item.ball.country}{tag}")
    reward = ", ".join(lines) if lines else "*no items configured*"
    emoji = bundle.emoji or "🛒"
    desc = f"\n{bundle.description}" if bundle.description else ""
    return f"{emoji} **{bundle.name}** — **{bundle.price:,}** coins\n{reward}{desc}"


async def purchase_bundle(player: Player, bundle_id: int, *, guild_id: int | None) -> tuple[bool, str]:
    try:
        bundle = await ShopBundle.objects.prefetch_related("items__ball").aget(pk=bundle_id)
    except ShopBundle.DoesNotExist:
        return False, "That bundle no longer exists."

    if not bundle.enabled:
        return False, f"**{bundle.name}** is not available right now."

    items = [item async for item in ShopBundleItem.objects.filter(bundle=bundle).select_related("ball", "special")]
    if not items:
        return False, f"**{bundle.name}** has no rewards configured yet."

    player = await Player.objects.aget(pk=player.pk)
    if not player.can_afford(bundle.price):
        return False, f"You need **{bundle.price:,}** coins (balance: **{player.money:,}**)."

    try:
        await player.remove_money(bundle.price)
    except ValueError:
        return False, f"You need **{bundle.price:,}** coins (balance: **{player.money:,}**)."

    granted: list[str] = []
    try:
        for item in items:
            for _ in range(item.quantity):
                await BallInstance.objects.acreate(
                    ball=item.ball,
                    player=player,
                    attack_bonus=0,
                    health_bonus=0,
                    server_id=guild_id,
                    special=item.special,
                )
            tag = f" ({item.special.name})" if item.special_id else ""
            granted.append(f"**{item.quantity}×** {item.ball.country}{tag}")
        await ShopPurchase.objects.acreate(player=player, bundle=bundle)
    except Exception:
        log.exception("Shop purchase delivery failed for player %s bundle %s — refunding.", player.pk, bundle.pk)
        await player.add_money(bundle.price)
        return False, "Purchase failed while delivering items — your coins were refunded."

    player = await Player.objects.aget(pk=player.pk)
    return True, (
        f"Purchased **{bundle.name}** for **{bundle.price:,}** coins!\n"
        f"Received: {', '.join(granted)}\n"
        f"-# Balance: **{player.money:,}** coins"
    )
