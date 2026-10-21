"""Pitch pictures for FC Derby, drawn at runtime with Pillow (a BallsDex dependency, imported lazily).

Drawing is CPU work, call the render functions through `asyncio.to_thread` from async code.
"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from typing import Any

from fcdex_3_1.fcdex_ext.derby_logic import FORMATIONS, Formation, get_formation

log = logging.getLogger("fcdex_3_1.derby.images")

PITCH_SIZE = (640, 880)
PITCH_MARGIN = 28
CARD_SIZE = 84

GRASS_DARK = (34, 120, 58)
GRASS_LIGHT = (40, 134, 66)
LINE_COLOR = (235, 245, 235)
POSITION_COLORS: dict[str, tuple[int, int, int]] = {
    "GK": (240, 190, 40),
    "DF": (60, 130, 220),
    "MF": (70, 190, 110),
    "ST": (225, 70, 70),
}

_preview_cache: dict[str, bytes] = {}


@dataclass(frozen=True, slots=True)
class SlotCard:
    """What to draw in one slot: a label and, when there is a picture file, its path."""

    label: str
    art_path: str | None = None


def _pillow() -> tuple[Any, Any, Any]:
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _font(size: int) -> Any:
    _, _, ImageFont = _pillow()
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow older than 10.1 has a single fixed size
        return ImageFont.load_default()


def _pitch(Image: Any, ImageDraw: Any) -> tuple[Any, Any]:
    width, height = PITCH_SIZE
    image = Image.new("RGB", (width, height), GRASS_DARK)
    draw = ImageDraw.Draw(image)
    stripe = (height - 2 * PITCH_MARGIN) // 10
    for i in range(10):
        if i % 2:
            top = PITCH_MARGIN + i * stripe
            draw.rectangle((PITCH_MARGIN, top, width - PITCH_MARGIN, top + stripe), fill=GRASS_LIGHT)

    left, top, right, bottom = PITCH_MARGIN, PITCH_MARGIN, width - PITCH_MARGIN, height - PITCH_MARGIN
    draw.rectangle((left, top, right, bottom), outline=LINE_COLOR, width=3)
    mid_y = height // 2
    draw.line((left, mid_y, right, mid_y), fill=LINE_COLOR, width=3)
    radius = 70
    draw.ellipse(
        (width // 2 - radius, mid_y - radius, width // 2 + radius, mid_y + radius), outline=LINE_COLOR, width=3
    )
    box_w, box_h = 280, 120
    small_w, small_h = 130, 48
    for edge_top in (True, False):
        y0 = top if edge_top else bottom - box_h
        draw.rectangle((width // 2 - box_w // 2, y0, width // 2 + box_w // 2, y0 + box_h), outline=LINE_COLOR, width=3)
        y1 = top if edge_top else bottom - small_h
        draw.rectangle(
            (width // 2 - small_w // 2, y1, width // 2 + small_w // 2, y1 + small_h), outline=LINE_COLOR, width=3
        )
    return image, draw


def slot_pixel(x: float, y: float) -> tuple[int, int]:
    """Pitch pixel for a formation coordinate (both 0..1)."""
    width, height = PITCH_SIZE
    inner_w, inner_h = width - 2 * PITCH_MARGIN - 20, height - 2 * PITCH_MARGIN - 120
    return int(PITCH_MARGIN + 10 + x * inner_w), int(PITCH_MARGIN + 60 + y * inner_h)


def _to_png(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _centered_text(draw: Any, center: tuple[int, int], text: str, font: Any, fill: Any) -> None:
    # Measured by hand because bitmap fonts (older Pillow) do not support text anchors.
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text((center[0] - (right - left) / 2 - left, center[1] - (bottom - top) / 2 - top), text, font=font, fill=fill)


def render_formation_preview(formation_key: str) -> bytes:
    """PNG of the empty formation: coloured dots with their slot names. Cached in memory."""
    formation = get_formation(formation_key)
    cached = _preview_cache.get(formation.key)
    if cached is not None:
        return cached

    Image, ImageDraw, _ = _pillow()
    image, draw = _pitch(Image, ImageDraw)
    title_font, dot_font = _font(30), _font(20)
    width = PITCH_SIZE[0]
    for position, slot, x, y in formation.layout():
        cx, cy = slot_pixel(x, y)
        r = 30
        draw.ellipse((cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3), fill=(255, 255, 255))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=POSITION_COLORS[position])
        _centered_text(draw, (cx, cy), f"{position}{slot + 1}", dot_font, (255, 255, 255))
    draw.rectangle((width // 2 - 90, 34, width // 2 + 90, 80), fill=(0, 0, 0))
    _centered_text(draw, (width // 2, 57), formation.key, title_font, (255, 255, 255))

    data = _to_png(image)
    _preview_cache[formation.key] = data
    return data


def prime_previews() -> None:
    """Render every formation once so the first `/fc derby layouts` is instant."""
    for key in FORMATIONS:
        render_formation_preview(key)


def ball_art_path(ball: Any) -> str | None:
    """Path of a clubball's card picture (collection card first, then wild card), or None when no file exists."""
    for attribute in ("collection_card", "wild_card"):
        field = getattr(ball, attribute, None)
        if not field or not getattr(field, "name", ""):
            continue
        try:
            path = str(field.path)
        except Exception:
            continue
        if os.path.exists(path):
            return path
    return None


def _load_art(Image: Any, path: str | None) -> Any | None:
    if not path:
        return None
    try:
        with Image.open(path) as source:
            art = source.convert("RGBA")
    except Exception:
        log.debug("Could not open card art %s", path, exc_info=True)
        return None
    side = min(art.size)
    left, top = (art.width - side) // 2, (art.height - side) // 2
    return art.crop((left, top, left + side, top + side)).resize((CARD_SIZE, CARD_SIZE))


def _short(label: str, limit: int = 13) -> str:
    return label if len(label) <= limit else label[: limit - 1] + "…"


def render_squad_image(formation: Formation | str, cards: dict[tuple[str, int], SlotCard]) -> bytes:
    """PNG of a squad on the pitch. Empty slots stay dots, a missing picture falls back to a name label."""
    formation = get_formation(formation) if isinstance(formation, str) else formation
    Image, ImageDraw, _ = _pillow()
    image, draw = _pitch(Image, ImageDraw)
    title_font, name_font, dot_font = _font(30), _font(17), _font(20)
    width = PITCH_SIZE[0]
    half = CARD_SIZE // 2

    for position, slot, x, y in formation.layout():
        cx, cy = slot_pixel(x, y)
        card = cards.get((position, slot))
        color = POSITION_COLORS[position]
        if card is None:
            r = 26
            draw.ellipse((cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3), fill=(255, 255, 255))
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
            _centered_text(draw, (cx, cy), f"{position}{slot + 1}", dot_font, (255, 255, 255))
            continue

        box = (cx - half, cy - half, cx + half, cy + half)
        draw.rounded_rectangle((box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4), radius=12, fill=color)
        art = _load_art(Image, card.art_path)
        if art is not None:
            image.paste(art, (box[0], box[1]), art)
        else:
            draw.rounded_rectangle(box, radius=10, fill=(30, 30, 30))
            _centered_text(draw, (cx, cy), _short(card.label, 9), name_font, (255, 255, 255))
        tag_y = box[3] + 16
        text = _short(card.label)
        tag_w = int(draw.textlength(text, font=name_font)) + 12
        draw.rounded_rectangle((cx - tag_w // 2, tag_y - 11, cx + tag_w // 2, tag_y + 11), radius=6, fill=(0, 0, 0))
        _centered_text(draw, (cx, tag_y), text, name_font, (255, 255, 255))

    draw.rectangle((width // 2 - 90, 34, width // 2 + 90, 80), fill=(0, 0, 0))
    _centered_text(draw, (width // 2, 57), formation.key, title_font, (255, 255, 255))
    return _to_png(image)
