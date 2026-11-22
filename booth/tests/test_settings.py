from __future__ import annotations

from walnut import config
from walnut.settings import DEFAULTS, clamp_settings, cut_count, cut_ratios, preview_ratio


def test_clamp_ranges():
    s = clamp_settings({"capture": {"countdown_sec": 99, "between_sec": -1, "extra_shots": 9}, "sync": {"interval_sec": 1}})
    assert s["capture"]["countdown_sec"] == 30 and s["capture"]["between_sec"] == 0
    assert s["capture"]["extra_shots"] == 6 and s["sync"]["interval_sec"] == 10


def test_clamp_fills_missing_and_ignores_unknown():
    s = clamp_settings({"capture": {"countdown_sec": "10", "future_key": 1}, "new_section": {}})
    assert s["capture"]["countdown_sec"] == 10 and "future_key" not in s["capture"] and "new_section" not in s
    assert s["share"] == DEFAULTS["share"] and clamp_settings(None) == DEFAULTS
    assert clamp_settings({"capture": {"countdown_sec": True}})["capture"]["countdown_sec"] == 10  # bool 은 숫자 아님


def test_filters_enabled_unknown_dropped_never_empty():
    assert clamp_settings({"filters": {"enabled": ["sepia", "mono"]}})["filters"]["enabled"] == ["mono"]
    assert clamp_settings({"filters": {"enabled": []}})["filters"]["enabled"] == ["original"]
    assert clamp_settings({"filters": {"enabled": ["warm", "mono", "warm"]}})["filters"]["enabled"] == ["warm", "mono"]


def test_stickers_clamped_and_bad_items_dropped():
    good = {"id": "a", "name": "별", "asset": "x" * 64, "anchor": "eyes", "scale": 9, "offset": [5, -5]}
    bad_anchor = dict(good, id="b", anchor="head")
    s = clamp_settings({"stickers": {"enabled": True, "items": [good, bad_anchor, "x", dict(good)]}})
    assert s["stickers"]["enabled"] is True
    assert len(s["stickers"]["items"]) == 1
    it = s["stickers"]["items"][0]
    assert it["scale"] == 3.0 and it["offset"] == [2.0, -2.0]


def test_cut_rules():
    slots = [{"shot": 1, "w": 300, "h": 400}, {"shot": 0, "w": 400, "h": 300}, {"shot": 0, "w": 100, "h": 100},
             {"shot": 2, "w": 300, "h": 400}]
    assert cut_count(slots) == 3
    assert cut_ratios(slots) == [400 / 300, 300 / 400, 300 / 400]
    assert preview_ratio(slots) == 300 / 400


def test_preview_ratio_counts_all_slots_and_ties_to_earliest():
    # 컷 비율로는 1:1 이 우세하지만 모든 슬롯으로 세면 3:4 가 3개
    slots = [{"shot": 0, "w": 100, "h": 100}, {"shot": 1, "w": 100, "h": 100},
             {"shot": 0, "w": 300, "h": 400}, {"shot": 0, "w": 300, "h": 400}, {"shot": 1, "w": 300, "h": 400}]
    assert preview_ratio(slots) == 0.75
    tie = [{"shot": 0, "w": 100, "h": 100}, {"shot": 1, "w": 300, "h": 400}]
    assert preview_ratio(tie) == 1.0


def test_config_bad_int_uses_default(tmp_path):
    c = config.load({"CAMERA_INDEX": "x", "SERVER_URL": "https://a.b/", "SYNC_INTERVAL": ""}, root=tmp_path)
    assert c.camera_index == 0 and c.server_url == "https://a.b" and c.sync_interval is None
