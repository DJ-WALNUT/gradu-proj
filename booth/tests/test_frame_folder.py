"""시험용 프레임 폴더 (booth/assets/frame) — 연결 없이 시작 · 개발자 모드가 쓰는 프레임."""

from __future__ import annotations

import hashlib
import json

from PIL import Image, ImageDraw

from walnut import default_bundle
from walnut.bundle import BundleStore

HOLES = [(20, 30, 120, 170), (140, 30, 240, 170), (20, 200, 120, 340), (140, 200, 240, 340)]


def make_frame(path, holes=HOLES, size=(260, 360), specks=()):
    img = Image.new("RGBA", size, (200, 40, 40, 255))
    d = ImageDraw.Draw(img)
    for x0, y0, x1, y1 in holes:
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(0, 0, 0, 0))
    for x, y in specks:
        d.rectangle((x, y, x + 1, y + 1), fill=(0, 0, 0, 0))
    img.save(path)
    return path


def test_detects_slots_from_holes_in_reading_order(tmp_path):
    # 순서를 섞어 그려도 위 줄 왼쪽부터 shot 0, 1, 2, 3
    make_frame(tmp_path / "a.png", holes=[HOLES[3], HOLES[0], HOLES[2], HOLES[1]])
    b = default_bundle.build(frame_dir=tmp_path)
    slots = b.frames[0]["slots"]
    assert [s["shot"] for s in slots] == [0, 1, 2, 3]
    assert [(s["cx"], s["cy"], s["w"], s["h"]) for s in slots] == [
        (70, 100, 100, 140), (190, 100, 100, 140), (70, 270, 100, 140), (190, 270, 100, 140)]
    assert all(s["rot"] == 0 for s in slots)


def test_specks_are_not_slots(tmp_path):
    make_frame(tmp_path / "a.png", specks=[(5, 5), (250, 350)])
    assert len(default_bundle.build(frame_dir=tmp_path).frames[0]["slots"]) == 4


def test_every_png_becomes_a_frame_named_after_file(tmp_path):
    make_frame(tmp_path / "b_party.png")
    make_frame(tmp_path / "a_basic.png", holes=HOLES[:2])
    b = default_bundle.build(frame_dir=tmp_path)
    assert [f["name"] for f in b.frames] == ["a_basic", "b_party"]
    assert [f["id"] for f in b.frames] == [1, 2]
    assert (b.frames[0]["width"], b.frames[0]["height"]) == (260, 360)
    shas = [hashlib.sha256((tmp_path / n).read_bytes()).hexdigest() for n in ("a_basic.png", "b_party.png")]
    assert [f["asset"] for f in b.frames] == shas and sorted(b.asset_shas()) == sorted(shas)


def test_sidecar_json_overrides_detection(tmp_path):
    make_frame(tmp_path / "a.png")
    slots = [{"id": "x", "shot": 0, "cx": 130, "cy": 180, "w": 200, "h": 300, "rot": 5, "ratio": "free"}]
    (tmp_path / "a.json").write_text(json.dumps({"slots": slots}), encoding="utf-8")
    assert default_bundle.build(frame_dir=tmp_path).frames[0]["slots"] == slots


def test_png_without_holes_is_skipped(tmp_path):
    Image.new("RGBA", (100, 100), (1, 2, 3, 255)).save(tmp_path / "solid.png")
    make_frame(tmp_path / "ok.png")
    assert [f["name"] for f in default_bundle.build(frame_dir=tmp_path).frames] == ["ok"]


def test_empty_or_missing_folder_uses_builtin_frame(tmp_path):
    for d in (tmp_path / "missing", tmp_path):
        b = default_bundle.build(frame_dir=d)
        assert [f["name"] for f in b.frames] == ["기본 프레임"]
    Image.new("RGBA", (50, 50), (0, 0, 0, 255)).save(tmp_path / "solid.png")
    assert [f["name"] for f in default_bundle.build(frame_dir=tmp_path).frames] == ["기본 프레임"]


def test_install_writes_every_folder_frame(tmp_path):
    src = tmp_path / "frames"
    src.mkdir()
    make_frame(src / "a.png")
    make_frame(src / "b.png", holes=HOLES[:1])
    store = BundleStore(tmp_path / "data")
    default_bundle.install(store, frame_dir=src)
    for f in default_bundle.build(frame_dir=src).frames:
        assert store.asset_path(f["asset"]).is_file()
    assert store.current() is None


def test_default_folder_is_booth_assets_frame():
    import walnut
    from pathlib import Path
    expected = Path(walnut.__file__).resolve().parents[1] / "assets" / "frame"
    assert default_bundle.DEFAULT_FRAME_DIR == expected
