"""후보 평가 · 베스트 컷 선택 시험."""

from __future__ import annotations

from types import SimpleNamespace as P

import numpy as np
import pytest

from facekit import fake_face, with_eyes
from walnut.quality import (Candidate, FaceObs, eye_aspect_ratio, eye_open_from,
                            frontality_from, select_best, sharpness)

BOX = (0.3, 0.2, 0.7, 0.8)


def face(eye=1.0, pose=1.0):
    return FaceObs(box=BOX, eye_open=eye, frontality=pose)


def cand(t=0.0, sharp=100.0, faces=None):
    return Candidate(t=t, sharpness=sharp, faces=[face()] if faces is None else faces)


def rot_y(deg, scale=1.0):
    r = np.radians(deg)
    m = np.eye(4)
    m[:3, :3] = scale * np.array([[np.cos(r), 0, np.sin(r)], [0, 1, 0], [-np.sin(r), 0, np.cos(r)]])
    return m


def test_empty_raises():
    with pytest.raises(ValueError):
        select_best([], 0.0)


def test_single_candidate_returned():
    sel = select_best([cand()], 0.0)
    assert (sel.index, sel.reason, sel.fallback_used, sel.scores) == (0, "single", False, [None])


def test_closed_eye_candidate_loses_to_open_one():
    sel = select_best([cand(0.0, faces=[face(eye=0.1)]), cand(0.1, faces=[face(eye=0.9)])], 0.0)
    assert sel.index == 1 and sel.reason == "best" and not sel.fallback_used
    assert sel.scores[0] is None  # 눈 감음으로 제외


def test_blurred_candidate_rejected():
    # 흐린 쪽이 눈 · 방향은 더 좋아도 제외된다
    sel = select_best([cand(0.0, sharp=20.0, faces=[face(1.0, 1.0)]),
                       cand(0.1, sharp=100.0, faces=[face(0.8, 0.5)])], 0.0)
    assert sel.index == 1 and sel.scores[0] is None


def test_profile_face_loses_to_frontal():
    sel = select_best([cand(0.0, faces=[face(pose=0.1)]), cand(0.1, faces=[face(pose=0.95)])], 0.0)
    assert sel.index == 1


def test_candidate_with_more_faces_wins():
    sel = select_best([cand(0.0, sharp=100.0, faces=[face(), face()]),
                       cand(0.1, sharp=100.0, faces=[face()]),
                       cand(0.2, sharp=100.0, faces=[face(), face()])], 0.2)
    assert sel.index == 2 and sel.scores[1] is None


def test_two_faces_use_the_worse_eye():
    one_open = cand(0.0, faces=[face(eye=1.0), face(eye=0.3)])
    both_open = cand(0.1, faces=[face(eye=0.8), face(eye=0.8)])
    assert select_best([one_open, both_open], 0.0).index == 1


def test_missing_metric_is_not_a_high_score():
    # 눈 지표가 없는 후보가 눈이 활짝 뜬 후보를 이겨선 안 된다 (선명도는 같다)
    missing = cand(0.0, faces=[face(eye=None, pose=1.0)])
    seen = cand(0.1, faces=[face(eye=1.0, pose=1.0)])
    sel = select_best([missing, seen], 0.0)
    assert sel.index == 1
    assert sel.scores[0] is not None and sel.scores[0] < sel.scores[1]


def test_missing_eye_never_triggers_eye_reject():
    sel = select_best([cand(0.0, faces=[face(eye=None)]), cand(0.1, faces=[face(eye=None)])], 0.0)
    assert sel.reason == "best" and None not in sel.scores


def test_missing_metric_uses_remaining_weights():
    # 방향 지표만 없을 때: 선명도 · 눈 가중치(0.4, 0.4)로 다시 나눈다
    a = cand(0.0, sharp=100.0, faces=[face(eye=0.8, pose=None)])
    b = cand(0.1, sharp=50.0, faces=[face(eye=0.8, pose=None)])
    sel = select_best([a, b], 0.0)
    assert sel.scores[0] == pytest.approx((0.4 * 1.0 + 0.4 * 0.8) / 0.8)
    assert sel.scores[1] == pytest.approx((0.4 * 0.0 + 0.4 * 0.8) / 0.8)


def test_no_faces_uses_sharpness_only():
    sel = select_best([cand(0.0, 50.0, faces=[]), cand(0.1, 90.0, faces=[]), cand(0.2, 10.0, faces=[])], 0.0)
    assert (sel.index, sel.reason, sel.fallback_used) == (1, "no_face", False)


def test_all_eye_rejected_picks_highest_eye_not_nearest_shutter():
    # Task H: 모두 눈 감음 탈락이면 셔터에 가까운 컷이 아니라 눈을 가장 크게 뜬 컷
    cands = [cand(0.0, faces=[face(eye=0.1)]), cand(0.4, faces=[face(eye=0.05)]),
             cand(0.9, faces=[face(eye=0.2)])]
    sel = select_best(cands, 0.5)
    assert (sel.index, sel.reason, sel.fallback_used) == (2, "all_rejected", True)
    assert sel.scores == [None, None, None]


def test_all_eye_rejected_picks_highest_eye():
    # c26c24 cut3 실제 값: 멀리 선 사람, 9장 모두 눈 감음 탈락 · 1번은 얼굴 없음 · 셔터 index 7 (눈 0.377, 가장 낮음)
    eyes = [0.406, None, 0.437, 0.566, 0.577, 0.596, 0.527, 0.377, 0.469, 0.449]
    cands = [cand(i * 0.1, faces=[] if e is None else [face(eye=e)]) for i, e in enumerate(eyes)]
    sel = select_best(cands, 0.7)
    assert (sel.index, sel.reason, sel.fallback_used) == (5, "all_rejected", True)
    assert sel.rejects == ["eye", "faces"] + ["eye"] * 8
    assert sel.scores == [None] * 10


def test_all_eye_rejected_tie_uses_tie_key():
    cands = [cand(0.0, faces=[face(eye=0.5)]), cand(0.3, faces=[face(eye=0.5)]), cand(0.6, faces=[face(eye=0.4)])]
    assert select_best(cands, 0.4).index == 1   # 눈이 같으면 셔터에 가까운 쪽


def test_eye_rejected_preferred_over_blur_rejected():
    # 흔들림 탈락보다 눈 감음 탈락 중 눈이 가장 큰 쪽 (흔들린 컷의 눈 값은 보지 않는다)
    cands = [cand(0.0, sharp=100.0, faces=[face(eye=0.3)]), cand(0.5, sharp=10.0, faces=[face(eye=0.69)]),
             cand(0.6, sharp=100.0, faces=[face(eye=0.5)])]
    sel = select_best(cands, 0.5)
    assert sel.rejects == ["eye", "blur", "eye"] and sel.index == 2


def test_blur_only_rejected_keeps_tie_key(monkeypatch):
    # 흔들림만으로 모두 탈락 (실제로는 가장 선명한 컷이 흔들림 탈락일 수 없어 기준을 1 넘게 올려 만든다):
    # 눈 값과 상관없이 지금처럼 셔터에 가장 가까운 컷
    from walnut import quality
    monkeypatch.setattr(quality, "BLUR_REJECT", 1.5)
    cands = [cand(0.0, faces=[face(eye=0.95)]), cand(0.4, faces=[face(eye=0.75)]), cand(0.9, faces=[face(eye=0.99)])]
    sel = select_best(cands, 0.5)
    assert sel.rejects == ["blur"] * 3
    assert (sel.index, sel.reason, sel.fallback_used) == (1, "all_rejected", True)


def test_eyes_measured_closed_are_all_rejected():
    # 실측: 감은 눈은 0.45~0.57 이 나온다. 모든 프레임이 0.5 면 전부 제외되고 기준에 가까운 컷으로 되돌아간다
    cands = [cand(0.0, faces=[face(eye=0.5)]), cand(0.4, faces=[face(eye=0.5)])]
    sel = select_best(cands, 0.4)
    assert sel.reason == "all_rejected" and sel.fallback_used is True


def test_all_rejected_does_not_fall_back_to_lost_person():
    cands = [cand(0.0, faces=[face(eye=0.1), face(eye=0.1)]),
             cand(0.5, faces=[face(eye=0.1)])]
    assert select_best(cands, 0.5).index == 0


def test_tie_prefers_nearest_shutter_then_earlier():
    cands = [cand(0.0), cand(0.4), cand(0.6)]
    assert select_best(cands, 0.5).index == 1  # 0.4 와 0.6 은 같은 거리 → 이른 쪽
    assert select_best(cands, 0.58).index == 2


def test_same_input_same_result():
    cands = [cand(i * 0.1, sharp=40 + 7 * (i % 3), faces=[face(0.5 + 0.1 * (i % 4), 0.8)]) for i in range(8)]
    first = select_best(cands, 0.3)
    for _ in range(5):
        assert select_best(cands, 0.3) == first


def test_sharpness_blurred_lower_than_sharp():
    rng = np.random.default_rng(0)
    sharp_img = (rng.random((64, 64)) * 255).astype(np.uint8)
    blurred = np.full((64, 64), 128, np.uint8)
    blurred[:, 32:] = 140
    assert sharpness(sharp_img) > sharpness(blurred) >= 0.0


def test_sharpness_box_ignores_sharp_background():
    img = np.full((100, 100), 128, np.uint8)
    img[:, :50] = (np.random.default_rng(1).random((100, 50)) * 255).astype(np.uint8)
    assert sharpness(img, (0.6, 0.1, 0.9, 0.9)) < 1.0 < sharpness(img, (0.0, 0.0, 0.4, 1.0))


def test_sharpness_box_clamped_and_empty():
    img = (np.random.default_rng(2).random((40, 40)) * 255).astype(np.uint8)
    assert sharpness(img, (-0.5, -0.5, 1.5, 1.5)) == pytest.approx(sharpness(img))
    assert sharpness(img, (0.5, 0.5, 0.5, 0.9)) == 0.0
    assert sharpness(img, (1.2, 0.0, 1.5, 1.0)) == 0.0


def test_ear_open_higher_than_closed():
    open_ear = eye_aspect_ratio(with_eyes(fake_face(), 0.30))
    closed_ear = eye_aspect_ratio(with_eyes(fake_face(), 0.05))
    assert open_ear > closed_ear
    assert open_ear == pytest.approx(0.30)


def test_ear_same_eye_in_16_9_frame_with_aspect():
    sq = eye_aspect_ratio(with_eyes(fake_face(), 0.25))
    wide_pts = with_eyes(fake_face(), 0.25, aspect=16 / 9)
    assert eye_aspect_ratio(wide_pts) > sq  # 종횡비를 모르면 값이 어긋난다
    assert eye_aspect_ratio(wide_pts, aspect=16 / 9) == pytest.approx(sq)


def bs(left, right):
    return [P(category_name="eyeBlinkLeft", score=left), P(category_name="eyeBlinkRight", score=right),
            P(category_name="jawOpen", score=0.9)]


def test_eye_open_prefers_blendshapes_and_uses_worse_eye():
    assert eye_open_from(bs(0.1, 0.4), None) == pytest.approx(0.6)


def test_eye_open_falls_back_to_ear_then_none():
    assert eye_open_from(None, with_eyes(fake_face(), 0.28)) == pytest.approx(1.0)
    assert eye_open_from([P(category_name="jawOpen", score=0.1)],
                         with_eyes(fake_face(), 0.12)) == pytest.approx(0.0)
    assert eye_open_from(None, None) is None
    assert eye_open_from([], None) is None


def test_eye_open_uses_smaller_ear_when_eyes_differ():
    pts = with_eyes(fake_face(), 0.28, left_ratio=0.12)
    assert eye_open_from(None, pts) == pytest.approx(0.0)


def test_frontality_identity_is_one_and_45_deg_is_zero():
    assert frontality_from(np.eye(4)) == pytest.approx(1.0)
    assert frontality_from(rot_y(45)) == pytest.approx(0.0, abs=1e-9)
    assert frontality_from(rot_y(22.5)) == pytest.approx(0.5)
    assert frontality_from(rot_y(80)) == 0.0


def test_frontality_ignores_scale_and_rejects_invalid():
    assert frontality_from(rot_y(22.5, scale=7.0)) == pytest.approx(0.5)
    assert frontality_from(None) is None
    assert frontality_from(np.zeros((4, 4))) is None
    assert frontality_from(np.eye(3)) is None
    bad = np.eye(4)
    bad[0, 0] = np.nan
    assert frontality_from(bad) is None


def test_near_identical_sharpness_does_not_beat_eye_open():
    # 실제 정지 시퀀스 값(26~27): 선명도 잡음이 0~1 로 부풀면 눈 뜸 0.75 가 0.91 을 이긴다
    a = cand(0.0, sharp=27.0, faces=[face(eye=0.75, pose=0.75)])
    b = cand(0.1, sharp=26.0, faces=[face(eye=0.91, pose=0.75)])
    assert select_best([a, b], 0.0).index == 1


def test_no_face_frames_do_not_blur_reject_face_frames():
    # 얼굴 없음은 프레임 전체(45), 얼굴 있음은 얼굴 영역(14~23)을 잰다 — 서로 비교하지 않는다
    cands = [cand(0.0, sharp=45.0, faces=[]), cand(0.1, sharp=45.0, faces=[]),
             cand(0.2, sharp=14.0, faces=[face(0.8, 0.8)]), cand(0.3, sharp=23.0, faces=[face(0.8, 0.8)])]
    sel = select_best(cands, 0.2)
    assert sel.reason == "best" and sel.fallback_used is False
    assert sel.index in (2, 3) and sel.scores[2] is not None and sel.scores[3] is not None


def test_real_sharpness_difference_still_decides():
    a = cand(0.0, sharp=12.0, faces=[face(0.8, 0.8)])  # 12 > 30 의 35% 라 제외되지 않는다
    b = cand(0.1, sharp=30.0, faces=[face(0.8, 0.8)])
    sel = select_best([a, b], 0.0)  # 셔터는 a 에 더 가깝지만 선명도 차이가 이긴다
    assert sel.index == 1 and sel.scores[1] > sel.scores[0]


# ---- 후보별 탈락 사유 ----

def test_rejects_per_candidate():
    two = [face(), face()]
    cands = [
        cand(t=-0.4, sharp=100.0, faces=[face()]),                  # 얼굴 수가 적다
        cand(t=-0.3, sharp=30.0, faces=two),                        # 최고 선명도의 35% 미만
        cand(t=-0.2, sharp=100.0, faces=[face(), face(eye=0.5)]),   # 한 사람이 눈을 감았다
        cand(t=-0.1, sharp=100.0, faces=two),
        cand(t=0.0, sharp=20.0, faces=[face(eye=0.5), face()]),     # 흐림 + 눈 감음 → 흐림이 먼저
    ]
    sel = select_best(cands, 0.0)
    assert sel.rejects == ["faces", "blur", "eye", None, "blur"]
    assert (sel.index, sel.reason) == (3, "best")


def test_rejects_all_none_for_single_and_no_face():
    assert select_best([cand()], 0.0).rejects == [None]
    sel = select_best([cand(t=0.0, sharp=10.0, faces=[]), cand(t=0.1, sharp=90.0, faces=[])], 0.0)
    assert sel.reason == "no_face" and sel.rejects == [None, None]


def test_all_rejected_keeps_reasons():
    sel = select_best([cand(t=-0.1, faces=[face(eye=0.2)]), cand(t=0.0, faces=[face(eye=0.3)])], 0.0)
    assert sel.reason == "all_rejected" and sel.rejects == ["eye", "eye"]
