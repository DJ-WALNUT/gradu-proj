"""얼굴 기반 크롭 계산 시험. 카메라 · 화면 없이 순수 계산만 본다."""

import inspect
import math

import numpy as np
from PIL import Image, ImageDraw

from walnut import framing
from walnut.analysis import BurstAnalyzer
from walnut.compose import cover_crop
from walnut.framing import (BASE_ZOOM, HOME_DEADBAND, MAX_FACES, MAX_UPSCALE, Crop, compute_crop, home_crop, home_zoom,
                            occlusion_grid)
from walnut.quality import FaceObs

PW, PH = 1920, 1080          # 16:9 컷
SLOT34 = (300, 400)          # 3:4 슬롯
SLOT11 = (400, 400)


def face(cx, cy, w=0.2, h=0.35):
    return FaceObs((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), 1.0, 1.0)


def run(faces, slot=SLOT34, pw=PW, ph=PH):
    return compute_crop(pw, ph, slot[0], slot[1], faces)


def box(c):
    return (c.x, c.y, c.w, c.h)


def contains(c, f, pw=PW, ph=PH):
    """얼굴 박스(여백 없음)가 크롭 안에 다 들어오는가."""
    return (c.x <= f.box[0] * pw and f.box[2] * pw <= c.x + c.w
            and c.y <= f.box[1] * ph and f.box[3] * ph <= c.y + c.h)


def zoom_of(c, slot=SLOT34, pw=PW, ph=PH):
    return cover_crop(pw, ph, *slot)[3] / c.h


def center_x(c):
    return c.x + c.w / 2


def test_max_faces_matches_analyzer():
    assert MAX_FACES == inspect.signature(BurstAnalyzer.__init__).parameters["max_faces"].default


def test_no_faces_gives_widest_center_crop():
    # 얼굴을 못 찾으면 사람이 어디 있는지 모르니 가장 넓게 (1.0배 가운데 = cover_crop).
    # 예전에는 기본 구도(1.3배)였는데, 가장자리에 선 사람이 1배보다 더 잘렸다 (확인 지점 3)
    c = run([])
    assert box(c) == cover_crop(PW, PH, *SLOT34)
    assert c.reason == "no_face" and c.fallback_used is True
    assert abs(center_x(c) - PW / 2) <= 1 and c.h == PH


def test_centered_face_keeps_home_crop():
    c = run([face(0.5, 0.42)])
    assert box(c) == home_crop(PW, PH, *SLOT34)
    assert c.reason == "home" and c.fallback_used is False


def test_group_inside_home_keeps_home():
    faces = [face(0.45, 0.45, 0.08, 0.15), face(0.55, 0.45, 0.08, 0.15)]
    c = run(faces)
    assert box(c) == home_crop(PW, PH, *SLOT34) and c.reason == "home"


def test_group_shifted_right_follows_right():
    faces = [face(0.62, 0.45, 0.08, 0.15), face(0.76, 0.45, 0.08, 0.15)]
    home = home_crop(PW, PH, *SLOT34)
    assert faces[1].box[2] * PW > home[0] + home[2]   # 오른쪽 사람은 기본 구도 밖
    c = run(faces)
    assert c.reason == "follow"
    assert (c.w, c.h) == home[2:]                       # 배율 그대로
    assert c.x > home[0]                                # 오른쪽으로
    assert all(contains(c, f) for f in faces)


def test_group_spread_beyond_home_widens_to_fit_all():
    faces = [face(0.35, 0.45, 0.08, 0.15), face(0.65, 0.45, 0.08, 0.15)]
    c = run(faces)
    assert c.reason == "widen"
    assert zoom_of(c) < BASE_ZOOM
    assert all(contains(c, f) for f in faces)            # 양 끝 사람이 다 들어온다


def test_person_outside_preview_is_included():
    # 예전에는 미리보기(가운데) 밖 얼굴을 지나가는 사람으로 버렸다. 이제는 프레임을 벗어난 일행이다
    main, edge = face(0.5, 0.45, 0.08, 0.15), face(0.72, 0.45, 0.08, 0.15)
    home = home_crop(PW, PH, *SLOT34)
    assert edge.box[0] * PW > home[0] + home[2] - 1     # 미리보기(기본 구도)에는 안 보이던 사람
    c = run([main, edge])
    assert c.reason == "follow"
    assert contains(c, main) and contains(c, edge)


def test_small_background_face_is_ignored():
    main = face(0.5, 0.45, 0.1, 0.2)
    small = face(0.85, 0.3, 0.03, 0.07)                 # 높이 0.07 < 0.4 x 0.2 — 뒤쪽 행인
    alone = run([main])
    both = run([main, small])
    assert box(both) == box(alone) and both.reason == alone.reason
    assert framing.usable_faces([main, small]) == [main]
    # 기준(40%) 이상이면 일행으로 본다
    near = face(0.85, 0.3, 0.05, 0.09)
    assert framing.usable_faces([main, near]) == [main, near]


def test_large_estimated_head_does_not_drop_real_faces():
    # 사람 찾기로 추정한 머리(eye_open 없음)는 팔을 벌리면 크게 잡힌다 — 그것을 기준으로 진짜 손님을 행인으로 빼지 않는다
    real = [face(0.3 + 0.15 * i, 0.45, 0.06, 0.12) for i in range(3)]
    b = face(0.8, 0.4, 0.25, 0.4).box
    head = FaceObs(b, None, None)                       # 높이 0.4 — 0.4 x 0.4 = 0.16 > 0.12
    assert framing.usable_faces(real + [head]) == real + [head]
    # 추정 머리뿐이면 그것끼리 비교한다
    small_head = FaceObs(face(0.2, 0.3, 0.03, 0.05).box, None, None)
    assert framing.usable_faces([head, small_head]) == [head]


def test_max_faces_uses_widest():
    # 가운데에 모여 기본 구도 안이어도, MAX_FACES 명이면 잡히지 않은 사람이 있을 수 있어 가장 넓게
    faces = [face(0.44 + 0.04 * i, 0.45, 0.03, 0.06) for i in range(MAX_FACES)]
    c = run(faces)
    assert c.h == PH and c.w == cover_crop(PW, PH, *SLOT34)[2]
    assert c.reason == "widen"


def test_small_background_faces_do_not_count_toward_max_faces():
    # 걸러 낸 뒤쪽 행인은 'MAX_FACES 이상 → 가장 넓게' 에도 세지 않는다 (2026-11-21 행사 기록).
    # 검출기는 한도를 넘으면 큰 얼굴부터 남기므로, 한도에 닿아 못 잡은 얼굴은 이미 잡힌 작은 얼굴보다도 작다
    for slot, faces in (
            # e2e4 3번 컷: 손님 한 명 + 폭 1.3% 짜리 뒤쪽 얼굴 셋 → 1.0배로 찍혔다
            ((960, 720), [(0.666, 0.687, 0.731, 0.812), (0.648, 0.512, 0.661, 0.537),
                          (0.64, 0.511, 0.653, 0.538), (0.628, 0.513, 0.642, 0.539)]),
            # 960b 4번 컷: 손님 두 명 + 폭 2% 짜리 뒤쪽 얼굴 셋
            ((960, 720), [(0.586, 0.576, 0.643, 0.685), (0.504, 0.671, 0.561, 0.769), (0.19, 0.203, 0.21, 0.238),
                          (0.203, 0.196, 0.224, 0.234), (0.22, 0.199, 0.242, 0.24)])):
        obs = [FaceObs(b, 1.0, 1.0) for b in faces]
        used = framing.usable_faces(obs)
        assert len(obs) >= MAX_FACES > len(used)
        c = compute_crop(PW, PH, *slot, obs)
        assert box(c) == box(compute_crop(PW, PH, *slot, used))   # 행인이 없을 때와 같은 구도
        assert c.reason != "widen" and c.h <= home_crop(PW, PH, *slot)[3]
        assert all(contains(c, f) for f in used)


def test_home_respects_max_upscale():
    # 720p · 큰 슬롯: 1.3배면 slot_h / crop_h 가 MAX_UPSCALE 을 넘는다 → 넘지 않는 가장 큰 배율
    slot = (750, 1000)
    z = home_zoom(1280, 720, *slot)
    assert 1.0 < z < BASE_ZOOM
    h = home_crop(1280, 720, *slot)
    assert slot[1] / h[3] <= MAX_UPSCALE
    assert slot[1] / round(720 / (z + 0.01)) > MAX_UPSCALE   # 조금만 더 확대해도 넘는다
    c = compute_crop(1280, 720, *slot, [face(0.5, 0.42)])
    assert box(c) == h and c.reason == "home"
    assert box(compute_crop(1280, 720, *slot, [])) == cover_crop(1280, 720, *slot)   # 얼굴 없음은 가장 넓게
    # 아주 큰 슬롯은 1배도 넘으므로 1배 (가운데 크롭)
    assert home_zoom(1280, 720, 1500, 2000) == 1.0
    assert home_crop(1280, 720, 1500, 2000) == cover_crop(1280, 720, 1500, 2000)
    # 4K 는 그대로 1.3배
    assert home_zoom(3840, 2160, *slot) == BASE_ZOOM


def test_home_crop_matches_centered_crop_of_ratio():
    for pw, ph in ((1920, 1080), (1280, 720), (1080, 1920)):
        for slot in (SLOT34, SLOT11, (400, 300)):
            z = home_zoom(pw, ph, *slot)
            assert framing.centered_crop(pw, ph, slot[0] / slot[1], z) == home_crop(pw, ph, *slot)
        assert framing.centered_crop(pw, ph, 0.75, 1.0) == cover_crop(pw, ph, 0.75, 1.0)


def test_left_face_moves_crop_left_for_3x4_and_1x1():
    for slot in (SLOT34, SLOT11):
        base = cover_crop(PW, PH, *slot)
        c = run([face(0.2, 0.42)], slot)
        assert c.x < base[0]
        assert c.x <= 0.2 * PW  # 얼굴이 크롭 안에 들어온다
        # 보통 크기 얼굴이라 1.3배 그대로 따라간다 (더 확대는 멀리 선 사람만)
        assert c.reason == "follow"
        assert (c.w, c.h) == home_crop(PW, PH, *slot)[2:]


def test_high_face_moves_crop_up():
    # 16:9 → 3:4 는 가운데 크롭(1배)에 세로 여유가 없지만, 기본 구도(1.3배)는 위아래로 옮길 수 있다
    f = face(0.5, 0.2)
    home = home_crop(PW, PH, *SLOT34)
    c = run([f])
    assert c.y < home[1]
    assert c.y + c.h / 2 < PH / 2
    # 작은 얼굴이 위쪽에 있을 때는 확대하면서 위로 올라간다
    c = run([face(0.5, 0.25, 0.07, 0.12)])
    assert c.h < PH
    assert c.y + c.h / 2 < PH / 2


def test_crop_keeps_ratio_and_stays_inside_image():
    cases = [[], [face(0.1, 0.3)], [face(0.9, 0.8, 0.06, 0.1)], [face(0.2, 0.5), face(0.8, 0.5)],
             [face(0.5, 0.5, 0.05, 0.08)]]
    for slot in (SLOT34, SLOT11, (400, 300)):
        for pw, ph in ((1920, 1080), (1280, 720), (3840, 2160), (1080, 1920)):
            for faces in cases:
                c = run(faces, slot, pw, ph)
                assert c.x >= 0 and c.y >= 0 and c.x + c.w <= pw and c.y + c.h <= ph
                assert abs(c.w / c.h - slot[0] / slot[1]) <= 1.5 / min(c.w, c.h)


def test_two_faces_both_kept_when_possible():
    faces = [face(0.3, 0.42, 0.15), face(0.55, 0.42, 0.15)]
    c = run(faces)
    for f in faces:
        x0, x1 = f.box[0] * PW, f.box[2] * PW
        assert c.x <= x0 and x1 <= c.x + c.w


def test_impossible_fit_minimises_cut():
    # 두 얼굴을 한 크롭에 다 담을 수 없다 (한 명은 반드시 잘린다)
    faces = [face(0.2, 0.42, 0.1, 0.2), face(0.62, 0.42, 0.1, 0.2)]
    c = run(faces)
    assert c.cost >= 0
    # 어느 쪽이든 한 명은 잘리지만 가운데만 자르는 것보다 잘림이 적다
    base = cover_crop(PW, PH, *SLOT34)
    base_cut = framing._cost(base, PW, PH, 1.0, faces)[1]
    cut_now = framing._cost((c.x, c.y, c.w, c.h), PW, PH, 1.0, faces)[1]
    assert cut_now < base_cut


def test_edge_face_never_goes_outside_image():
    for cx in (0.02, 0.98):
        c = run([face(cx, 0.5, 0.06, 0.12)])
        assert c.x >= 0 and c.x + c.w <= PW and c.y >= 0 and c.y + c.h <= PH


def test_zoom_never_exceeds_limit():
    for pw, ph in ((1280, 720), (1920, 1080), (3840, 2160)):
        c = compute_crop(pw, ph, 600, 800, [face(0.5, 0.45, 0.04, 0.07)])
        base = cover_crop(pw, ph, 600, 800)
        if c.h != base[3]:
            assert 800 / c.h <= MAX_UPSCALE + 1e-9


def test_small_centered_faces_zoom_in():
    c = run([face(0.5, 0.45, 0.04, 0.07)], pw=3840, ph=2160)
    assert c.reason == "zoomed"
    assert c.h < 2160


BOOTH_SLOT = (813, 1083)     # 실제 4컷 프레임 슬롯


def face_px(cx, cy, w):
    """1920x1080 에서 가로 w(정규화)인 정사각형에 가까운 얼굴 박스."""
    return face(cx, cy, w, w * PW / PH)


def test_single_person_at_normal_distance_keeps_home():
    # 가까이 선 한 사람 (얼굴 너비 0.10 이상) 은 미리보기와 같은 1.3배 그대로
    for w in (0.12, 0.10):
        c = compute_crop(PW, PH, *BOOTH_SLOT, [face_px(0.5, 0.42, w)])
        assert c.reason == "home", w
        assert box(c) == home_crop(PW, PH, *BOOTH_SLOT)


def test_single_far_person_zooms_past_home():
    # 얼굴 너비 0.08 이하는 기본보다 더 확대한다, MAX_UPSCALE 까지. 2026-11-21 행사(광각)에서 손님 얼굴은
    # 너비 0.05~0.09 였고, 1.3배로는 얼굴 높이가 칸의 약 20% 라 작게 보였다 (FAR_FILL 0.17 → 0.25)
    home = home_crop(PW, PH, *BOOTH_SLOT)
    for w in (0.08, 0.06, 0.05, 0.04, 0.03):
        c = compute_crop(PW, PH, *BOOTH_SLOT, [face_px(0.5, 0.42, w)])
        assert c.reason == "zoomed", w
        assert c.h < home[3] and BOOTH_SLOT[1] / c.h <= MAX_UPSCALE
        assert contains(c, face_px(0.5, 0.42, w))


def test_single_person_off_center_follows_at_home_zoom():
    # 가장자리에 혼자 서도 가까우면 1.3배 그대로 따라간다 (위치와 상관없이 같은 규칙)
    home = home_crop(PW, PH, *BOOTH_SLOT)
    for cx in (0.3, 0.7):
        for w in (0.12, 0.10):
            f = face_px(cx, 0.42, w)
            c = compute_crop(PW, PH, *BOOTH_SLOT, [f])
            assert c.reason == "follow", (cx, w)
            assert (c.w, c.h) == home[2:], (cx, w)
            assert contains(c, f)


def test_single_far_person_off_center_zooms():
    for w in (0.07, 0.04):
        f = face_px(0.3, 0.42, w)
        c = compute_crop(PW, PH, *BOOTH_SLOT, [f])
        assert c.reason == "zoomed", w
        assert c.h < home_crop(PW, PH, *BOOTH_SLOT)[3] and BOOTH_SLOT[1] / c.h <= MAX_UPSCALE
        assert contains(c, f)


def test_group_probes_unchanged_on_booth_slot():
    home = home_crop(PW, PH, *BOOTH_SLOT)
    pair_center = [face_px(0.45, 0.42, 0.06), face_px(0.55, 0.42, 0.06)]
    c = compute_crop(PW, PH, *BOOTH_SLOT, pair_center)
    assert c.reason == "home" and box(c) == home
    pair_right = [face_px(0.70, 0.42, 0.06), face_px(0.80, 0.42, 0.06)]
    c = compute_crop(PW, PH, *BOOTH_SLOT, pair_right)
    assert c.reason == "follow" and (c.w, c.h) == home[2:] and c.x > home[0]
    assert all(contains(c, f) for f in pair_right)
    spread = [face_px(0.36, 0.42, 0.06), face_px(0.5, 0.42, 0.06), face_px(0.64, 0.42, 0.06)]
    c = compute_crop(PW, PH, *BOOTH_SLOT, spread)
    assert c.reason == "widen" and c.h > home[3]
    assert all(contains(c, f) for f in spread)


def test_normal_sized_face_does_not_zoom_past_home():
    c = run([face(0.5, 0.42, 0.2, 0.35)])
    assert box(c) == home_crop(PW, PH, *SLOT34)


def test_zoom_stops_at_max_upscale(monkeypatch):
    # 720p 는 기본 구도부터 MAX_UPSCALE 에 막혀 더 확대하지 못한다 (기본 구도 그대로)
    faces = [face(0.5, 0.45, 0.04, 0.07)]   # 멀리 선 사람 (기본 구도에서도 작다)
    slot = (750, 1000)
    lo = compute_crop(1280, 720, *slot, faces)
    hi = compute_crop(3840, 2160, *slot, faces)
    assert lo.reason == "home" and box(lo) == home_crop(1280, 720, *slot)
    assert hi.reason == "zoomed"
    assert slot[1] / lo.h <= MAX_UPSCALE + 1e-9
    assert slot[1] / round(720 / 1.2) > MAX_UPSCALE         # 다음 확대 단계(1.2)는 한계를 넘는다
    assert 720 / lo.h < 0.8 * (2160 / hi.h)                  # 4K 는 눈에 띄게 더 확대한다
    # 한계를 풀면 720p 도 더 확대한다 = 한계가 실제로 막고 있다
    monkeypatch.setattr(framing, "MAX_UPSCALE", 99)
    free = compute_crop(1280, 720, *slot, faces)
    assert free.h < lo.h


def test_zoomed_crop_keeps_all_faces():
    faces = [face(0.46, 0.45, 0.03, 0.05), face(0.54, 0.45, 0.03, 0.05)]
    c = run(faces, pw=3840, ph=2160)
    assert c.h < 2160
    for f in faces:
        assert c.x <= f.box[0] * 3840 and f.box[2] * 3840 <= c.x + c.w
        assert c.y <= f.box[1] * 2160 and f.box[3] * 2160 <= c.y + c.h


def test_max_faces_means_no_zoom():
    faces = [face(0.35 + 0.1 * i, 0.45, 0.04, 0.07) for i in range(MAX_FACES)]
    c = run(faces, pw=3840, ph=2160)
    assert c.h == 2160  # 3:4 에서 z=1 은 세로 전체


def test_same_input_same_crop():
    faces = [face(0.3, 0.4, 0.07, 0.12), face(0.5, 0.45, 0.07, 0.12)]
    assert run(faces) == run(faces)


def test_face_cut_is_lower_than_center_crop_on_shifted_samples():
    for cx in (0.1, 0.15, 0.2, 0.8, 0.85, 0.9):
        f = [face(cx, 0.45)]
        c = run(f)
        base = cover_crop(PW, PH, *SLOT34)
        base_cut = framing._cost(base, PW, PH, 1.0, f)[1]
        cut_now = framing._cost((c.x, c.y, c.w, c.h), PW, PH, 1.0, f)[1]
        assert cut_now < base_cut


def test_small_faces_zoom_in_at_1080p_with_upscale_limit():
    # 광각 16:9 1080p: 얼굴이 작게 모이면 확대하고, 슬롯이 크면 MAX_UPSCALE 에서 멈춘다
    small = [face(0.5, 0.45, 0.04, 0.07)]
    c = compute_crop(1920, 1080, 300, 400, small)
    assert c.reason == "zoomed" and c.h < 1080
    big_slot = compute_crop(1920, 1080, 1200, 1600, small)  # 기본 배율이 1.08 로 깎이고 z=1.1 부터 한계 초과 → 기본 구도
    assert box(big_slot) == home_crop(1920, 1080, 1200, 1600) and big_slot.h == 1000
    mid_slot = compute_crop(1920, 1080, 600, 800, small)
    assert mid_slot.h < 1080 and 800 / mid_slot.h <= MAX_UPSCALE + 1e-9


# --- 장식 가림 지도 -------------------------------------------------------------

def _frame(size=(1000, 1000)):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _paint(img, box):
    ImageDraw.Draw(img).rectangle(box, fill=(255, 0, 0, 255))


SLOT = {"cx": 500, "cy": 500, "w": 300, "h": 400, "rot": 0}


def test_grid_marks_opaque_corner_only():
    f = _frame()
    _paint(f, (500, 600, 649, 699))    # 슬롯 (350..650, 300..700) 의 오른쪽 절반 x 아래 4분의 1
    g = occlusion_grid(f, SLOT, cols=12)
    assert g.shape == (16, 12)         # rows = round(12 * 400 / 300)
    assert g[-1, -1] == 1.0 and g[-2, -2] == 1.0
    assert g[0, 0] == 0.0 and g[0, -1] == 0.0 and g[-1, 0] == 0.0
    assert g.min() >= 0.0 and g.max() <= 1.0


def test_grid_ignores_specks():
    f = _frame()
    for x, y in ((400, 400), (450, 500), (550, 350)):
        _paint(f, (x, y, x + 1, y + 1))   # 2x2 잔티
    _paint(f, (600, 650, 601, 651))
    assert occlusion_grid(f, SLOT).max() == 0.0


def test_grid_follows_rotated_slot():
    # rot=90 (시계 방향): 슬롯의 똑바른 좌상단 모서리는 프레임에서 오른쪽 위에 놓인다
    slot = {"cx": 500, "cy": 500, "w": 200, "h": 400, "rot": 90}
    th = math.radians(slot["rot"])
    lx, ly = -slot["w"] / 2 + 25, -slot["h"] / 2 + 25   # 슬롯 좌표의 좌상단 근처
    px = slot["cx"] + lx * math.cos(th) - ly * math.sin(th)   # compose.slot_corners 와 같은 식
    py = slot["cy"] + lx * math.sin(th) + ly * math.cos(th)
    f = _frame()
    _paint(f, (px - 20, py - 20, px + 20, py + 20))
    g = occlusion_grid(f, slot, cols=8)
    assert g.shape == (16, 8)
    assert g[0, 0] > 0.5
    assert g[-1, -1] == 0.0 and g[0, -1] == 0.0 and g[-1, 0] == 0.0


def _grid_with(covered_cols=None, covered_rows=None, cols=20, rows=20):
    g = np.zeros((rows, cols), dtype=np.float32)
    if covered_cols:
        g[:, covered_cols[0]:covered_cols[1]] = 1.0
    if covered_rows:
        g[covered_rows[0]:covered_rows[1], :] = 1.0
    return g


def _face_rel(c, f):
    """얼굴 박스가 크롭 안에서 놓인 정규화 위치 (좌, 위, 우, 아래)."""
    return ((f.box[0] * PW - c.x) / c.w, (f.box[1] * PH - c.y) / c.h,
            (f.box[2] * PW - c.x) / c.w, (f.box[3] * PH - c.y) / c.h)


def test_crop_moves_face_away_from_right_decoration():
    # 기본 구도 밖이라 따라갈 때, 장식이 있으면 얼굴이 장식을 피한 자리로 간다
    f = [face(0.7, 0.42, 0.08, 0.15)]
    grid = _grid_with(covered_cols=(10, 20))     # 오른쪽 절반 (가로 0.5 부터)
    plain = compute_crop(PW, PH, *SLOT34, f)
    c = compute_crop(PW, PH, *SLOT34, f, occlusion=grid)
    assert _face_rel(plain, f[0])[2] > 0.5         # 장식이 없으면 얼굴이 장식에 걸친다
    assert _face_rel(c, f[0])[2] <= 0.5            # 장식이 있으면 얼굴이 장식 왼쪽에 온다
    assert contains(c, f[0])


def test_inside_home_ignores_decoration():
    # 기본 구도에 다 들어오면 장식 때문에 구도를 흔들지 않는다 (장식 회피는 따라갈 때만)
    f = [face(0.5, 0.42, 0.2, 0.35)]
    grid = _grid_with(covered_cols=(13, 20))
    c = compute_crop(PW, PH, *SLOT34, f, occlusion=grid)
    assert box(c) == home_crop(PW, PH, *SLOT34) and c.reason == "home"


def test_occlusion_is_minor_next_to_cut():
    # 퍼진 두 사람을 다 담으면 오른쪽 사람이 장식에 걸려도, 장식을 피하려고 사람을 자르지 않는다
    faces = [face(0.35, 0.45, 0.08, 0.15), face(0.65, 0.45, 0.08, 0.15)]
    grid = _grid_with(covered_cols=(10, 20))
    c = compute_crop(PW, PH, *SLOT34, faces, occlusion=grid)
    assert all(contains(c, f) for f in faces)
    assert framing._cost(box(c), PW, PH, 1.0, faces)[1] == 0.0
    assert framing.W_OCCLUDE < framing.W_CUT


def test_crop_moves_face_up_from_bottom_decoration():
    # 멀리 선 사람이라 기본보다 확대할 때, 확대한 자리가 아래 장식을 피한다
    f = [face(0.5, 0.4, 0.04, 0.07)]
    grid = _grid_with(covered_rows=(8, 20))      # 아래 60% (세로 0.4 부터)
    plain = compute_crop(PW, PH, *SLOT34, f)
    c = compute_crop(PW, PH, *SLOT34, f, occlusion=grid)
    assert _face_rel(plain, f[0])[3] > 0.4         # 장식이 없으면 얼굴이 장식에 걸친다
    assert _face_rel(c, f[0])[3] <= 0.4            # 장식이 있으면 얼굴이 장식 위로 올라간다


def test_no_decoration_gives_same_crop_as_without_grid():
    for f in ([face(0.2, 0.42)], [face(0.5, 0.45, 0.07, 0.12)], []):
        zero = np.zeros((20, 15), dtype=np.float32)
        assert compute_crop(PW, PH, *SLOT34, f, occlusion=zero) == run(f)


def test_fully_covered_slot_still_returns_valid_crop():
    full = np.ones((20, 15), dtype=np.float32)
    for f in ([face(0.5, 0.42)], [face(0.2, 0.42, 0.1, 0.2), face(0.62, 0.42, 0.1, 0.2)]):
        c = compute_crop(PW, PH, *SLOT34, f, occlusion=full)
        assert c.x >= 0 and c.y >= 0 and c.x + c.w <= PW and c.y + c.h <= PH
        assert abs(c.w / c.h - SLOT34[0] / SLOT34[1]) <= 1.5 / min(c.w, c.h)


def test_occlusion_never_outweighs_cutting_the_face_off():
    # 오른쪽이 거의 다 가려져도, 가리지 않으려고 얼굴을 크롭 밖으로 밀어내지는 않는다
    f = [face(0.5, 0.42, 0.2, 0.35)]
    grid = _grid_with(covered_cols=(2, 20))
    c = compute_crop(PW, PH, *SLOT34, f, occlusion=grid)
    x0, _, x1, _ = _face_rel(c, f[0])
    assert x0 >= 0.0 and x1 <= 1.0
    cut = framing._cost((c.x, c.y, c.w, c.h), PW, PH, 1.0, f)[1]
    assert cut == 0.0


# --- 확인 지점 3: 기본 구도 안이어도 가운데로 (데드존) -----------------------------

# 실제 기록 (1920x1080, 슬롯 813x1083, 거울 적용된 박스). 모두 기본 구도 안이라 예전에는 home 이었고
# 얼굴이 칸 구석(왼쪽 · 오른쪽 · 아래)에 남았다.
REAL_OFF_CENTER = {
    "f1cc85 cut0": (0.355, 0.647, 0.459, 0.861),   # 아래 왼쪽
    "4c2cd1 cut1": (0.363, 0.306, 0.446, 0.480),   # 왼쪽
    "f5e801 cut0": (0.378, 0.498, 0.477, 0.664),   # 왼쪽 아래
    "f5e801 cut1": (0.373, 0.296, 0.462, 0.481),   # 왼쪽
    "f5e801 cut2": (0.555, 0.271, 0.645, 0.455),   # 오른쪽
    "a80dc3 cut3": (0.411, 0.573, 0.517, 0.815),   # 아래
}


def _rel_center(c, faces):
    """얼굴 전체 박스 중심이 크롭 안에서 놓인 자리 (가로, 세로 비율)."""
    ux = (min(f.box[0] for f in faces) + max(f.box[2] for f in faces)) / 2 * PW
    uy = (min(f.box[1] for f in faces) + max(f.box[3] for f in faces)) / 2 * PH
    return (ux - c.x) / c.w, (uy - c.y) / c.h


def test_real_off_center_faces_inside_home_are_followed_to_center():
    home = home_crop(PW, PH, *BOOTH_SLOT)
    for name, b in REAL_OFF_CENTER.items():
        f = [FaceObs(b, 1.0, 1.0)]
        assert framing._inside(home, PW, PH, f), name           # 기본 구도 안 (예전 규칙이면 home)
        c = compute_crop(PW, PH, *BOOTH_SLOT, f)
        assert c.reason == "follow", name
        assert (c.w, c.h) == home[2:], name                      # 배율은 기본 그대로
        assert contains(c, f[0]), name
        rx, ry = _rel_center(c, f)
        # 가로 · 세로 각각: 목표점 데드존 안이거나, 더 못 옮기는 원본 경계에 닿았다
        assert abs(rx - framing.TARGET[0]) <= HOME_DEADBAND[0] or c.x == 0 or c.x + c.w == PW, (name, rx)
        assert abs(ry - framing.TARGET[1]) <= HOME_DEADBAND[1] or c.y == 0 or c.y + c.h == PH, (name, ry)
        hx, hy = _rel_center(Crop(*home, "home", False, 0.0), f)
        assert math.hypot(rx - framing.TARGET[0], ry - framing.TARGET[1]) <             math.hypot(hx - framing.TARGET[0], hy - framing.TARGET[1]), name   # 기본 구도보다 가운데에 가깝다


def test_face_near_target_inside_deadband_keeps_home():
    # 목표점에서 데드존 안쪽으로 조금 비켜선 얼굴은 구도를 흔들지 않는다
    home = home_crop(PW, PH, *BOOTH_SLOT)
    tx = home[0] + framing.TARGET[0] * home[2]
    ty = home[1] + framing.TARGET[1] * home[3]
    for dx, dy in ((0.8, 0), (-0.8, 0), (0, 0.8), (0, -0.8), (0.6, 0.6)):
        cx = (tx + dx * HOME_DEADBAND[0] * home[2]) / PW
        cy = (ty + dy * HOME_DEADBAND[1] * home[3]) / PH
        c = compute_crop(PW, PH, *BOOTH_SLOT, [face_px(cx, cy, 0.10)])
        assert c.reason == "home" and box(c) == home, (dx, dy)


def test_face_just_outside_deadband_follows():
    home = home_crop(PW, PH, *BOOTH_SLOT)
    tx = home[0] + framing.TARGET[0] * home[2]
    cx = (tx + 1.5 * HOME_DEADBAND[0] * home[2]) / PW
    f = face_px(cx, framing.TARGET[1] * home[3] / PH + home[1] / PH, 0.10)
    assert framing._inside(home, PW, PH, [f])
    c = compute_crop(PW, PH, *BOOTH_SLOT, [f])
    assert c.reason == "follow" and (c.w, c.h) == home[2:] and c.x > home[0]
    assert abs(_rel_center(c, [f])[0] - framing.TARGET[0]) <= HOME_DEADBAND[0]


def test_far_off_center_face_inside_home_still_zooms():
    # 멀리 선 사람은 기본 구도 안 · 데드존 밖이어도 기본보다 확대할 수 있다 (가운데로 오면서)
    home = home_crop(PW, PH, *BOOTH_SLOT)
    f = face_px(0.42, 0.55, 0.03)
    assert framing._inside(home, PW, PH, [f])
    c = compute_crop(PW, PH, *BOOTH_SLOT, [f])
    assert c.reason in ("zoomed", "follow")
    assert contains(c, f)
    rx, ry = _rel_center(c, [f])
    assert abs(rx - framing.TARGET[0]) <= HOME_DEADBAND[0]


def test_flickering_second_person_is_kept_in_crop():
    # 리뷰 탐침 (사용자 결정: 진짜 사람을 자르는 것이 사진이 조금 넓어지는 것보다 나쁘다):
    # A(x 0.42) 와 고르기에서 빠진 B(x 0.58) 를 함께 넘기면 둘 다 크롭 안이다
    a, b = face_px(0.42, 0.42, 0.06), face_px(0.58, 0.42, 0.06)
    c = compute_crop(PW, PH, *BOOTH_SLOT, [a, b])
    assert c.reason in ("home", "follow", "widen")
    assert contains(c, a) and contains(c, b)


def test_90986a_fake_face_widens_but_never_cuts_person():
    person = FaceObs((0.589, 0.266, 0.673, 0.435), 1.0, 1.0)
    fake = FaceObs((0.683, 0.643, 0.778, 0.764), 1.0, 1.0)
    c = compute_crop(PW, PH, *BOOTH_SLOT, [person, fake])
    assert contains(c, person) and contains(c, fake)
