"""합성 ↔ 스마트 크롭 연결 시험.

compose 는 crop_for 가 없으면 지금과 같은 결과를 내야 하고, crop_for 가 실패하면 그 슬롯만 가운데 크롭으로 간다.
장면 시험은 플래그(BOOTH_SMART_CROP)가 꺼져 있으면 완성본 · 축소판이 픽셀까지 그대로인지 본다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pygame
import pytest
from PIL import Image

from walnut.compose import compose, cover_crop
from walnut import framing
from walnut.framing import SmartCropper, compute_crop, home_crop
from walnut.quality import FaceObs
from walnut.scenes.capture import Shoot, cut_thumb
from walnut.scenes.retake import RetakeScene
from walnut.scenes.review import ReviewScene
from walnut.session import ShootSession
from tests.test_app import paired_with_bundle, step  # noqa: F401
from tests.test_touch_app import FakeClock

ROOT = Path(__file__).resolve().parents[2]
FIX = json.loads((ROOT / "shared" / "compose_fixtures.json").read_text(encoding="utf-8"))


def gradient(w=640, h=480, seed=0):
    """위치마다 색이 다른 사진 (크롭 위치가 바뀌면 픽셀이 달라진다)."""
    x = np.linspace(0, 255, w, dtype=np.float32)[None, :]
    y = np.linspace(0, 255, h, dtype=np.float32)[:, None]
    r = np.broadcast_to(x, (h, w))
    g = np.broadcast_to(y, (h, w))
    b = np.full((h, w), (seed * 53) % 256, np.float32)
    return Image.fromarray(np.stack([r, g, b], -1).astype(np.uint8))


def slot(sid, shot, cx, cy, w=150, h=200, rot=0):
    return {"id": sid, "shot": shot, "cx": cx, "cy": cy, "w": w, "h": h, "rot": rot}


def same(a: Image.Image, b: Image.Image) -> bool:
    return a.size == b.size and a.mode == b.mode and a.tobytes() == b.tobytes()


LEFT_FACE = [FaceObs((0.15, 0.2, 0.3, 0.4), None, None)]  # 가운데 크롭 왼쪽 가장자리에 걸친 얼굴


# ---- compose ----
@pytest.mark.parametrize("case", FIX["cases"], ids=lambda c: c["name"])
def test_compose_without_crop_for_matches_fixtures(case):
    s = dict(case["slot"], shot=0)
    pw, ph = case["photo"]["w"], case["photo"]["h"]
    fw = math.ceil(max(abs(x) for x, _ in case["corners"])) + 2
    fh = math.ceil(max(abs(y) for _, y in case["corners"])) + 2
    frame = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    cut = gradient(pw, ph)
    a = compose(frame, [s], [cut])
    b = compose(frame, [s], [cut], crop_for=None)
    c = compose(frame, [s], [cut], crop_for=lambda sl, ct: cover_crop(ct.width, ct.height, sl["w"], sl["h"]))
    assert same(a, b) and same(a, c)


def test_compose_uses_given_crop():
    frame = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    cut = Image.new("RGB", (400, 200), (255, 0, 0))
    cut.paste((0, 0, 255), (0, 0, 200, 200))  # 왼쪽 절반 파랑
    sl = slot("a", 0, 150, 150, 100, 100)
    center = compose(frame, [sl], [cut])
    left = compose(frame, [sl], [cut], crop_for=lambda s, c: (0, 0, 200, 200))
    assert left.getpixel((150, 150)) == (0, 0, 255)
    assert center.getpixel((120, 150)) == (0, 0, 255) and center.getpixel((180, 150)) == (255, 0, 0)


def test_compose_none_from_crop_for_is_center_crop():
    frame = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    slots = [slot("a", 0, 100, 150), slot("b", 1, 300, 150)]
    cuts = [gradient(seed=1), gradient(seed=2)]
    assert same(compose(frame, slots, cuts), compose(frame, slots, cuts, crop_for=lambda s, c: None))


def test_compose_crop_error_falls_back_to_center():
    frame = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    slots = [slot("a", 0, 100, 150), slot("b", 1, 300, 150)]
    cuts = [gradient(seed=1), gradient(seed=2)]

    def boom(s, c):
        if s["id"] == "a":
            raise RuntimeError("분석 실패")
        return (0, 0, 360, 480)

    out = compose(frame, slots, cuts, crop_for=boom)
    want = compose(frame, slots, cuts, crop_for=lambda s, c: None if s["id"] == "a" else (0, 0, 360, 480))
    assert same(out, want)
    # 범위를 벗어난 크롭 · 잘못된 값도 가운데 크롭
    for bad in [(-5, 0, 360, 480), (400, 0, 360, 480), (0, 0, 0, 10), "x", (1, 2, 3)]:
        assert same(compose(frame, slots, cuts, crop_for=lambda s, c, bad=bad: bad), compose(frame, slots, cuts))


def test_one_cut_in_two_slots_gets_a_crop_per_slot():
    frame = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    slots = [slot("a", 0, 100, 150, 100, 100), slot("b", 0, 300, 150, 100, 200)]
    calls = []

    def crop_for(s, c):
        calls.append(s["id"])
        return (0, 0, 100, 100) if s["id"] == "a" else (300, 0, 100, 200)

    cut = gradient(400, 200)
    out = compose(frame, slots, [cut], crop_for=crop_for)
    assert calls == ["a", "b"]
    # a 는 왼쪽 위 (빨강 거의 0), b 는 오른쪽 (빨강 큼)
    assert out.getpixel((100, 150))[0] < 80 and out.getpixel((300, 150))[0] > 180


def test_rotated_slot_with_crop_composes():
    frame = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    sl = {"id": "s", "shot": 0, "cx": 150, "cy": 150, "w": 200, "h": 20, "rot": 90}
    cut = Image.new("RGB", (400, 400), (255, 0, 0))
    cut.paste((0, 255, 0), (0, 0, 400, 40))  # 위쪽 띠만 초록
    out = compose(frame, [sl], [cut], crop_for=lambda s, c: (0, 0, 400, 40))
    assert out.getpixel((150, 60)) == (0, 255, 0) and out.getpixel((150, 240)) == (0, 255, 0)
    assert out.getpixel((60, 150)) == (255, 255, 255)


# ---- SmartCropper ----
def make_session(faces, n=2, extra=0):
    slots = [slot(k + 1, k, 100, 120 + 220 * k) for k in range(n)]
    cap = {"extra_shots": extra, "allow_retake": True, "review_auto_sec": 25, "countdown_sec": 3,
           "between_sec": 1, "mirror": True}
    s = ShootSession({"slots": slots}, cap)
    for k in range(n + extra):
        s.add_shot(gradient(seed=k), faces if k == 0 else None)
    return s


def test_smart_cropper_moves_toward_face_and_falls_back():
    s = make_session(LEFT_FACE)
    frame = Image.new("RGBA", (300, 560), (0, 0, 0, 0))
    sc = SmartCropper(frame, s.frame["slots"], s)
    sl0, sl1 = s.frame["slots"]
    box = sc.crop_for(sl0, s.shots[0])
    want = compute_crop(640, 480, 150, 200, LEFT_FACE, None)
    assert want.reason == "follow"  # 기본 구도 밖 보통 크기 얼굴 — 1.3배 그대로 왼쪽으로 따라간다
    assert (want.w, want.h) == home_crop(640, 480, 150, 200)[2:]
    assert box is not None and box != home_crop(640, 480, 150, 200)
    # 얼굴 정보 없음 → 가장 넓게 (1.0배 가운데) — 사람이 어디 있는지 모르니 자르지 않는다
    c = sc.crop(sl1, s.shots[1])
    assert (c.x, c.y, c.w, c.h) == cover_crop(640, 480, 150, 200)
    assert c.reason == "unavailable" and c.fallback_used is True
    # 이상한 슬롯 (격자 계산 실패) → 가장 넓게
    assert sc.crop_for({**sl0, "w": 0}, s.shots[0]) == cover_crop(640, 480, 0, 200)
    # 그것마저 못 구하면 None (compose 가 가운데 크롭)
    assert sc.crop_for({k: v for k, v in sl0.items() if k != "h"}, s.shots[0]) is None


def test_crop_failure_falls_back_to_widest(monkeypatch):
    s = make_session(LEFT_FACE)
    frame = Image.new("RGBA", (300, 560), (0, 0, 0, 0))
    sc = SmartCropper(frame, s.frame["slots"], s)

    def boom(*a, **k):
        raise RuntimeError("계산 실패")

    monkeypatch.setattr(framing, "compute_crop", boom)
    sl0 = s.frame["slots"][0]
    c = sc.crop(sl0, s.shots[0])
    assert (c.x, c.y, c.w, c.h) == cover_crop(640, 480, 150, 200)
    assert c.reason == "unavailable" and c.fallback_used is True
    # 합성도 그 슬롯을 가장 넓게(가운데 1배) 자른다 = 크롭 없이 합성한 것과 같다
    cuts = s.cuts()
    out = compose(frame, s.frame["slots"], cuts, crop_for=sc.crop_for)
    assert same(out, compose(frame, s.frame["slots"], cuts))


# ---- 장면 ----
@pytest.fixture
def make(make_app, paired_with_bundle):
    def _make(env=None):
        a = make_app(env)
        a.time_fn = clock = FakeClock()
        a._went_at = clock.t - 10
        step(a)
        return a
    return _make


def shoot_with_faces(app, n=2):
    capture = dict(app.bundle.settings["capture"])
    capture["extra_shots"] = 0
    capture["allow_retake"] = True
    s = ShootSession({"slots": [slot(k + 1, k, 100, 120 + 220 * k) for k in range(n)]}, capture)
    for k in range(n):
        s.add_shot(gradient(seed=k), LEFT_FACE)
    return Shoot(s, Image.new("RGBA", (300, 120 + 220 * n), (0, 0, 0, 0)), None, False)


def test_flag_off_review_is_pixel_identical(make):
    app = make()
    sh = shoot_with_faces(app)
    sc = ReviewScene(app, sh)
    assert same(sc.collage, compose(sh.frame_png, sh.session.frame["slots"], sh.session.cuts()))
    assert sh.cropper is None


def test_review_collage_size_and_format_unchanged(make, tmp_path):
    app = make({"BOOTH_SMART_CROP": "1", "BOOTH_CAPTURE_LOG": "1"})
    sh = shoot_with_faces(app)
    sc = ReviewScene(app, sh)
    plain = compose(sh.frame_png, sh.session.frame["slots"], sh.session.cuts())
    assert sc.collage.size == plain.size == sh.frame_png.size and sc.collage.mode == "RGB"
    assert not same(sc.collage, plain)  # 얼굴 쪽으로 옮겨졌다
    lines = [json.loads(x) for x in (tmp_path / "data" / "logs" / "capture_metrics.jsonl")
             .read_text(encoding="utf-8").splitlines()]
    crops = [r for r in lines if r["type"] == "crop"]
    assert [r["slot_index"] for r in crops] == [0, 1]
    for r in crops:
        assert {"slot", "x", "y", "w", "h", "cost", "reason", "fallback_used", "zoom"} <= r.keys()
        assert r["reason"] == "follow" and r["zoom"] == pytest.approx(1.3, abs=0.01)


def thumb_bytes(surf: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surf, "RGB")


def test_retake_thumb_matches_final_crop(make, tmp_path):
    app = make({"BOOTH_SMART_CROP": "1", "BOOTH_CAPTURE_LOG": "1"})
    sh = shoot_with_faces(app)
    review = ReviewScene(app, sh)
    crops = [json.loads(x) for x in (tmp_path / "data" / "logs" / "capture_metrics.jsonl")
             .read_text(encoding="utf-8").splitlines()]
    crops = [r for r in crops if r["type"] == "crop"]
    rt = RetakeScene(app, sh, review.collage)
    s = sh.session
    b, bb = app.stage.tokens["print"]["border"], app.stage.tokens["print"]["border_bottom"]
    for i, (img, r) in enumerate(zip(s.shots, rt.lay.cuts)):
        box = (r.w - 2 * b, r.h - b - bb)
        c = crops[i]
        final = cut_thumb(img, s.ratio_for_shot(i), box, (c["x"], c["y"], c["w"], c["h"]))
        center = cut_thumb(img, s.ratio_for_shot(i), box)
        assert thumb_bytes(rt.thumbs[i]) == thumb_bytes(final)
        assert thumb_bytes(rt.thumbs[i]) != thumb_bytes(center)


def test_flag_off_retake_thumbs_are_center(make):
    app = make()
    sh = shoot_with_faces(app)
    rt = RetakeScene(app, sh, Image.new("RGB", (10, 10)))
    s = sh.session
    b, bb = app.stage.tokens["print"]["border"], app.stage.tokens["print"]["border_bottom"]
    for i, (img, r) in enumerate(zip(s.shots, rt.lay.cuts)):
        center = cut_thumb(img, s.ratio_for_shot(i), (r.w - 2 * b, r.h - b - bb))
        assert thumb_bytes(rt.thumbs[i]) == thumb_bytes(center)
