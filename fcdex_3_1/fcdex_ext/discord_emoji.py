from __future__ import annotations

import re
import unicodedata

_CUSTOM_EMOJI_RE = re.compile(r"^<(?P<animated>a)?:(?P<name>[a-zA-Z0-9_]+):(?P<id>\d+)>$")


def _is_emoji_codepoint(code: int) -> bool:
    return (
        0x1F1E6 <= code <= 0x1F1FF or 0x1F300 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF or 0x2300 <= code <= 0x23FF
    )


def _is_unicode_emoji(text: str) -> bool:
    """True when *text* is Discord-valid Unicode emoji text (not plain words)."""
    if not text or len(text) > 32:
        return False
    compact = "".join(ch for ch in text if not ch.isspace())
    if not compact:
        return False
    if compact.isascii() and compact.isalnum():
        return False
    has_emoji = False
    for ch in text:
        code = ord(ch)
        if ch in "\u200d\u20e3\ufe0f":
            continue
        if unicodedata.category(ch) in ("Mn", "Me"):
            continue
        if _is_emoji_codepoint(code):
            has_emoji = True
            continue
        if unicodedata.category(ch) == "So" and code > 0xFFFF:
            has_emoji = True
            continue
        if "0" <= ch <= "9" and "\u20e3" in text:
            has_emoji = True
            continue
        return False
    return has_emoji


def _has_multiple_emoji(text: str) -> bool:
    """True when *text* contains more than one distinct emoji (flags and ZWJ chains count as one)."""
    if "\u200d" in text:
        return False
    codes = [ord(ch) for ch in text if ch not in "\u20e3\ufe0f" and unicodedata.category(ch) not in ("Mn", "Me")]
    if not codes:
        return False
    regional = [c for c in codes if 0x1F1E6 <= c <= 0x1F1FF]
    other = [c for c in codes if not (0x1F1E6 <= c <= 0x1F1FF)]
    if regional and not other:
        return len(regional) != 2
    if regional and other:
        return True
    return len(other) > 1


def _single_unicode_emoji(text: str) -> str | None:
    stripped = text.strip()
    if not stripped or _CUSTOM_EMOJI_RE.match(stripped):
        return None
    if _has_multiple_emoji(stripped):
        return None
    if _is_unicode_emoji(stripped):
        return stripped
    return None


def unicode_emoji_or_default(raw: str | None, *, default: str) -> str:
    """Pick a single Unicode emoji for labels, never a custom emoji reference."""
    if not raw:
        return default
    return _single_unicode_emoji(raw) or default


def option_label_with_emoji(name: str, raw: str | None, *, default: str = "📦") -> str:
    """Build a select-option label with a safe leading emoji (no ``emoji=`` API field)."""
    icon = unicode_emoji_or_default(raw, default=default)
    return f"{icon} {name}"[:100]


def select_option_emoji(raw: str | None) -> str | None:
    """Return a single Unicode emoji safe for ``SelectOption(emoji=...)``, or ``None`` to omit.

    Custom emoji markup and multi-emoji strings are rejected — Discord often rejects those in
    select menus when the emoji is not available to the application.
    """
    if raw is None:
        return None
    return _single_unicode_emoji(raw.strip())
