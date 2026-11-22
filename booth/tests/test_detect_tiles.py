"""광각 · 단체용 검출 전략 (전체 · 겹치는 좌우 반쪽) 시험.

가짜 landmarker 는 '세상' 에 놓인 얼굴들(전체 프레임 정규화 좌표)을 알고 있다.
입력 그림의 G 채널에 원래 x 화소 번호를 심어 두어, 어떤 조각(시작 x · 폭)이 들어왔는지 알아낸다.
조각 안에 통째로 들어온 얼굴 중, 조각 폭 대비 얼굴 폭이 min_frac 이상인 것만 '검출' 한다
(작은 얼굴은 전체 화면에서 놓치는 실제 검출기 흉내).
"""

from __future__ import annotations

import csv
from types import SimpleNamespace as P

import numpy as np
import pytest

from facekit import fake_face, with_eyes
from tools import compare_detect as cd
from tools import record_burst as rb
from walnut import analysis
from walnut.analysis import BurstAnalyzer, detect_tiles
from walnut.burst import TimedFrame
from walnut.quality import FaceObs, eye_open_from

W, H = 240, 120  # 조각: 왼쪽 [0,156) · 오른쪽 [84,240)


def frame(t=0.0):
    rgb = np.zeros((H, W, 3), np.uint8)
    rgb[:, :, 1] = np.arange(W, dtype=np.uint8)[None, :]  # G = 원래 x
    return TimedFrame(t, rgb)


def world_face(cx, w=0.16, ratio=0.35):
    """전체 프레임 정규화 좌표의 얼굴 (눈 점 포함). with_eyes 는 가운데(0.5) 기준이라 통째로 옮긴다."""
    pts = with_eyes(fake_face(cx=0.5, cy=0.5, w=w), ratio, aspect=W / H)
    return [P(x=p.x + (cx - 0.5), y=p.y) for p in pts]


def box_of(pts):
    xs, ys = [p.x for p in pts], [p.y for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


class TileLandmarker:
    def __init__(self, faces, min_frac=0.0, fail_ox=None):
        self.faces = faces          # 전체 프레임 좌표 얼굴 목록
        self.min_frac = min_frac
        self.fail_ox = fail_ox
        self.calls = []             # (ox, tw)

    def detect(self, image):
        img = np.asarray(image.numpy_view())
        ox, tw = int(img[0, 0, 1]), img.shape[1]
        self.calls.append((ox, tw))
        if self.fail_ox is not None and ox == self.fail_ox:
            raise RuntimeError("조각 검출 실패")
        out = []
        for pts in self.faces:
            x0, _, x1, _ = box_of(pts)
            px0, px1 = x0 * W, x1 * W
            if px0 < ox or px1 > ox + tw:
                continue  # 조각 밖으로 나간 얼굴
            if (px1 - px0) / tw < self.min_frac:
                continue  # 너무 작아 놓침
            out.append([P(x=(p.x * W - ox) / tw, y=p.y) for p in pts])
        return P(face_landmarks=out, face_blendshapes=[],
                 facial_transformation_matrixes=[np.eye(4) for _ in out])

    def close(self):
        pass


def run(faces, mode, *, min_frac=0.0, fail_ox=None, mirror=False, max_faces=4):
    lm = TileLandmarker(faces, min_frac, fail_ox)
    an = BurstAnalyzer(analysis.Path("none.task"), max_faces=max_faces, landmarker=lm, detect_mode=mode)
    try:
        res = an.submit([frame()], 0.0, mirror).result(5)
    finally:
        an.close()
    return res, lm


def test_default_mode_is_full_plus_halves():
    assert analysis.DETECT_MODE == "full+halves"


def test_halves_cover_frame_with_overlap():
    assert detect_tiles(1920, "halves") == [("left", 0, 1248), ("right", 672, 1920)]
    assert detect_tiles(1920, "full") == [("full", 0, 1920)]
    assert detect_tiles(1920, "full+halves") == [("full", 0, 1920), ("left", 0, 1248), ("right", 672, 1920)]
    assert detect_tiles(W, "halves") == [("left", 0, 156), ("right", 84, 240)]


def test_unknown_mode_falls_back_to_full():
    assert detect_tiles(1920, "이상한값") == [("full", 0, 1920)]


def test_full_mode_is_unchanged():
    faces = [world_face(0.7), world_face(0.3)]
    res, lm = run(faces, "full")
    assert lm.calls == [(0, W)]  # 전체 한 번만
    # 지금처럼 검출 순서 그대로, 박스 · 눈 뜸도 직접 계산한 값과 같다
    for got, pts in zip(res.faces, faces):
        assert got.box == pytest.approx(analysis._face_box(pts), abs=1e-9)
    assert res.faces[0].box[0] > res.faces[1].box[0]  # 왼쪽 x 순으로 다시 늘어놓지 않는다
    assert res.faces[0].eye_open == pytest.approx(eye_open_from(None, faces[0], W / H), abs=1e-9)
    assert res.info["detect_mode"] == "full"


def test_tile_landmarks_map_back_to_full_frame():
    face = world_face(0.8)
    res, lm = run([face], "halves")
    assert (84, 156) in lm.calls
    assert len(res.faces) == 1
    assert res.faces[0].box == pytest.approx(analysis._face_box(face), abs=1e-9)


def test_tile_face_matches_full_face_metrics():
    face = world_face(0.2, ratio=0.3)
    full, _ = run([face], "full")
    tiled, _ = run([face], "halves")
    a, b = full.faces[0], tiled.faces[0]
    assert b.box == pytest.approx(a.box, abs=1e-6)
    assert b.eye_open == pytest.approx(a.eye_open, abs=1e-6)
    assert b.frontality == pytest.approx(a.frontality)


def test_duplicate_in_overlap_is_merged():
    face = world_face(0.5)  # 전체 · 왼쪽 · 오른쪽 모두에 통째로 들어온다
    res, lm = run([face], "full+halves")
    assert len(lm.calls) == 3
    assert len(res.faces) == 1
    assert res.faces[0].box == pytest.approx(analysis._face_box(face))


def test_two_people_on_both_sides_are_both_found():
    faces = [world_face(0.15), world_face(0.85)]
    full, _ = run(faces, "full", min_frac=0.2)
    assert full.faces == []  # 전체 화면에서는 작아서 놓친다
    res, _ = run(faces, "full+halves", min_frac=0.2)
    assert len(res.faces) == 2
    assert res.faces[0].box[0] < 0.5 < res.faces[1].box[0]


def test_failed_tile_keeps_other_results():
    faces = [world_face(0.15), world_face(0.85)]
    res, _ = run(faces, "full+halves", min_frac=0.2, fail_ox=84)  # 오른쪽 조각 실패
    assert len(res.faces) == 1 and res.faces[0].box[0] < 0.5
    assert res.info["candidates"][0]["faces"] == 1


def test_all_tiles_failing_is_a_missing_face():
    lm = TileLandmarker([world_face(0.5)])
    lm.detect = lambda image: (_ for _ in ()).throw(RuntimeError("모두 실패"))
    an = BurstAnalyzer(analysis.Path("none.task"), landmarker=lm, detect_mode="full+halves")
    try:
        res = an.submit([frame()], 0.0, False).result(5)
    finally:
        an.close()
    assert res.info["candidates"][0]["faces"] == 0


def test_order_and_cap_are_deterministic():
    faces = [world_face(0.8, w=0.24), world_face(0.2, w=0.16), world_face(0.5, w=0.2)]
    res, _ = run(faces, "full+halves", max_faces=4)
    xs = [f.box[0] for f in res.faces]
    assert len(res.faces) == 3 and xs == sorted(xs)
    capped, _ = run(faces, "full+halves", max_faces=2)
    again, _ = run(faces, "full+halves", max_faces=2)
    assert [f.box for f in capped.faces] == [f.box for f in again.faces]
    # 상한을 넘으면 큰 얼굴부터 남기고, 남은 것은 왼쪽 x 순
    widths = sorted(round(f.box[2] - f.box[0], 3) for f in capped.faces)
    assert len(capped.faces) == 2 and widths[0] > 0.17
    assert capped.faces[0].box[0] < capped.faces[1].box[0]


def test_mirror_applies_after_mapping():
    face = world_face(0.8)
    res, _ = run([face], "halves", mirror=True)
    x0, y0, x1, y1 = analysis._face_box(face)
    assert res.faces[0].box == pytest.approx((1 - x1, y0, 1 - x0, y1))


def test_detect_frames_returns_faces_and_ms_per_frame():
    lm = TileLandmarker([world_face(0.15), world_face(0.85)], min_frac=0.2)
    an = BurstAnalyzer(analysis.Path("none.task"), landmarker=lm)
    try:
        full = an.detect_frames([frame().rgb, frame().rgb], "full").result(5)
        both = an.detect_frames([frame().rgb], "full+halves").result(5)
    finally:
        an.close()
    assert [len(f) for f, _ in full] == [0, 0] and all(ms >= 0 for _, ms in full)
    assert len(both[0][0]) == 2 and isinstance(both[0][0][0], FaceObs)


class FakeDetector:
    """compare_detect 용 가짜 분석기: 전략마다 정해 둔 (얼굴 수, ms) 를 프레임마다 돌려준다."""

    def __init__(self, plan):
        self.plan = plan  # mode -> [(얼굴 수, ms), ...]
        self.seen = []

    def detect_frames(self, frames, mode):
        from concurrent.futures import Future
        self.seen.append((mode, len(frames)))
        fut = Future()
        box = FaceObs((0.1, 0.1, 0.3, 0.4), 1.0, 1.0)
        fut.set_result([([box] * n, ms) for n, ms in self.plan[mode][:len(frames)]])
        return fut


def make_seq(root, name, n=3):
    frames = [TimedFrame(10.0 + 0.1 * i, np.full((24, 32, 3), 40 * i + 10, np.uint8)) for i in range(n)]
    rb.save_sequence(root / name, frames, frames[0].t, {"subject": "x", "conditions": ["단체"]})


def test_compare_detect_reports_rates_and_ms(tmp_path):
    make_seq(tmp_path, "seqA")
    make_seq(tmp_path, "field_x")
    det = FakeDetector({
        "full": [(0, 10.0), (1, 20.0), (0, 30.0)],
        "halves": [(1, 40.0), (2, 50.0), (1, 60.0)],
        "full+halves": [(2, 70.0), (2, 80.0), (3, 90.0)],
    })
    lines = []
    cd.run(tmp_path, det, out=lines.append)
    raw = (tmp_path / "compare_detect.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(raw.decode("utf-8-sig").splitlines()))
    assert rows[0] == cd.CSV_HEADER
    body = {(r[0], r[1]): r for r in rows[1:]}
    assert len(rows) == 1 + 3 * 3  # 시퀀스 2개 + 전체, 전략 3개씩
    h = cd.CSV_HEADER
    a = dict(zip(h, body[("seqA", "full")]))
    assert a["프레임 수"] == "3" and a["얼굴 찾은 비율"] == "0.333"
    assert a["프레임당 얼굴 수"] == "0.33" and a["평균 ms"] == "20.0" and a["최대 ms"] == "30.0"
    t = dict(zip(h, body[(cd.TOTAL, "full+halves")]))
    assert t["프레임 수"] == "6" and t["얼굴 찾은 비율"] == "1.000" and t["프레임당 얼굴 수"] == "2.33"
    assert t["최대 ms"] == "90.0"
    assert any("seqA" in ln and "full+halves" in ln for ln in lines)
    assert any(cd.TOTAL in ln for ln in lines)


def test_compare_detect_debug_dir_writes_boxes(tmp_path):
    make_seq(tmp_path, "seqA", n=2)
    det = FakeDetector({m: [(1, 1.0), (0, 1.0)] for m in cd.MODES})
    out = tmp_path / "dbg"
    cd.run(tmp_path, det, out=lambda s: None, debug_dir=out)
    files = sorted(p.name for p in (out / "seqA").glob("*.jpg"))
    assert len(files) == 2 * len(cd.MODES)
    assert "000_full+halves.jpg" in files


def test_compare_detect_no_debug_by_default(tmp_path):
    make_seq(tmp_path, "seqA", n=1)
    det = FakeDetector({m: [(1, 1.0)] for m in cd.MODES})
    cd.run(tmp_path, det, out=lambda s: None)
    assert list(tmp_path.rglob("*_full.jpg")) == []
