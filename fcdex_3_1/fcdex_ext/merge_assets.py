from __future__ import annotations

import io
import logging
import re
from importlib.resources import files
from pathlib import Path

from fcdex_3_1.fcdex_ext.merge_config import MAX_MERGE_LEVEL

log = logging.getLogger("fcdex_3_1.merge.assets")

MERGE_CARD_SIZE = (1428, 2000)
MERGE_LEVEL_FILE = re.compile(r"^merge-level(\d+)\.(jpg|jpeg|png|webp)$", re.IGNORECASE)


def merge_background_filename(level: int) -> str:
    return f"fcdex_merge_l{level}_background.png"


def merge_card_path(level: int) -> Path:
    if level < 1 or level > MAX_MERGE_LEVEL:
        raise ValueError(f"Invalid merge level: {level}")
    base = Path(str(files("fcdex_3_1").joinpath("media")))
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = base / f"merge-level{level}{ext}"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Merge card asset missing for L{level} under {base}")


def list_merge_card_levels() -> list[int]:
    base = Path(str(files("fcdex_3_1").joinpath("media")))
    levels: set[int] = set()
    if not base.is_dir():
        return []
    for path in base.iterdir():
        match = MERGE_LEVEL_FILE.match(path.name)
        if match:
            levels.add(int(match.group(1)))
    return sorted(level for level in levels if 1 <= level <= MAX_MERGE_LEVEL)


def prepare_merge_background(raw: bytes) -> bytes:
    try:
        from PIL import Image  # pyright: ignore[reportMissingImports]
    except ImportError:
        log.warning("Pillow not installed — using merge card as-is; card renderer expects 1428×2000.")
        return raw

    image = Image.open(io.BytesIO(raw))
    if image.size != MERGE_CARD_SIZE:
        image = image.resize(MERGE_CARD_SIZE, Image.Resampling.LANCZOS)
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def read_merge_card(level: int) -> bytes:
    path = merge_card_path(level)
    return prepare_merge_background(path.read_bytes())
