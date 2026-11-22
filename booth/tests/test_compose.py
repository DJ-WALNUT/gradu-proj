"""자유 슬롯 합성: 공유 기하 기대값, 회전 방향, 프레임 합성 순서."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from walnut.compose import compose, cover_crop, save_jpeg, slot_corners

ROOT = Path(__file__).resolve().parents[2]
FIX = json.loads((ROOT / "shared" / "compose_fixtures.json").read_text(encoding="utf-8"))


def transparent_frame(w, h):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def solid(rgb, size=(200, 200)):
    return Image.new("RGB", size, rgb)


def slot(sid, shot, cx, cy, w=60, h=60, rot=0):
    return {"id": sid, "shot": shot, "cx": cx, "cy": cy, "w": w, "h": h, "rot": rot}


def frame_with_opaque_band(w, h, y0, y1, rgb):
    f = transparent_frame(w, h)
    f.paste(Image.new("RGBA", (w, y1 - y0), (*rgb, 255)), (0, y0))
    return f


@pytest.mark.parametrize("case", FIX["cases"], ids=lambda c: c["name"])
def test_shared_fixture_geometry(case):
    for (x, y), (ex, ey) in zip(slot_corners(case["slot"]), case["corners"]):
        assert abs(x - ex) < 1e-6 and abs(y - ey) < 1e-6
    c = case["crop"]
    assert cover_crop(case["photo"]["w"], case["photo"]["h"], case["slot"]["w"], case["slot"]["h"]) == (c["x"], c["y"], c["w"], c["h"])


def test_cover_crop_min_one_pixel():
    x, y, w, h = cover_crop(1440, 1080, 1, 4000)
    assert w >= 1 and h == 1080 and x >= 0


def test_same_cut_in_two_slots():
    out = compose(transparent_frame(400, 300), [slot("a", 0, 100, 100), slot("b", 0, 300, 100), slot("c", 1, 200, 220)],
                  [solid((255, 0, 0)), solid((0, 0, 255))])
    assert out.mode == "RGB" and out.size == (400, 300)
    assert out.getpixel((100, 100)) == (255, 0, 0) == out.getpixel((300, 100))
    assert out.getpixel((200, 220)) == (0, 0, 255)


def test_rotated_slot_clockwise():
    out = compose(transparent_frame(300, 300), [{"id": "s", "shot": 0, "cx": 150, "cy": 150, "w": 200, "h": 20, "rot": 90}], [solid((0, 255, 0))])
    assert out.getpixel((150, 60)) == (0, 255, 0) and out.getpixel((60, 150)) == (255, 255, 255)


def test_rotation_sign_is_clockwise_on_screen():
    # 왼쪽 빨강 / 오른쪽 초록 컷. 시계 방향 90° 면 왼쪽(빨강)이 위로 간다.
    cut = Image.new("RGB", (200, 200), (255, 0, 0))
    cut.paste(Image.new("RGB", (100, 200), (0, 255, 0)), (100, 0))
    out = compose(transparent_frame(300, 300), [slot("s", 0, 150, 150, 160, 160, 90)], [cut])
    assert out.getpixel((150, 100)) == (255, 0, 0)
    assert out.getpixel((150, 200)) == (0, 255, 0)


def test_rot30_fills_slot_corner_not_mirror():
    # rot=30 슬롯의 우상단 꼭짓점 안쪽은 채워지고, 반대 방향으로 돌렸다면 채워질 자리는 비어야 한다.
    s = slot("s", 0, 200, 200, 200, 100, 30)
    out = compose(transparent_frame(400, 400), [s], [solid((255, 0, 0))])
    (x0, y0), (x1, y1), (x2, y2), _ = slot_corners(s)
    cx, cy = 200, 200
    inset = lambda x, y: (int(cx + (x - cx) * 0.95), int(cy + (y - cy) * 0.95))
    assert out.getpixel(inset(x1, y1)) == (255, 0, 0)       # 우상 꼭짓점 (시계 방향으로 내려간 쪽)
    assert out.getpixel(inset(x2, y2)) == (255, 0, 0)
    mx, my = cx + (x1 - cx), cy - (y1 - cy)                 # 반시계로 돌렸을 때의 우상 꼭짓점
    assert out.getpixel(inset(mx, my)) == (255, 255, 255)


def test_frame_drawn_over_photo_and_background_white():
    frame = frame_with_opaque_band(400, 300, 90, 110, (0, 0, 255))
    out = compose(frame, [slot("a", 0, 100, 100, 100, 100)], [solid((255, 0, 0))])
    assert out.getpixel((100, 100)) == (0, 0, 255)      # 프레임 불투명 영역이 사진 위
    assert out.getpixel((100, 60)) == (255, 0, 0)       # 사진
    assert out.getpixel((350, 250)) == (255, 255, 255)  # 슬롯 밖 투명 영역은 흰색


def test_save_jpeg_atomic(tmp_path):
    p = tmp_path / "sub" / "a.jpg"
    p.parent.mkdir()
    save_jpeg(Image.new("RGB", (20, 20), (10, 20, 30)), p)
    assert Image.open(p).format == "JPEG"
    assert [f.name for f in p.parent.iterdir()] == ["a.jpg"]
