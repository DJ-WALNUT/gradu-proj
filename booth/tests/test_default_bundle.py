"""기본 프레임 · 기본 번들 — 연결 없이 시작할 때 쓰는 것."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image

from walnut import default_bundle
from walnut.bundle import BundleStore
from walnut.settings import DEFAULTS, clamp_settings, cut_count

SHARED = Path(__file__).resolve().parents[2] / "shared" / "booth-design" / "default-frame"
COPY = Path(__file__).resolve().parents[1] / "walnut" / "default_frame"


def test_booth_copy_matches_shared():
    for name in ("frame.png", "frame.json"):
        assert (COPY / name).read_bytes() == (SHARED / name).read_bytes()


def test_frame_png_has_holes_at_slot_centers():
    img = Image.open(io.BytesIO(default_bundle.frame_png()))
    assert img.size == (1000, 1500) and img.mode == "RGBA"
    for cx, cy in [(265, 360), (735, 360), (265, 1020), (735, 1020)]:
        assert img.getpixel((cx, cy))[3] == 0
    assert img.getpixel((5, 5))[3] == 255


def test_build_defaults():
    b = default_bundle.build()
    assert (b.version, b.event_id, b.event_name) == (0, 0, "연결 없이 사용")
    assert b.settings == clamp_settings(DEFAULTS)
    assert len(b.frames) == 1 and b.frames[0]["name"] == "기본 프레임"
    assert cut_count(b.frames[0]["slots"]) == 4
    sha = hashlib.sha256(default_bundle.frame_png()).hexdigest()
    assert b.frames[0]["asset"] == sha and b.asset_shas() == [sha]


def test_build_patch_does_not_leak():
    assert default_bundle.build({"capture": {"countdown_sec": 4}}).settings["capture"]["countdown_sec"] == 4
    assert default_bundle.build().settings["capture"]["countdown_sec"] == 10


def test_install_is_idempotent(tmp_path):
    store = BundleStore(tmp_path)
    default_bundle.install(store)
    default_bundle.install(store)
    sha = default_bundle.build().frames[0]["asset"]
    assert store.asset_path(sha).read_bytes() == default_bundle.frame_png()
    assert store.current() is None  # 번들 폴더 · 포인터는 건드리지 않는다
