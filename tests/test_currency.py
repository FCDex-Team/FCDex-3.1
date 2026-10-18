from __future__ import annotations

from types import SimpleNamespace

import pytest

from fcdex_3_1.fcdex_ext import currency
from fcdex_3_1.fcdex_ext.currency import currency_noun, format_money


def host(**overrides) -> SimpleNamespace:
    values = {
        "currency_name": "coin",
        "currency_plural": "coins",
        "currency_symbol": None,
        "currency_symbol_before": False,
        "currency_emoji": lambda bot: None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def use_host(monkeypatch):
    def apply(value):
        monkeypatch.setattr(currency, "_host_settings", lambda: value)

    return apply


def test_defaults_to_coins_without_host_settings(use_host):
    use_host(None)
    assert format_money(1_250) == "1,250 coins"
    assert format_money(1) == "1 coin"


def test_uses_the_configured_name_and_plural(use_host):
    use_host(host(currency_name="point", currency_plural="points"))
    assert format_money(1) == "1 point"
    assert format_money(0) == "0 points"
    assert format_money(1_000_000) == "1,000,000 points"


def test_plural_falls_back_to_name_with_an_s(use_host):
    use_host(host(currency_name="credit", currency_plural=None))
    assert format_money(5) == "5 credits"


def test_unset_name_keeps_the_coin_default(use_host):
    use_host(host(currency_name=None, currency_plural=None))
    assert currency_noun(1) == "coin"
    assert currency_noun(2) == "coins"


def test_the_hosts_placeholder_plural_is_not_used_before_a_name_is_set(use_host):
    # BallsDex reports "currencies" while currency_name is empty, FCDex keeps saying coins
    use_host(host(currency_name=None, currency_plural="currencies"))
    assert format_money(1_250) == "1,250 coins"


def test_symbol_goes_before_or_after_the_amount(use_host):
    use_host(host(currency_symbol="$", currency_symbol_before=True))
    assert format_money(1_250) == "$1,250"
    use_host(host(currency_symbol="FC", currency_symbol_before=False))
    assert format_money(1_250) == "1,250FC"


def test_emoji_wins_over_the_symbol_when_a_bot_is_given(use_host):
    use_host(host(currency_symbol="$", currency_emoji=lambda bot: "<:fc:1>"))
    assert format_money(50, bot=object()) == "50 <:fc:1>"
    assert format_money(50) == "50$"


def test_emoji_respects_symbol_position(use_host):
    use_host(host(currency_symbol_before=True, currency_emoji=lambda bot: "<:fc:1>"))
    assert format_money(50, bot=object()) == "<:fc:1> 50"


def test_a_broken_emoji_lookup_falls_back_to_the_name(use_host):
    def boom(bot):
        raise RuntimeError("cache not ready")

    use_host(host(currency_emoji=boom))
    assert format_money(7, bot=object()) == "7 coins"
