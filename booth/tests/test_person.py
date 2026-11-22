"""사람 찾기로 구도용 머리 더하기 (Task H) — 가짜 사람 검출기를 주입한다."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace as P

import numpy as np
import pytest

from test_analysis import H, W, FakeLandmarker, _shifted, frame, matrix
from walnut import analysis
from walnut.analysis import (HEAD_ASPECT, HEAD_TOP_PAD, HEAD_W_RATIO, PERSON_FACE_TOP, BurstAnalyzer, head_box,
                             person_heads)
from walnut.burst import TimedFrame
from walnut.quality import FaceObs

LEFT_PERSON = (0.125, 0.25, 0.375, 1.00)  # 정규화 x0 y0 x1 y1 (가짜 그림 64x48 의 화소 경계에 맞춘다)
RIGHT_PERSON = (0.625, 8 / 48, 0.875, 1.00)


class FakePersons:
    """marker -> 사람 박스 목록(정규화) 또는 예외. 받은 그림 크기의 화소 좌표로 돌려준다 (MediaPipe 와 같은 모양)."""

    def __init__(self, script, label="person"):
        self.script = script
        self.label = label
        self.calls = 0
        self.closed = False
        self.threads = set()

    def detect(self, image):
        self.calls += 1
        self.threads.add(threading.get_ident())
        arr = np.asarray(image.numpy_view())
        h, w = arr.shape[:2]
        boxes = self.script.get(int(arr[0, 0, 0]), [])
        if isinstance(boxes, Exception):
            raise boxes
        dets = [P(bounding_box=P(origin_x=round(b[0] * w), origin_y=round(b[1] * h),
                                 width=round((b[2] - b[0]) * w), height=round((b[3] - b[1]) * h)),
                  categories=[P(category_name=self.label, score=0.9)]) for b in boxes]
        return P(detections=dets)

    def close(self):
        self.closed = True


def make(face_script, person_script, tmp_path, persons=None):
    det = persons if persons is not None else FakePersons(person_script)
    return BurstAnalyzer(tmp_path / "none.task", landmarker=FakeLandmarker(face_script), detect_mode="full",
                         person_detector=det), det


def run(an, frames, shutter=0.0, mirror=False):
    try:
        return an.submit(frames, shutter, mirror).result(5)
    finally:
        an.close()


def test_head_box_estimate_constants():
    # 보정 (data-dev 슬롯 63쌍, 보고서 task-H-report.md): 머리 폭 = 사람 폭 × 0.4, 높이 = 폭 × 1.2,
    # 위 = 사람 위 + 머리 폭 × 0.3
    assert (HEAD_W_RATIO, HEAD_ASPECT, HEAD_TOP_PAD, PERSON_FACE_TOP) == (0.4, 1.2, 0.3, 0.6)
    box = head_box((0.25, 0.10, 0.50, 0.90), 1920, 1080)
    hw = 0.25 * 1920 * 0.4                        # 192 px
    assert box[0] == pytest.approx((0.375 * 1920 - hw / 2) / 1920)
    assert box[2] == pytest.approx((0.375 * 1920 + hw / 2) / 1920)
    top = 0.10 * 1080 + 0.3 * hw
    assert box[1] == pytest.approx(top / 1080)
    assert box[3] == pytest.approx((top + hw * 1.2) / 1080)


def test_head_box_clipped_to_frame():
    box = head_box((0.0, 0.95, 0.30, 1.0), 1920, 1080)   # 왼쪽 끝 · 아래 끝
    assert all(0.0 <= v <= 1.0 for v in box) and box[0] < box[2] and box[1] <= box[3]


def test_person_heads_skip_person_with_face_inside_top_part():
    face = FaceObs((0.20, 0.25, 0.30, 0.40), 0.9, 1.0)       # 가운데 (0.25, 0.325) — 왼쪽 사람 위 60% 안
    heads = person_heads([LEFT_PERSON, RIGHT_PERSON], [face], 1920, 1080)
    assert len(heads) == 1 and heads[0].box == head_box(RIGHT_PERSON, 1920, 1080)
    assert heads[0].eye_open is None and heads[0].frontality is None
    low = FaceObs((0.20, 0.85, 0.30, 0.95), 0.9, 1.0)         # 사람 박스 아래쪽(배 근처)의 얼굴은 그 사람의 얼굴이 아니다
    assert len(person_heads([LEFT_PERSON], [low], 1920, 1080)) == 1


def test_no_face_uses_person_head_for_framing(tmp_path):
    an, det = make({}, {m: [LEFT_PERSON] for m in range(1, 4)}, tmp_path)
    res = run(an, [frame(0.1 * i, i + 1) for i in range(3)], 0.1)
    assert res.info["reason"] == "no_face"
    assert [f.box for f in res.faces] == [head_box(LEFT_PERSON, W, H)]
    assert res.info["person_heads"] == 1 and res.info["person_ms"] is not None
    assert res.info["faces_from"] is None
    assert det.calls == 1                       # 고른 프레임 한 장에만


def test_person_without_face_box_is_added(tmp_path):
    a = (_shifted(0.25, 0.3), matrix(0))       # 왼쪽 사람의 얼굴만 잡혔다
    an, _ = make({1: [a], 2: [a]}, {1: [LEFT_PERSON, RIGHT_PERSON], 2: [LEFT_PERSON, RIGHT_PERSON]}, tmp_path)
    res = run(an, [frame(0.0, 1), frame(0.1, 2)])
    assert len(res.faces) == 2 and res.info["person_heads"] == 1
    assert res.faces[1].box == head_box(RIGHT_PERSON, W, H)


def test_person_with_face_inside_not_added(tmp_path):
    a = (_shifted(0.25, 0.3), matrix(0))
    an, _ = make({1: [a]}, {1: [LEFT_PERSON]}, tmp_path)
    res = run(an, [frame(0.0, 1)])
    assert len(res.faces) == 1 and res.info["person_heads"] == 0
    assert res.info["person_ms"] is not None


def test_person_does_not_change_selection(tmp_path):
    # 사람 찾기는 구도용만 — 고른 번호 · 점수 · 탈락은 사람 찾기가 없을 때와 같다
    script = {1: [(_shifted(0.25, 0.3, ratio=0.05), matrix(0))], 2: [(_shifted(0.25, 0.3), matrix(0))]}
    frames = [frame(0.0, 1), frame(0.1, 2)]
    plain = BurstAnalyzer(tmp_path / "none.task", landmarker=FakeLandmarker(script), detect_mode="full")
    base = run(plain, frames)
    an, _ = make(script, {1: [RIGHT_PERSON], 2: [RIGHT_PERSON]}, tmp_path)
    res = run(an, frames)
    for k in ("index", "reason", "scores", "rejects", "candidates"):
        assert res.info[k] == base.info[k]


def test_person_detector_missing_model_keeps_analysis(tmp_path):
    a = (_shifted(0.25, 0.3), matrix(0))
    frames = [frame(0.0, 1), frame(0.1, 2)]
    an = BurstAnalyzer(tmp_path / "none.task", landmarker=FakeLandmarker({1: [a], 2: [a]}), detect_mode="full",
                       person_model_path=tmp_path / "없음.tflite")
    res = run(an, frames)
    assert len(res.faces) == 1 and res.info["person_heads"] == 0 and res.info["person_ms"] is None


def test_person_detector_broken_model_turns_off_once(tmp_path, caplog):
    bad = tmp_path / "bad.tflite"
    bad.write_bytes(b"not a model")
    a = (_shifted(0.25, 0.3), matrix(0))
    an = BurstAnalyzer(tmp_path / "none.task", landmarker=FakeLandmarker({1: [a]}), detect_mode="full",
                       person_model_path=bad)
    try:
        r1 = an.submit([frame(0.0, 1)], 0.0, False).result(30)
        r2 = an.submit([frame(0.0, 1)], 0.0, False).result(30)
    finally:
        an.close()
    for r in (r1, r2):
        assert len(r.faces) == 1 and r.info["person_heads"] == 0 and r.info["person_ms"] is None
    assert sum("사람 찾기" in m for m in caplog.messages) == 1    # 경고는 한 번


def test_person_detector_exception_keeps_analysis(tmp_path):
    a = (_shifted(0.25, 0.3), matrix(0))
    an, _ = make({1: [a]}, {1: RuntimeError("사람 모델 오류")}, tmp_path)
    res = run(an, [frame(0.0, 1)])
    assert len(res.faces) == 1 and res.info["person_heads"] == 0 and res.info["person_ms"] is None
    json.dumps(res.info)


def test_person_heads_mirrored_once(tmp_path):
    an, _ = make({}, {1: [LEFT_PERSON]}, tmp_path)
    try:
        plain = an.submit([frame(0.0, 1)], 0.0, False).result(5)
        flipped = an.submit([frame(0.0, 1)], 0.0, True).result(5)
    finally:
        an.close()
    a, b = plain.faces[0].box, flipped.faces[0].box
    assert b[0] == pytest.approx(1 - a[2]) and b[2] == pytest.approx(1 - a[0]) and b[1] == a[1]


def test_person_detection_runs_on_worker_thread_and_closes_only_owned(tmp_path):
    an, det = make({}, {1: [LEFT_PERSON]}, tmp_path)
    an.submit([frame(0.0, 1)], 0.0, False).result(5)
    an.close()
    assert det.threads and threading.get_ident() not in det.threads
    assert det.closed is False    # 주입한 검출기는 분석기가 닫지 않는다


def test_non_person_category_is_ignored(tmp_path):
    an, _ = make({}, {}, tmp_path, persons=FakePersons({1: [LEFT_PERSON]}, label="dog"))
    res = run(an, [frame(0.0, 1)])
    assert res.faces == [] and res.info["person_heads"] == 0


def test_timings_include_person(tmp_path):
    an, _ = make({}, {1: [LEFT_PERSON]}, tmp_path)
    res = run(an, [frame(0.0, 1)])
    t = res.info["timings"]
    assert "person" in t and t["person"] >= 0 and t["total"] >= t["person"]


def test_small_person_head_filtered_like_small_face():
    # 배경 행인: 사람 박스가 작으면 추정 머리도 작아 framing.usable_faces 가 똑같이 뺀다
    from walnut.framing import usable_faces
    near = FaceObs((0.40, 0.20, 0.55, 0.50), 0.9, 1.0)
    far = person_heads([(0.85, 0.40, 0.90, 0.60)], [near], 1920, 1080)
    assert len(far) == 1 and usable_faces([near] + far) == [near]


def test_person_heads_count_toward_many_faces_rule():
    from walnut.framing import MAX_FACES, compute_crop
    faces = [FaceObs((0.1 + 0.2 * k, 0.3, 0.16 + 0.2 * k, 0.42), 0.9, 1.0) for k in range(3)]
    heads = person_heads([(0.80, 0.25, 0.95, 1.0)], faces, 1920, 1080)
    assert len(faces) + len(heads) == MAX_FACES
    c = compute_crop(1920, 1080, 813, 1083, faces + heads)
    assert c.h == 1080   # 4명 이상이면 1.0배


def test_smart_crop_off_skips_person_step(tmp_path):
    # 버스트만 켜고 구도 보정은 끔: 머리를 더해도 쓸 곳이 없다 — 검출기를 부르지 않고 기록도 0 · None
    det = FakePersons({m: [LEFT_PERSON] for m in range(1, 4)})
    an = BurstAnalyzer(tmp_path / "none.task", landmarker=FakeLandmarker({}), detect_mode="full",
                       person_detector=det, person_enabled=False)
    res = run(an, [frame(0.1 * i, i + 1) for i in range(3)], 0.1)
    assert det.calls == 0 and res.faces == []
    assert res.info["person_heads"] == 0 and res.info["person_ms"] is None


def test_person_enabled_by_default_for_tools(tmp_path):
    # 기본값은 지금 동작 그대로 (tools/eval_capture.py 는 구도를 늘 계산한다)
    an = BurstAnalyzer(tmp_path / "none.task", landmarker=FakeLandmarker({}))
    try:
        assert an.person_enabled is True
    finally:
        an.close()


def test_burst_only_app_never_loads_person_model(make_app, monkeypatch):
    # 앱: BOOTH_BURST=1 · BOOTH_SMART_CROP 끔 → 사람 찾기를 끈 분석기, 불러오기도 시도하지 않는다
    tried = []
    monkeypatch.setattr(BurstAnalyzer, "_ensure_person", lambda self: tried.append(1) or False)
    app = make_app({"BOOTH_BURST": "true", "BOOTH_SMART_CROP": "false"})
    assert app.analyzer is not None and app.analyzer.person_enabled is False
    app.analyzer._executor.submit(lambda: None).result(30)   # warm 이 끝날 때까지
    assert tried == []


def test_smart_crop_app_enables_person(make_app):
    app = make_app({"BOOTH_BURST": "true", "BOOTH_SMART_CROP": "true"})
    assert app.analyzer.person_enabled is True


@pytest.mark.skipif(not (analysis.Path(__file__).resolve().parent.parent / "models" / "efficientdet_lite0.tflite").is_file(),
                    reason="사람 찾기 모델 파일 없음")
def test_real_person_model_smoke_on_blank_frame():
    root = analysis.Path(__file__).resolve().parent.parent / "models"
    an = BurstAnalyzer(root / "face_landmarker.task")
    try:
        res = an.submit([TimedFrame(0.0, np.full((360, 640, 3), 120, np.uint8))], 0.0, False).result(60)
    finally:
        an.close()
    assert res.faces == [] and res.info["person_heads"] == 0 and res.info["person_ms"] is not None



def test_cut_line_has_person_fields():
    from walnut.fieldlog import cut_details
    base = {"index": 0, "scores": [None], "rejects": [None], "candidates": [{"t": 0.0, "sharpness": 1.0, "faces": 0}]}
    out = cut_details({**base, "person_heads": 2, "person_ms": 23.456}, 0.0, [])
    assert out["person_heads"] == 2 and out["person_ms"] == 23.5
    off = cut_details({**base, "person_heads": 0, "person_ms": None}, 0.0, [])
    assert off["person_heads"] == 0 and off["person_ms"] is None
    none = cut_details(None, 0.0, [])     # 시간 초과 · 오류로 결과가 없으면 모른다
    assert none["person_heads"] is None and none["person_ms"] is None
    json.dumps(out)


def test_analyze_field_log_counts_person_framing(tmp_path):
    from tools import analyze_field_log as an
    face = [0.4, 0.2, 0.5, 0.4]
    recs = [
        {"type": "cut", "shoot_id": "a", "reason": "no_face", "faces": [face], "person_heads": 1, "person_ms": 20.0},
        {"type": "cut", "shoot_id": "a", "reason": "best", "faces": [face, face], "person_heads": 1, "person_ms": 21.0},
        {"type": "cut", "shoot_id": "a", "reason": "best", "faces": [face], "person_heads": 0, "person_ms": 19.0},
        {"type": "cut", "shoot_id": "a", "reason": "best", "faces": [face], "person_heads": None, "person_ms": None},
        {"type": "cut", "shoot_id": "b", "reason": "best", "faces": [face]},   # 예전 기록 — 필드 없음
    ]
    p = tmp_path / "capture_metrics.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    s = an.summarize(an.load_records(p)[0])
    assert s["person"] == {"ran": 3, "only": 1, "added": 1, "ms": an.stats([20.0, 21.0, 19.0])}
    text = an.format_report(s)
    assert "사람 찾기로 구도를 잡은 컷 (얼굴 0 → 사람)  1" in text
    assert "얼굴에 사람 찾기 머리를 더한 컷  1" in text


def test_analyze_field_log_without_person_fields_has_no_person_lines(tmp_path):
    from tools import analyze_field_log as an
    s = an.summarize([{"type": "cut", "shoot_id": "b", "reason": "best", "faces": []}])
    assert s["person"]["ran"] == 0 and "사람 찾기" not in an.format_report(s)
