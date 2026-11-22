"""버스트 분석기 시험 (가짜 landmarker 를 주입한다)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace as P

import numpy as np
import pytest

from facekit import fake_face, with_eyes
from walnut.analysis import BurstAnalyzer
from walnut.burst import TimedFrame

MODEL = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"
W, H = 64, 48


def frame(t, marker, noise=0):
    """marker 를 (0,0) 화소에 심어 가짜 landmarker 가 프레임을 구별하게 한다. noise 가 크면 선명해진다."""
    rng = np.random.default_rng(marker)
    rgb = (rng.integers(0, noise + 1, (H, W, 3)) if noise else np.zeros((H, W, 3))).astype(np.uint8)
    rgb[0, 0] = (marker, 0, 0)
    return TimedFrame(t, rgb)


def matrix(deg=0.0):
    r = np.radians(deg)
    m = np.eye(4)
    m[:3, :3] = [[np.cos(r), 0, np.sin(r)], [0, 1, 0], [-np.sin(r), 0, np.cos(r)]]
    return m


class FakeLandmarker:
    """marker -> (얼굴 목록 [(landmarks, matrix)], 예외) 로 정해 둔 결과를 돌려준다."""

    def __init__(self, script):
        self.script = script
        self.closed = False
        self.threads = set()

    def detect(self, image):
        self.threads.add(threading.get_ident())
        marker = int(np.asarray(image.numpy_view())[0, 0, 0])
        faces = self.script.get(marker, [])
        if isinstance(faces, Exception):
            raise faces
        return P(face_landmarks=[f[0] for f in faces], face_blendshapes=[],
                 facial_transformation_matrixes=[f[1] for f in faces])

    def close(self):
        self.closed = True


def open_face(cx=0.3, ratio=0.35):
    return (with_eyes(fake_face(cx=cx, cy=0.5), ratio, aspect=W / H), matrix(0))


def analyzer(script, tmp_path):
    # 이 가짜는 조각을 구별하지 못하므로 전체 프레임 한 번으로 검출한다 (조각 전략은 test_detect_tiles.py)
    return BurstAnalyzer(tmp_path / "none.task", landmarker=FakeLandmarker(script), detect_mode="full")


def test_picks_frame_from_selection(tmp_path):
    # 둘 다 선명도는 같고 두 번째 프레임만 눈을 감았다
    script = {1: [open_face(ratio=0.05)], 2: [open_face(ratio=0.35)]}
    frames = [frame(0.0, 1), frame(0.1, 2)]
    an = analyzer(script, tmp_path)
    try:
        res = an.submit(frames, 0.0, False).result(5)
    finally:
        an.close()
    assert res.info["index"] == 1
    assert res.info["reason"] in ("best", "all_rejected")
    assert res.raw is frames[1].rgb
    assert len(res.faces) == 1


def test_mirror_flips_face_box_x_and_keeps_raw(tmp_path):
    script = {1: [open_face(cx=0.3)]}
    frames = [frame(0.0, 1)]
    an = analyzer(script, tmp_path)
    try:
        plain = an.submit(frames, 0.0, False).result(5)
        flipped = an.submit(frames, 0.0, True).result(5)
    finally:
        an.close()
    a, b = plain.faces[0].box, flipped.faces[0].box
    assert b[0] == pytest.approx(1 - a[2]) and b[2] == pytest.approx(1 - a[0])
    assert b[1] == a[1] and b[3] == a[3]
    assert flipped.raw is frames[0].rgb  # 거울은 촬영 경로가 따로 적용한다
    assert plain.faces[0].eye_open == flipped.faces[0].eye_open


def test_model_error_on_one_frame_is_a_missing_face(tmp_path):
    script = {1: RuntimeError("모델 오류"), 2: [open_face()]}
    frames = [frame(0.0, 1, noise=255), frame(0.1, 2)]
    an = analyzer(script, tmp_path)
    try:
        res = an.submit(frames, 0.0, False).result(5)
    finally:
        an.close()
    cands = res.info["candidates"]
    assert cands[0]["faces"] == 0 and cands[0]["sharpness"] > 0
    assert cands[1]["faces"] == 1
    assert res.info["index"] == 1  # 얼굴이 더 많은 쪽만 남는다


def test_short_landmarks_is_a_missing_face(tmp_path):
    short = ([P(x=0.5, y=0.5)] * 10, matrix(0))  # 눈 점 번호가 범위 밖 -> IndexError
    an = analyzer({1: [short]}, tmp_path)
    try:
        res = an.submit([frame(0.0, 1), frame(0.1, 2)], 0.0, False).result(5)
    finally:
        an.close()
    assert [c["faces"] for c in res.info["candidates"]] == [0, 0]


def test_worker_exception_reaches_future(tmp_path):
    an = analyzer({}, tmp_path)
    try:
        fut = an.submit([], 0.0, False)  # 빈 목록: select_best 의 ValueError
        with pytest.raises(ValueError):
            fut.result(5)
    finally:
        an.close()


def test_missing_model_is_unavailable(tmp_path):
    an = BurstAnalyzer(tmp_path / "없음.task")
    try:
        assert an.available is False
        an.warm()  # 예외 없이 끝나야 한다
        with pytest.raises(RuntimeError):
            an.submit([frame(0.0, 1)], 0.0, False).result(5)
    finally:
        an.close()


def test_broken_model_file_turns_unavailable(tmp_path):
    bad = tmp_path / "bad.task"
    bad.write_bytes(b"not a model")
    an = BurstAnalyzer(bad)
    try:
        assert an.available is True
        an.warm()
        with pytest.raises(RuntimeError):
            an.submit([frame(0.0, 1)], 0.0, False).result(30)
        assert an.available is False
    finally:
        an.close()


def test_injected_landmarker_is_available(tmp_path):
    an = analyzer({}, tmp_path)
    try:
        assert an.available is True
    finally:
        an.close()


def test_info_has_timings_and_no_image_data(tmp_path):
    script = {1: [open_face()], 2: [open_face()]}
    an = analyzer(script, tmp_path)
    try:
        res = an.submit([frame(0.0, 1), frame(0.1, 2)], 0.05, False).result(5)
    finally:
        an.close()
    info = res.info
    assert {"reason", "fallback_used", "scores", "timings", "index", "candidates"} <= set(info)
    assert {"load", "detect", "select", "total"} <= set(info["timings"])
    assert set(info["candidates"][0]) == {"t", "sharpness", "faces", "eye", "frontality"}
    assert info["rejects"] == [None, None]  # 후보마다 하나 (탈락 없음)
    json.dumps(info)  # 넘파이 값이나 이미지가 있으면 실패한다
    assert not any(isinstance(v, np.ndarray) for v in info.values())


def test_input_frames_are_not_modified(tmp_path):
    frames = [frame(0.0, 1, noise=50), frame(0.1, 2, noise=50)]
    before = [f.rgb.copy() for f in frames]
    an = analyzer({1: [open_face()], 2: [open_face()]}, tmp_path)
    try:
        an.submit(frames, 0.0, True).result(5)
    finally:
        an.close()
    for f, b in zip(frames, before):
        assert np.array_equal(f.rgb, b)


def test_work_runs_off_the_calling_thread_and_landmarker_closes_there(tmp_path):
    script = {1: [open_face()]}
    lm = FakeLandmarker(script)
    an = BurstAnalyzer(tmp_path / "none.task", landmarker=lm, detect_mode="full")
    an.submit([frame(0.0, 1)], 0.0, False).result(5)
    an.close()
    assert lm.threads and threading.get_ident() not in lm.threads
    assert lm.closed is False  # 주입한 landmarker 는 분석기가 닫지 않는다


def test_submit_after_close_raises_cleanly(tmp_path):
    an = analyzer({}, tmp_path)
    an.close()
    an.close()  # 두 번 닫아도 무해하다
    with pytest.raises(RuntimeError, match="닫"):
        an.submit([frame(0.0, 1)], 0.0, False)


@pytest.mark.skipif(not MODEL.is_file(), reason="얼굴 모델 파일 없음")
def test_real_model_smoke_on_blank_frames():
    an = BurstAnalyzer(MODEL)
    try:
        an.warm()
        frames = [TimedFrame(i * 0.1, np.full((360, 640, 3), 120, np.uint8)) for i in range(2)]
        res = an.submit(frames, 0.1, False).result(60)
    finally:
        an.close()
    assert res.info["reason"] == "no_face"
    assert res.faces == []


# ---- 확인 지점 3: 꾸준히 잡힌 얼굴만 · 이웃 후보 얼굴 빌리기 ----

from walnut import analysis  # noqa: E402
from walnut.analysis import STABLE_RATIO, borrow_faces, stable_faces  # noqa: E402
from walnut.quality import Candidate, FaceObs, select_best  # noqa: E402

PERSON = (0.589, 0.266, 0.673, 0.435)      # 90986a cut0 (거울 적용 박스) — 혼자 선 사람
OBJECT = (0.683, 0.643, 0.778, 0.764)      # 같은 컷, 10장 중 5장에서만 잡힌 배경 물건
FRIEND = (0.20, 0.30, 0.29, 0.47)          # 진짜 두 번째 사람


def fo(box, eye=0.95):
    return FaceObs(tuple(box), eye, 1.0)


def test_object_seen_in_half_the_candidates_is_dropped():
    # 90986a cut0 실제 박스: 얼굴 수가 2 · 1 로 깜빡여 '얼굴 수 부족' 탈락이 겹쳤다
    pattern = [2, 1, 2, 1, 1, 1, 2, 2, 1, 2]
    cands = [Candidate(0.1 * i, 100.0, [fo(PERSON)] + ([fo(OBJECT)] if k == 2 else []))
             for i, k in enumerate(pattern)]
    assert "faces" in select_best(cands, 0.45).rejects        # 거르기 전에는 탈락이 생긴다
    kept, dropped = stable_faces(cands)
    assert dropped == 5
    assert all([f.box for f in c.faces] == [PERSON] for c in kept)
    sel = select_best(kept, 0.45)
    assert "faces" not in sel.rejects and sel.reason == "best"
    assert [len(c.faces) for c in cands] == pattern             # 입력은 고치지 않는다


def test_real_second_person_briefly_hidden_is_kept():
    # 10장 중 8장에 있는 두 번째 사람 (잠깐 가려짐) — 사람이다
    cands = [Candidate(0.1 * i, 100.0, [fo(PERSON)] + ([] if i in (3, 4) else [fo(FRIEND)])) for i in range(10)]
    kept, dropped = stable_faces(cands)
    assert dropped == 0
    assert [len(c.faces) for c in kept] == [len(c.faces) for c in cands]


def test_ratio_is_against_candidates_that_found_any_face():
    # 얼굴이 잡힌 후보가 둘뿐이면 그 둘에 다 있는 얼굴은 꾸준한 얼굴이다 (b949f8 cut1 처럼)
    cands = [Candidate(0.1 * i, 100.0, [fo(PERSON)] if i < 2 else []) for i in range(10)]
    kept, dropped = stable_faces(cands)
    assert dropped == 0 and [len(c.faces) for c in kept] == [1, 1] + [0] * 8
    assert 0.5 < STABLE_RATIO <= 0.8


def test_moving_face_still_counts_as_same_place():
    # 1초 안에 조금씩 움직여도 (IoU > 0.3) 같은 얼굴로 센다
    cands = [Candidate(0.1 * i, 100.0, [fo((0.40 + 0.003 * i, 0.3, 0.49 + 0.003 * i, 0.47))]) for i in range(10)]
    assert stable_faces(cands)[1] == 0


def test_fewer_than_three_candidates_are_not_filtered():
    cands = [Candidate(0.0, 1.0, [fo(PERSON), fo(OBJECT)]), Candidate(0.1, 1.0, [fo(PERSON)])]
    kept, dropped = stable_faces(cands)
    assert dropped == 0 and kept == cands


def test_dropped_face_resharpens_candidate():
    # 걸러진 얼굴이 있던 후보는 선명도를 남은 얼굴로 다시 잰다 (가짜 얼굴의 흐림이 탈락을 만들지 않게)
    cands = [Candidate(0.1 * i, 5.0 if i == 0 else 100.0, [fo(PERSON)] + ([fo(OBJECT)] if i == 0 else []))
             for i in range(5)]
    calls = []

    def resharpen(i, faces):
        calls.append((i, [f.box for f in faces]))
        return 100.0

    kept, dropped = stable_faces(cands, resharpen)
    assert dropped == 1 and calls == [(0, [PERSON])]
    assert kept[0].sharpness == 100.0 and kept[1].sharpness == 100.0


def test_borrow_faces_from_nearest_candidate_in_time():
    cands = [Candidate(0.0, 1.0, [fo(FRIEND)]), Candidate(0.1, 1.0, []), Candidate(0.25, 1.0, [fo(PERSON)])]
    faces, src = borrow_faces(cands, 1)
    assert src == 0 and [f.box for f in faces] == [FRIEND]       # 0.1 초 차이가 0.15 초보다 가깝다
    assert borrow_faces(cands, 2) == (cands[2].faces, None)      # 얼굴이 있으면 빌리지 않는다
    none = [Candidate(0.1 * i, 1.0, []) for i in range(3)]
    assert borrow_faces(none, 1) == ([], None)                   # 아무 후보에도 없으면 빈 목록


def _shifted(cx, cy=0.5, ratio=0.35):
    """눈까지 담은 가짜 얼굴을 (cx, cy) 로 옮긴다 (박스가 그 자리에 모이게)."""
    pts = with_eyes(fake_face(cx=0.5, cy=0.5), ratio, aspect=W / H)
    return [P(x=p.x + cx - 0.5, y=p.y + cy - 0.5) for p in pts]


def test_analyzer_ignores_flickering_face_for_selection_but_keeps_it_for_framing(tmp_path):
    # 꾸준하지 않은 얼굴은 고르기의 얼굴 수에서만 뺀다. 고른 프레임에 있으면 구도에는 담는다 (사람을 자르지 않게)
    person = (_shifted(0.3), matrix(0))
    obj = (_shifted(0.8), matrix(0))
    with_obj = {1, 3, 7, 8, 10}
    script = {m: [person, obj] if m in with_obj else [person] for m in range(1, 11)}
    an = analyzer(script, tmp_path)
    try:
        res = an.submit([frame(0.1 * (m - 1), m) for m in range(1, 11)], 0.0, False).result(5)  # 셔터 = 1번(물건 있음)
        other = an.submit([frame(0.1 * (m - 1), m) for m in range(1, 11)], 0.45, False).result(5)  # 5번(물건 없음)
    finally:
        an.close()
    assert res.info["unstable_faces"] == 5
    assert [c["faces"] for c in res.info["candidates"]] == [1] * 10   # 고르기 기준 얼굴 수
    assert "faces" not in res.info["rejects"]
    assert res.info["index"] == 0
    assert len(res.faces) == 2 and res.info["faces_unstable"] == [1]    # 구도에는 물건까지 (오른쪽 = 1번)
    assert res.info["faces_from"] is None
    # 물건이 없는 프레임을 골라도 다른 후보 5장에서 잡혔으니 구도에 더한다 (사진이 조금 넓어질 뿐 사람은 안 잘림)
    assert other.info["index"] == 4 and len(other.faces) == 2 and other.info["faces_unstable"] == []
    assert other.info["faces_added"] == 1 and res.info["faces_added"] == 0


def test_analyzer_keeps_flickering_real_person_in_framing(tmp_path):
    # 리뷰 탐침: A 는 10장 모두, B 는 10장 중 5장 → B 는 고르기에서만 빠지고, B 가 있는 프레임을 고르면 구도에 담긴다
    a = (_shifted(0.42), matrix(0))
    b = (_shifted(0.58), matrix(0))
    script = {m: [a, b] if m % 2 else [a] for m in range(1, 11)}
    an = analyzer(script, tmp_path)
    try:
        res = an.submit([frame(0.1 * (m - 1), m) for m in range(1, 11)], 0.2, False).result(5)  # 3번(B 있음)
    finally:
        an.close()
    assert "faces" not in res.info["rejects"] and res.info["index"] == 2
    assert len(res.faces) == 2 and res.info["faces_unstable"] == [1]


def test_analyzer_borrows_neighbor_faces_for_framing(tmp_path, monkeypatch):
    # 고른 후보에 얼굴이 없고 이웃에 있으면 그 얼굴을 구도용으로 쓴다 (거울은 빌린 뒤 같은 순서로)
    script = {1: [open_face(cx=0.3)], 2: [], 3: [open_face(cx=0.3)]}
    frames = [frame(0.0, 1), frame(0.1, 2), frame(0.3, 3)]
    real = analysis.select_best

    def pick_faceless(cands, shutter_t):
        sel = real(cands, shutter_t)
        sel.index = 1
        return sel

    monkeypatch.setattr(analysis, "select_best", pick_faceless)
    an = analyzer(script, tmp_path)
    try:
        plain = an.submit(frames, 0.1, False).result(5)
        mirrored = an.submit(frames, 0.1, True).result(5)
    finally:
        an.close()
    assert plain.info["index"] == 1 and plain.raw is frames[1].rgb   # 프레임은 고른 그대로
    assert plain.info["faces_from"] == 0                             # 시각이 가장 가까운 후보
    assert plain.info["candidates"][1]["faces"] == 0                 # 점수 · 기록의 후보 수치는 그대로
    assert len(plain.faces) == 1
    a, b = plain.faces[0].box, mirrored.faces[0].box
    assert b[0] == pytest.approx(1 - a[2]) and b[2] == pytest.approx(1 - a[0])
    json.dumps(plain.info)


def test_analyzer_no_face_anywhere_has_empty_faces(tmp_path):
    an = analyzer({}, tmp_path)
    try:
        res = an.submit([frame(0.1 * i, i + 1) for i in range(3)], 0.1, False).result(5)
    finally:
        an.close()
    assert res.faces == [] and res.info["faces_from"] is None and res.info["unstable_faces"] == 0
    assert res.info["faces_unstable"] == []


def test_framing_faces_uses_chosen_frame_faces_including_unstable():
    from walnut.analysis import framing_faces
    raw = [Candidate(0.1 * i, 100.0, [fo(PERSON)] + ([fo(OBJECT)] if i == 0 else [])) for i in range(5)]
    kept, dropped = stable_faces(raw)
    assert dropped == 1
    faces, src, unstable, added = framing_faces(raw, kept, 0)
    assert [f.box for f in faces] == [PERSON, OBJECT] and src is None and unstable == [1] and added == 0
    faces, src, unstable, added = framing_faces(raw, kept, 1)
    assert [f.box for f in faces] == [PERSON] and unstable == [] and added == 0   # 다른 후보 1장에서만 — 더하지 않는다
    empty = [Candidate(0.0, 1.0, [fo(PERSON)]), Candidate(0.1, 1.0, []), Candidate(0.3, 1.0, [fo(PERSON)])]
    k2, _ = stable_faces(empty)
    assert framing_faces(empty, k2, 1)[:2][1] == 0                         # 얼굴이 없으면 빌린다


def test_framing_faces_adds_face_missing_from_chosen_frame_seen_in_two_others():
    from walnut.analysis import FRAMING_MIN_OTHERS, framing_faces
    assert FRAMING_MIN_OTHERS == 2
    near = (0.21, 0.30, 0.30, 0.47)   # 친구가 조금 움직였다 — 시각이 가장 가까운 후보의 박스를 쓴다
    raw = [Candidate(0.0, 1.0, [fo(PERSON), fo(FRIEND)]), Candidate(0.1, 1.0, [fo(PERSON)]),
           Candidate(0.2, 1.0, [fo(PERSON), fo(near)]), Candidate(0.4, 1.0, [fo(PERSON)])]
    kept, _ = stable_faces(raw)
    faces, src, unstable, added = framing_faces(raw, kept, 1)
    assert added == 1 and src is None
    assert [f.box for f in faces] == [PERSON, FRIEND]   # 0번(0.1초)과 2번(0.1초) 동점 — 앞 번호
    faces, _, _, added = framing_faces(raw, kept, 3)
    assert added == 1 and [f.box for f in faces] == [PERSON, near]   # 3번에서는 2번이 가장 가깝다


def test_analyzer_keeps_flickering_person_even_when_chosen_frame_misses_them(tmp_path):
    # 리뷰 탐침: A 10장, B 5장(홀수 번). B 가 없는 프레임(4번)을 골라도 다른 후보에서 잡힌 B 를 구도에 담는다
    from walnut.framing import compute_crop
    a = (_shifted(0.42), matrix(0))
    b = (_shifted(0.58), matrix(0))
    script = {m: [a, b] if m % 2 else [a] for m in range(1, 11)}
    an = analyzer(script, tmp_path)
    try:
        res = an.submit([frame(0.1 * (m - 1), m) for m in range(1, 11)], 0.3, False).result(5)
    finally:
        an.close()
    assert res.info["index"] == 3 and len(res.faces) == 2 and res.info["faces_added"] == 1
    c = compute_crop(1920, 1080, 813, 1083, res.faces)   # 부스 슬롯 기준 크롭에 A · B 둘 다 들어온다
    for f in res.faces:
        assert c.x <= f.box[0] * 1920 and f.box[2] * 1920 <= c.x + c.w


def test_one_off_fake_in_one_other_candidate_is_not_added(tmp_path):
    person = (_shifted(0.3), matrix(0))
    obj = (_shifted(0.8), matrix(0))
    script = {m: [person, obj] if m == 1 else [person] for m in range(1, 6)}
    an = analyzer(script, tmp_path)
    try:
        res = an.submit([frame(0.1 * (m - 1), m) for m in range(1, 6)], 0.3, False).result(5)
    finally:
        an.close()
    assert res.info["index"] == 3 and len(res.faces) == 1 and res.info["faces_added"] == 0


def test_cut_line_records_added_faces_only_when_analyzer_reports_it():
    from walnut.fieldlog import cut_details
    base = {"index": 0, "scores": [None], "rejects": [None], "candidates": [{"t": 0.0, "sharpness": 1.0, "faces": 1}]}
    assert cut_details({**base, "faces_added": 1}, 0.0, [])["faces_added"] == 1
    assert "faces_added" not in cut_details(base, 0.0, [])
