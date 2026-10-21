from __future__ import annotations

import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from fcdex_3_1.fcdex_ext import derby_images  # noqa: E402
from fcdex_3_1.fcdex_ext.derby_images import SlotCard, render_formation_preview, render_squad_image  # noqa: E402
from fcdex_3_1.fcdex_ext.derby_logic import FORMATION_ORDER, get_formation  # noqa: E402

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("key", FORMATION_ORDER)
def test_preview_is_a_png_of_the_pitch_size(key, tmp_path):
    data = render_formation_preview(key)
    assert data.startswith(PNG_MAGIC)
    path = tmp_path / "preview.png"
    path.write_bytes(data)
    with Image.open(path) as image:
        assert image.size == derby_images.PITCH_SIZE


def test_preview_is_cached():
    assert render_formation_preview("4-4-2") is render_formation_preview("4-4-2")


def test_squad_image_uses_card_art_and_falls_back_to_labels(tmp_path):
    art = tmp_path / "card.png"
    Image.new("RGB", (200, 300), (200, 30, 30)).save(art)
    formation = get_formation("4-3-3")
    cards = {
        ("GK", 0): SlotCard("Keeper FC", str(art)),
        ("DF", 0): SlotCard("No Picture FC", str(tmp_path / "missing.png")),
        ("ST", 2): SlotCard("Striker United"),
    }
    data = render_squad_image(formation, cards)
    assert data.startswith(PNG_MAGIC)


def test_empty_squad_image_still_renders():
    assert render_squad_image("5-3-2", {}).startswith(PNG_MAGIC)
