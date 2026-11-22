"""촬영 세션 규칙 테스트."""
from __future__ import annotations

import pytest
from PIL import Image

from walnut.session import ShootSession

CAP = {"countdown_sec": 10, "between_sec": 2, "extra_shots": 0, "allow_retake": True,
       "review_auto_sec": 25, "mirror": True}


def frame_with_cuts(n, sizes=None):
    sizes = sizes or [(100, 100)] * n
    return {"slots": [{"id": k + 1, "shot": k, "cx": 0.5, "cy": 0.5, "w": sizes[k][0], "h": sizes[k][1],
                       "rot": 0, "ratio": "free"} for k in range(n)]}


def img(i):
    return Image.new("RGB", (4, 4), (i, 0, 0))


def tag(im):
    return im.getpixel((0, 0))[0]


def test_extra_mode_pick_order_is_cut_order():
    s = ShootSession(frame_with_cuts(2), {**CAP, "extra_shots": 2})
    assert s.total_shots() == 4
    for i in range(4):
        s.add_shot(img(i))
    assert s.capturing_done()
    s.toggle_pick(2); s.toggle_pick(0); s.toggle_pick(3)  # 셋째는 무시 (n=2)
    assert s.pick_order() == [1, None, 0, None] and s.picks_complete()
    assert [tag(c) for c in s.cuts()] == [2, 0]
    s.toggle_pick(2)
    assert s.pick_order() == [0, None, None, None]  # 빼면 순서 당김


def test_extra_mode_cuts_requires_picks():
    s = ShootSession(frame_with_cuts(2), {**CAP, "extra_shots": 1})
    for i in range(3):
        s.add_shot(img(i))
    s.toggle_pick(0)
    with pytest.raises(ValueError):
        s.cuts()


def test_retake_replaces_only_unkept():
    s = ShootSession(frame_with_cuts(3), CAP)
    for i in range(3):
        s.add_shot(img(i))
    assert s.can_retake() and s.capturing_done()
    s.begin_retake([True, False, True])
    assert s.retake_queue == [1] and not s.capturing_done() and s.next_cut() == 1
    s.add_shot(img(9))
    assert [tag(c) for c in s.cuts()] == [0, 9, 2] and s.capturing_done()
    assert len(s.shots) == 3


def test_retake_multiple_in_order():
    s = ShootSession(frame_with_cuts(3), CAP)
    for i in range(3):
        s.add_shot(img(i))
    s.begin_retake([False, True, False])
    assert s.next_cut() == 0
    s.add_shot(img(7)); assert not s.capturing_done() and s.next_cut() == 2
    s.add_shot(img(8))
    assert [tag(c) for c in s.cuts()] == [7, 1, 8] and s.capturing_done()


def test_begin_retake_validation():
    s = ShootSession(frame_with_cuts(2), CAP)
    for i in range(2):
        s.add_shot(img(i))
    with pytest.raises(ValueError):
        s.begin_retake([True])
    x = ShootSession(frame_with_cuts(2), {**CAP, "allow_retake": False})
    with pytest.raises(ValueError):
        x.begin_retake([True, False])


def test_ratio_per_shot_and_preview_ratio():
    f = frame_with_cuts(3, [(100, 100), (200, 100), (100, 200)])
    s = ShootSession(f, CAP)
    assert [s.ratio_for_shot(i) for i in range(3)] == [1.0, 2.0, 0.5]
    assert s.next_cut() == 0
    f2 = frame_with_cuts(3, [(100, 100), (200, 100), (200, 100)])
    e = ShootSession(f2, {**CAP, "extra_shots": 1})
    assert all(e.ratio_for_shot(i) == 2.0 for i in range(4))


def test_next_cut_during_initial_capture():
    s = ShootSession(frame_with_cuts(2), CAP)
    assert s.next_cut() == 0
    s.add_shot(img(0))
    assert s.next_cut() == 1 and not s.capturing_done()


def test_allow_retake_false_or_extra_mode_disables_retake():
    assert ShootSession(frame_with_cuts(2), CAP).can_retake()
    assert not ShootSession(frame_with_cuts(2), {**CAP, "allow_retake": False}).can_retake()
    assert not ShootSession(frame_with_cuts(2), {**CAP, "extra_shots": 1}).can_retake()


# ---- 컷별 얼굴 (cut_faces 는 cuts() 와 같은 순서) ----
def faces_tag(i):
    return [f"face{i}"]


def test_retake_replaces_faces_too():
    s = ShootSession(frame_with_cuts(3), CAP)
    for i in range(3):
        s.add_shot(img(i), faces_tag(i))
    s.begin_retake([True, False, True])
    s.add_shot(img(9), faces_tag(9))
    assert [tag(c) for c in s.cuts()] == [0, 9, 2]
    assert s.cut_faces() == [faces_tag(0), faces_tag(9), faces_tag(2)]
    s.begin_retake([False, True, True])
    s.add_shot(img(5))  # 얼굴 정보 없이 다시 찍으면 옛 얼굴이 남지 않는다
    assert s.cut_faces() == [None, faces_tag(9), faces_tag(2)]


def test_extra_mode_faces_follow_pick_order():
    s = ShootSession(frame_with_cuts(2), {**CAP, "extra_shots": 2})
    for i in range(4):
        s.add_shot(img(i), faces_tag(i))
    s.toggle_pick(3); s.toggle_pick(1)
    assert [tag(c) for c in s.cuts()] == [3, 1]
    assert s.cut_faces() == [faces_tag(3), faces_tag(1)]
    s.toggle_pick(3); s.toggle_pick(0)  # 빼고 다시 고르면 순서도 따라간다
    assert [tag(c) for c in s.cuts()] == [1, 0]
    assert s.cut_faces() == [faces_tag(1), faces_tag(0)]


def test_extra_mode_cut_faces_requires_picks():
    s = ShootSession(frame_with_cuts(2), {**CAP, "extra_shots": 1})
    for i in range(3):
        s.add_shot(img(i))
    with pytest.raises(ValueError):
        s.cut_faces()


def test_cut_faces_when_shots_set_directly():
    s = ShootSession(frame_with_cuts(2), CAP)
    s.shots = [img(0), img(1)]  # shot_faces 없이 넣은 경우 (시험 · 옛 경로)
    assert s.cut_faces() == [None, None]
