"""Show money the way the BallsDex admin configured it (name, plural, symbol or emoji)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import discord

DEFAULT_CURRENCY_NAME = "coin"


def _host_settings() -> Any | None:
    try:
        from settings.models import settings
    except Exception:
        return None
    return settings


def currency_noun(amount: int) -> str:
    """The configured currency name, singular for exactly one.

    BallsDex has no usable name until the admin sets `currency_name`, so FCDex keeps saying "coins" until then.
    """
    host = _host_settings()
    name = getattr(host, "currency_name", None)
    if not name:
        return DEFAULT_CURRENCY_NAME if amount == 1 else f"{DEFAULT_CURRENCY_NAME}s"
    if amount == 1:
        return name
    return getattr(host, "currency_plural", None) or f"{name}s"


def format_money(amount: int, bot: discord.Client | None = None) -> str:
    """`1,250 coins`, `1,250 FC`, `$1,250` or `1,250 <emoji>` depending on the BallsDex currency settings."""
    humanized = f"{amount:,}"
    host = _host_settings()
    if host is None:
        return f"{humanized} {currency_noun(amount)}"

    emoji = None
    resolve_emoji = getattr(host, "currency_emoji", None)
    if bot is not None and callable(resolve_emoji):
        try:
            emoji = resolve_emoji(bot)
        except Exception:
            emoji = None
    before = bool(getattr(host, "currency_symbol_before", False))
    if emoji:
        return f"{emoji} {humanized}" if before else f"{humanized} {emoji}"

    symbol = getattr(host, "currency_symbol", None)
    if symbol:
        return f"{symbol}{humanized}" if before else f"{humanized}{symbol}"
    return f"{humanized} {currency_noun(amount)}"
