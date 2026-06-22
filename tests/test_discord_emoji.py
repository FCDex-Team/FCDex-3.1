from __future__ import annotations

from fcdex_3_1.fcdex_ext.discord_emoji import (
    option_label_with_emoji,
    select_option_emoji,
    unicode_emoji_or_default,
)


def test_select_option_emoji_rejects_plain_text() -> None:
    assert select_option_emoji("Boss") is None
    assert select_option_emoji("  ") is None
    assert select_option_emoji(None) is None


def test_select_option_emoji_rejects_custom_markup() -> None:
    assert select_option_emoji("<:trophy:123456789012345678>") is None
    assert select_option_emoji("<a:spin:987654321098765432>") is None


def test_select_option_emoji_rejects_multi_emoji() -> None:
    assert select_option_emoji("🔥✨") is None


def test_select_option_emoji_accepts_single_unicode() -> None:
    assert select_option_emoji("\U0001f3c6") == "\U0001f3c6"
    assert select_option_emoji(" 🛒 ") == "🛒"


def test_unicode_emoji_or_default_falls_back() -> None:
    assert unicode_emoji_or_default("Boss", default="🛒") == "🛒"
    assert unicode_emoji_or_default("<:x:1>", default="🛒") == "🛒"
    assert unicode_emoji_or_default("💰", default="🛒") == "💰"


def test_option_label_with_emoji_prefixes_name() -> None:
    assert option_label_with_emoji("Starter Pack", "💰", default="🛒").startswith("💰 Starter")
    assert option_label_with_emoji("Starter Pack", "invalid", default="🛒").startswith("🛒 Starter")
