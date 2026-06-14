from __future__ import annotations

from fcdex_3_1.fcdex_ext.merge_assets import list_merge_card_levels, merge_card_path
from fcdex_3_1.fcdex_ext.merge_config import MAX_MERGE_LEVEL
from fcdex_3_1.fcdex_ext.merge_special import is_merge_special_name, merge_special_name, parse_merge_special_level


def test_merge_special_names_for_all_levels():
    assert merge_special_name(1) == "FCDex Merge"
    assert merge_special_name(2) == "FCDex Merge L2"
    assert merge_special_name(7) == "FCDex Merge L7"


def test_is_merge_special_name():
    assert is_merge_special_name("FCDex Merge")
    assert is_merge_special_name("FCDex Merge L3")
    assert not is_merge_special_name("Boss")
    assert not is_merge_special_name("FCDex Merge L8")


def test_parse_merge_special_level():
    assert parse_merge_special_level("FCDex Merge") == 1
    assert parse_merge_special_level("FCDex Merge L5") == 5
    assert parse_merge_special_level("Other") is None


def test_all_merge_card_assets_exist():
    levels = list_merge_card_levels()
    assert levels == list(range(1, MAX_MERGE_LEVEL + 1))
    for level in range(1, MAX_MERGE_LEVEL + 1):
        assert merge_card_path(level).is_file()
