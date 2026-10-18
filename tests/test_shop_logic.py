from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from fcdex_3_1.fcdex_ext import shop_logic


class FakePlayer:
    """Follows the money rules of recent BallsDex: zero amounts are rejected, overdrafts raise ValueError."""

    pk = 1

    def __init__(self, money: int):
        self.money = money
        self.charged = 0
        self.refunded = 0

    def can_afford(self, amount: int) -> bool:
        return self.money >= amount

    async def remove_money(self, amount: int) -> None:
        if amount <= 0:
            raise ValueError("Amount to remove must be positive")
        if self.money < amount:
            raise ValueError("Not enough money")
        self.money -= amount
        self.charged += amount

    async def add_money(self, amount: int) -> int:
        if amount <= 0:
            raise ValueError("Amount to add must be positive")
        self.money += amount
        self.refunded += amount
        return self.money


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def select_related(self, *names):
        return self

    def __aiter__(self):
        async def iterate():
            for row in self.rows:
                yield row

        return iterate()


@pytest.fixture
def shop(monkeypatch):
    state = SimpleNamespace(player=FakePlayer(1_000), granted=[], purchases=[], fail_delivery=False)
    item = SimpleNamespace(quantity=2, ball=SimpleNamespace(country="Everton"), special=None, special_id=None)

    missing = type("DoesNotExist", (Exception,), {})

    def make_bundle(price: int) -> SimpleNamespace:
        return SimpleNamespace(pk=7, name="Starter", price=price, enabled=True)

    state.bundle = make_bundle(300)
    state.make_bundle = make_bundle

    class Bundles:
        DoesNotExist = missing

        class objects:
            @staticmethod
            def prefetch_related(*names):
                async def aget(pk):
                    return state.bundle

                return SimpleNamespace(aget=aget)

    async def get_player(pk):
        return state.player

    async def create_ball(**kwargs):
        if state.fail_delivery:
            raise RuntimeError("database down")
        state.granted.append(kwargs["ball"].country)

    async def record_purchase(**kwargs):
        state.purchases.append(kwargs)

    monkeypatch.setattr(shop_logic, "ShopBundle", Bundles)
    monkeypatch.setattr(
        shop_logic, "ShopBundleItem", SimpleNamespace(objects=SimpleNamespace(filter=lambda **kw: FakeQuery([item])))
    )
    monkeypatch.setattr(shop_logic, "Player", SimpleNamespace(objects=SimpleNamespace(aget=get_player)))
    monkeypatch.setattr(shop_logic, "BallInstance", SimpleNamespace(objects=SimpleNamespace(acreate=create_ball)))
    monkeypatch.setattr(shop_logic, "ShopPurchase", SimpleNamespace(objects=SimpleNamespace(acreate=record_purchase)))
    return state


def buy(shop_state) -> tuple[bool, str]:
    return asyncio.run(shop_logic.purchase_bundle(shop_state.player, 7, guild_id=1))  # type: ignore[arg-type]


def test_a_paid_bundle_charges_its_price_and_delivers(shop):
    ok, message = buy(shop)
    assert ok and shop.player.money == 700 and shop.player.charged == 300
    assert shop.granted == ["Everton", "Everton"] and len(shop.purchases) == 1
    assert "300" in message and "700" in message


def test_a_free_bundle_is_delivered_without_moving_any_money(shop):
    shop.bundle = shop.make_bundle(0)
    ok, message = buy(shop)
    assert ok, message
    assert shop.player.money == 1_000 and shop.player.charged == 0
    assert shop.granted == ["Everton", "Everton"]


def test_a_bundle_the_player_cannot_afford_is_refused_before_anything_happens(shop):
    shop.player = FakePlayer(100)
    ok, message = buy(shop)
    assert not ok and "You need" in message and "300" in message and "100" in message
    assert shop.granted == [] and shop.player.charged == 0


def test_a_failed_delivery_refunds_a_paid_bundle(shop):
    shop.fail_delivery = True
    ok, message = buy(shop)
    assert not ok and "not charged" in message
    assert shop.player.money == 1_000 and shop.player.refunded == 300


def test_a_failed_delivery_of_a_free_bundle_has_nothing_to_refund(shop):
    shop.bundle = shop.make_bundle(0)
    shop.fail_delivery = True
    ok, message = buy(shop)
    assert not ok and "not charged" in message
    assert shop.player.refunded == 0


def test_the_shop_listing_shows_the_price_in_the_configured_currency(shop):
    bundle = SimpleNamespace(emoji="🛒", name="Starter", price=1_250, description="")
    line = asyncio.run(shop_logic.format_bundle_line_async(bundle))  # type: ignore[arg-type]
    assert "**1,250 coins**" in line
