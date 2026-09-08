from __future__ import annotations

from fcdex_3_1.fcdex_ext.merge_assets import MERGE_CARD_SIZE, merge_card_path, prepare_merge_background
from fcdex_3_1.fcdex_ext.merge_config import MAX_MERGE_LEVEL


def test_merge_card_asset_exists():
    for level in range(1, MAX_MERGE_LEVEL + 1):
        assert merge_card_path(level).is_file()


def test_prepare_merge_background_targets_card_size():
    payload = prepare_merge_background(merge_card_path(1).read_bytes())
    try:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(payload))
        assert image.size == MERGE_CARD_SIZE
    except ImportError:
        assert len(payload) > 0
