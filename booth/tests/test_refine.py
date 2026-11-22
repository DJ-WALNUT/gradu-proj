"""사람별 얼굴 다시 찾기 (Task K) — 전체 프레임과 머리 둘레 조각을 구별하는 가짜 얼굴 모델을 주입한다."""

from __future__ import annotations

from types import SimpleNamespace as P

import numpy as np
import pytest

from facekit import fake_face, with_eyes
from test_analysis import matrix
from test_person import FakePersons
from walnut import analysis
from walnut.analysis import (REFINE_FACE_W, REFINE_MIN_PX, BurstAnalyzer, head_box, merge_refined, refine_regions)
from walnut.burst import TimedFrame
from walnut.fieldlog import cut_details
from walnut.quality import FaceObs

W, H = 640, 480
PERSON = (0.25, 0.10, 0.75, 1.00)          # 머리 둘레 조각 = x 128~512, y 0~368
RECT = (128, 0, 512, 368)
FAR = (0.80, 0.10, 0.98, 1.00)             # 오른쪽 끝의 또 한 사람


def frame(t, marker):
    """가짜 모델이 조각에서도 프레임을 구별하도록 그림 전체를 marker 로 채운다."""
    return TimedFrame(t, np.full((H, W, 3), marker, np.uint8))


class CropLandmarker:
    """전체 프레임이면 full[marker], 조각이면 crop[marker] 의 얼굴 목록 [(landmarks, matrix)] 을 돌려준다."""

    def __init__(self, full, crop):
        self.full, self.crop = full, crop
        self.crops = 0

    def detect(self, image):
        arr = np.asarray(image.numpy_view())
        whole = arr.shape[:2] == (H, W)
        self.crops += 0 if whole else 1
        faces = (self.full if whole else self.crop).get(int(arr[0, 0, 0]), [])
        if isinstance(faces, Exception):
            raise faces
        return P(face_landmarks=[f[0] for f in faces], face_blendshapes=[],
                 facial_transformation_matrixes=[f[1] for f in faces])

    def close(self):
        pass


def tile_face(ratio=0.16):
    """전체 프레임에서 잡힌 작은 얼굴 (폭 약 0.135). 눈 뜸이 낮게 나온다 (ratio 0.16 → 0.25)."""
    return (with_eyes(fake_face(cx=0.5, cy=0.35, w=0.1, h=0.15), ratio, aspect=W / H, eye_w=0.02), matrix(0))


def crop_face(ratio):
    """조각 안에서 크게 잡힌 같은 얼굴. ratio 0.35 → 눈 뜸 1.0, 0.05 → 0.0."""
    cw, ch = RECT[2] - RECT[0], RECT[3] - RECT[1]
    return (with_eyes(fake_face(cx=0.5, cy=0.5, w=0.3, h=0.4), ratio, aspect=cw / ch), matrix(0))


def make(full, crop, persons, tmp_path, **kw):
    lm = CropLandmarker(full, crop)
    det = FakePersons(persons)
    return BurstAnalyzer(tmp_path / "none.task", landmarker=lm, detect_mode="full", person_detector=det, **kw), lm, det


def run(an, frames, shutter):
    try:
        return an.submit(frames, shutter, False).result(5)
    finally:
        an.close()


# ---- 순수 계산 ----

def test_regions_cover_head_with_padding():
    assert refine_regions([PERSON], [], W, H) == [RECT]
    hb = head_box(PERSON, W, H)
    assert RECT[0] < hb[0] * W and hb[2] * W < RECT[2] and hb[3] * H < RECT[3]


def test_regions_skip_big_face_and_tiny_crop():
    big = FaceObs((0.40, 0.25, 0.40 + REFINE_FACE_W, 0.50), 0.9, 1.0)
    assert refine_regions([PERSON], [big], W, H) == []
    small = FaceObs((0.45, 0.25, 0.55, 0.40), 0.9, 1.0)
    assert refine_regions([PERSON], [small], W, H) == [RECT]
    tiny = (0.50, 0.10, 0.52, 0.30)   # 사람 폭 12.8px → 조각이 REFINE_MIN_PX 보다 작다
    assert refine_regions([tiny], [], W, H) == []
    assert REFINE_MIN_PX == 48


def test_regions_order_no_face_first_then_smaller_face():
    left, mid, right = (0.02, 0.1, 0.30, 1.0), (0.36, 0.1, 0.64, 1.0), (0.70, 0.1, 0.98, 1.0)
    faces = [FaceObs((0.12, 0.25, 0.20, 0.40), 0.9, 1.0),    # 왼쪽 사람: 폭 0.08
             FaceObs((0.47, 0.25, 0.53, 0.40), 0.9, 1.0)]    # 가운데 사람: 폭 0.06, 오른쪽 사람은 얼굴 없음
    order = refine_regions([left, mid, right], faces, W, H)
    centers = [(r[0] + r[2]) / 2 / W for r in order]
    assert len(order) == 3 and centers[0] > 0.7 and 0.4 < centers[1] < 0.6 and centers[2] < 0.3


def test_merge_prefers_refined_and_keeps_other_tile_faces():
    tile_same = FaceObs((0.44, 0.28, 0.56, 0.46), 0.3, 1.0)
    tile_other = FaceObs((0.10, 0.30, 0.20, 0.45), 0.8, 1.0)
    ref = FaceObs((0.42, 0.25, 0.58, 0.50), 0.9, 1.0)
    out = merge_refined([tile_same, tile_other], [(5.0, ref)], 4)
    assert out == [tile_other, ref] and out[1] is ref           # 같은 자리는 다시 찾은 쪽, 결과는 왼쪽부터
    tiles = [tile_same]
    assert merge_refined(tiles, [], 4) is tiles                   # 다시 찾은 것이 없으면 그대로


def test_merge_duplicate_refined_keeps_nearer_to_crop_center():
    far = FaceObs((0.42, 0.25, 0.58, 0.50), 0.5, 1.0)             # 옆 사람 조각 가장자리에서 잡힌 것
    near = FaceObs((0.43, 0.25, 0.59, 0.50), 0.9, 1.0)            # 자기 조각 가운데에서 잡힌 것
    assert merge_refined([], [(200.0, far), (3.0, near)], 4) == [near]


def test_merge_respects_max_faces_keeping_larger():
    big = FaceObs((0.10, 0.10, 0.40, 0.50), 0.9, 1.0)
    small = FaceObs((0.60, 0.30, 0.66, 0.38), 0.9, 1.0)
    assert merge_refined([small], [(1.0, big)], 1) == [big]


# ---- 분석기 ----

def test_refined_eye_value_drives_selection(tmp_path):
    # 조각 검출로는 두 프레임 모두 눈 뜸 0.25 (모두 탈락). 다시 찾으면 1번은 뜸, 2번(셔터 프레임)은 감음
    full = {1: [tile_face()], 2: [tile_face()]}
    frames = [frame(0.0, 1), frame(0.1, 2)]
    plain = BurstAnalyzer(tmp_path / "none.task", landmarker=CropLandmarker(full, {}), detect_mode="full")
    base = run(plain, frames, 0.1)
    assert base.info["reason"] == "all_rejected" and base.info["refined"] == 0

    an, lm, det = make(full, {1: [crop_face(0.35)], 2: [crop_face(0.05)]}, {2: [PERSON]}, tmp_path)
    res = run(an, frames, 0.1)
    assert res.info["refined"] == 1 and res.info["refine_ms"] >= 0 and lm.crops == 2
    assert det.calls == 1                                   # 사람 찾기는 셔터 프레임 한 장에서 한 번
    assert res.info["reason"] == "best" and res.info["index"] == 0
    assert res.info["rejects"] == [None, "eye"]
    assert [c["eye"] for c in res.info["candidates"]] == [pytest.approx(1.0), pytest.approx(0.0)]
    assert [c["faces"] for c in res.info["candidates"]] == [1, 1]      # 같은 얼굴을 두 번 세지 않는다
    assert len(res.faces) == 1 and res.info["person_heads"] == 0
    assert res.faces[0].box[0] == pytest.approx((0.35 * 384 + 128) / W)  # 박스는 전체 프레임 좌표


def test_missed_face_is_found_in_crop(tmp_path):
    # 전체 프레임에서는 얼굴이 하나도 안 잡힌다 (멀리 선 사람)
    an, _, _ = make({}, {1: [crop_face(0.35)], 2: [crop_face(0.35)]}, {1: [PERSON], 2: [PERSON]}, tmp_path)
    res = run(an, [frame(0.0, 1), frame(0.1, 2)], 0.1)
    assert res.info["reason"] == "best" and res.info["refined"] == 1
    assert len(res.faces) == 1 and res.faces[0].eye_open == pytest.approx(1.0)
    assert res.info["person_heads"] == 0                    # 얼굴을 찾았으니 추정 머리는 더하지 않는다


def test_crop_without_face_falls_back_to_head_estimate(tmp_path):
    an, _, _ = make({}, {}, {1: [PERSON], 2: [PERSON]}, tmp_path)
    res = run(an, [frame(0.0, 1), frame(0.1, 2)], 0.1)
    assert res.info["reason"] == "no_face" and res.info["refined"] == 1
    assert [f.box for f in res.faces] == [head_box(PERSON, W, H)] and res.info["person_heads"] == 1


def test_no_refine_when_person_finding_is_off(tmp_path):
    an, lm, det = make({1: [tile_face()]}, {1: [crop_face(0.35)]}, {1: [PERSON]}, tmp_path, person_enabled=False)
    res = run(an, [frame(0.0, 1)], 0.0)
    assert res.info["refined"] == 0 and lm.crops == 0 and det.calls == 0


def test_crop_error_keeps_tile_result(tmp_path):
    an, _, _ = make({1: [tile_face()], 2: [tile_face()]}, {1: RuntimeError("조각 오류"), 2: [crop_face(0.35)]},
                    {2: [PERSON]}, tmp_path)
    res = run(an, [frame(0.0, 1), frame(0.1, 2)], 0.1)
    assert [c["eye"] for c in res.info["candidates"]] == [pytest.approx(0.25), pytest.approx(1.0)]
    assert res.info["index"] == 1


def test_time_budget_stops_after_first_person(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "REFINE_BUDGET_SEC", 0.0)
    an, lm, _ = make({}, {}, {1: [PERSON, FAR], 2: [PERSON, FAR]}, tmp_path)
    res = run(an, [frame(0.0, 1), frame(0.1, 2)], 0.1)
    assert res.info["refined"] == 1 and lm.crops == 2       # 한 사람(프레임 2장)만
    assert res.info["person_heads"] == 2                    # 남은 사람도 구도에는 담는다


def test_deadline_skips_refine_but_keeps_heads(tmp_path, monkeypatch):
    # 조각 검출만으로 이미 늦었으면 다시 찾기를 하지 않는다 (촬영 장면의 시간 초과를 피한다)
    monkeypatch.setattr(analysis, "REFINE_DEADLINE_SEC", 0.0)
    an, lm, _ = make({1: [tile_face()]}, {1: [crop_face(0.35)]}, {1: [PERSON, FAR]}, tmp_path)
    res = run(an, [frame(0.0, 1)], 0.0)
    assert res.info["refined"] == 0 and lm.crops == 0
    assert res.info["person_heads"] == 1 and len(res.faces) == 2     # 얼굴 없는 사람의 추정 머리는 그대로 더한다


def test_detect_burst_returns_refined_faces(tmp_path):
    an, _, _ = make({1: [tile_face()], 2: [tile_face()]}, {1: [crop_face(0.35)], 2: [crop_face(0.05)]},
                    {2: [PERSON]}, tmp_path)
    try:
        plain = an.detect_frames([frame(0.0, 1).rgb, frame(0.1, 2).rgb], "full").result(5)
        both = an.detect_burst([frame(0.0, 1).rgb, frame(0.1, 2).rgb], 1, "full").result(5)
    finally:
        an.close()
    assert [fs[0].eye_open for fs, _ in plain] == [pytest.approx(0.25)] * 2
    assert [fs[0].eye_open for fs, _ in both] == [pytest.approx(1.0), pytest.approx(0.0)]
    assert all(len(fs) == 1 and ms >= 0 for fs, ms in both)


def test_cut_details_carry_refine_fields():
    base = {"index": 0, "candidates": [], "scores": [], "rejects": []}
    out = cut_details({**base, "refined": 2, "refine_ms": 312.345}, 0.0, [])
    assert out["refined"] == 2 and out["refine_ms"] == 312.3
    none = cut_details(None, 0.0, [])
    assert none["refined"] is None and none["refine_ms"] is None
