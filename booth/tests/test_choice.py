"""컷마다 '찍은 그대로' · 'AI 추천' 고르기 (Task G).

가짜 분석기(test_capture_burst.FakeAnalyzer)로 결과가 언제 · 무엇으로 끝나는지 시험이 정한다.
"""

from __future__ import annotations

import dataclasses
import json
import math

import numpy as np
import pygame
import pytest
from PIL import Image

from test_capture_burst import (BURST, SETTINGS, SMART, FakeAnalyzer, _restore_sfx, make_result, marked,  # noqa: F401
                                read_records, start, tick, to_shutter)
from walnut.compose import compose, cover_crop
from walnut.framing import compute_crop, home_crop
from walnut.quality import FaceObs
from walnut.scenes.capture import ANALYZE_TIMEOUT, BETWEEN, BURST_AFTER, COUNTDOWN, process_cut
from walnut.scenes.choice import CHOICE_SEC, ChoiceScene, choice_layout
from walnut.session import AS_SHOT, AUTO, ShootSession

BOTH = {**BURST, **SMART}
LOG = {"BOOTH_CAPTURE_LOG": "1"}
# FakeCamera(1280x720) 의 슬롯 2:3 기본 구도 가운데 (TARGET) 에 선 얼굴 → 구도 보정 결과도 기본 구도
# 가운데 가까이 선 사람 (너비 0.1) — 구도 보정이 기본 구도 그대로라 '찍은 그대로' 와 같다 (framing.FAR_FILL 보다 크다)
CENTER_FACE = [FaceObs((576 / 1280, 250 / 720, 704 / 1280, 390 / 720), 0.9, 0.9)]


def key(k: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode="", mod=0, scancode=0)


ENTER, LEFT, RIGHT, F2, F5 = (key(k) for k in (pygame.K_RETURN, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_F2,
                                               pygame.K_F5))


def name(app) -> str:
    return type(app.scene).__name__


def finish_cut(app, raw: np.ndarray | None = None, faces=None) -> None:
    """지금 촬영 장면에서 한 컷: 카운트다운 → (버스트면 수집) → 분석 결과 raw."""
    scene = app.scene
    while scene.state in (COUNTDOWN, BETWEEN):
        app.step(0.1, [])
    if app.cfg.burst:
        tick(app, BURST_AFTER + 0.1)
    res = make_result(app.frame if raw is None else raw)
    res.faces = list(faces or [])
    app.analyzer.futures[-1].set_result(res)
    app.step(0.1, [])


def cut_lines(app) -> list[dict]:
    return [r for r in read_records(app) if r["type"] == "cut"]


# ---- 꺼짐: 지금과 같다 ----
def test_flags_off_no_choice_scene(start):
    app, scene = start({}, None)
    seen, lines = [], []
    for _ in range(400):
        app.step(0.1, [])
        seen.append(name(app))
        lines.append(app.scene.remote_state())
        if name(app) == "ReviewScene":
            break
    assert "ChoiceScene" not in seen and seen[-1] == "ReviewScene"
    assert not any(line.startswith("A") for line in lines)  # 리모컨에 가는 줄도 지금과 같다
    s = scene.shoot.session
    assert s.cut_choices() == [AUTO] * s.n
    plain = compose(scene.shoot.frame_png, s.frame["slots"], s.cuts())
    assert app.scene.collage.tobytes() == plain.tobytes()  # 픽셀까지 지금과 같다


# ---- 고르기 화면 ----
def test_choice_shown_after_cut_when_smart_on(start):
    app, scene = start(BOTH, FakeAnalyzer())
    finish_cut(app, marked(7))
    assert name(app) == "ChoiceScene"
    ch = app.scene
    assert ch.data.cut == 0 and len(scene.shoot.session.shots) == 1
    assert ch.sel == 1  # 기본은 AI 추천 (시간이 다 되면 고르는 쪽)
    assert ch.remote_state() == "A|1|100|100"  # 리모컨 고르기 줄: 커서 · 남은 0.1초 · 전체 0.1초
    app.step(0.1, [LEFT])
    assert app.scene.remote_state() == "A|0|99|100"  # 키를 누르면 시간은 처음부터 (그 뒤 한 걸음 0.1초)


def _a_line(ch) -> tuple[int, int, int]:
    kind, *rest = ch.remote_state().split("|")
    assert kind == "A" and len(rest) == 3
    return tuple(int(v) for v in rest)


def test_remote_line_counts_down_and_resets(start):
    app, scene = start(BOTH, FakeAnalyzer())
    finish_cut(app, marked(7))
    ch = app.scene
    tick(app, 3.0)
    sel, left, full = _a_line(ch)
    assert sel == 1 and full == round(CHOICE_SEC * 10)
    assert left == math.ceil((CHOICE_SEC - ch.idle_t) * 10 - 1e-6) and 65 <= left <= 71  # 0.1초 단위 올림
    tick(app, 3.0)
    assert _a_line(ch)[1] < left  # 줄어든다
    app.step(0.1, [RIGHT])
    assert _a_line(ch) == (1, 99, 100)  # 키 → 처음부터 (그 뒤 한 걸음 0.1초)
    tick(app, 2.0)
    app.step(0.1, [LEFT])
    assert _a_line(ch)[:2] == (0, 99)
    tick(app, 2.0)
    assert _a_line(ch)[1] < 99
    app.step(0.1, [])  # 그려야 탭 영역이 생긴다
    assert _a_line(ch)[1] < 99
    ch.hits.tap((1, 1))  # 빈 곳 탭 → 시간만 처음부터
    assert name(app) == "ChoiceScene" and _a_line(ch) == (0, 100, 100)
    ch.idle_t = CHOICE_SEC + 5  # 넘쳐도 음수는 보내지 않는다
    assert _a_line(ch)[1] == 0


def test_extra_mode_choice_sends_same_remote_line(start):
    app, scene = start(BOTH, FakeAnalyzer(), EXTRA)
    finish_cut(app, marked(7))
    assert name(app) == "ChoiceScene" and app.scene.remote_state() == "A|1|100|100"


def test_timeout_picks_ai_after_10s(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer())
    finish_cut(app, marked(7))
    ai = scene.shoot.session.shots[0]
    assert CHOICE_SEC == 10.0  # 사용자 결정 (2026-11-17)
    tick(app, 9.8)
    assert name(app) == "ChoiceScene"
    tick(app, 0.4)
    assert name(app) == "CaptureScene" and app.scene.state == COUNTDOWN  # 고르는 동안 쉬었으니 바로 카운트다운
    s = scene.shoot.session
    assert s.shots[0] is ai and s.cut_choices()[0] == AUTO
    assert cut_lines(app)[-1]["choice"] == "timeout_ai"


def test_guest_pick_goes_straight_to_countdown(start):
    app, scene = start(BOTH, FakeAnalyzer())
    finish_cut(app, marked(7))
    app.step(0.1, [LEFT, ENTER])
    assert name(app) == "CaptureScene" and app.scene is not scene and app.scene.state == COUNTDOWN
    assert app.scene.remain > app.scene.countdown - 0.2  # 다음 컷 카운트다운을 처음부터


def test_skipped_choice_keeps_between_pause(start):
    app, scene = start(BOTH, FakeAnalyzer())
    finish_cut(app, None, CENTER_FACE)  # 두 장이 같아 고르기 없음
    assert name(app) == "CaptureScene" and app.scene is scene and scene.state == BETWEEN


def test_retake_pick_goes_straight_to_countdown(start):
    app, scene = start(BOTH, FakeAnalyzer())
    s = scene.shoot.session
    for k in range(s.n):
        finish_cut(app, marked(10 + k))
        app.step(0.1, [ENTER])
    app.scene.press("retake")
    app.scene.keep = [False, False, True, True]
    app.scene._retake()
    finish_cut(app, marked(50))
    app.step(0.1, [ENTER])
    assert name(app) == "CaptureScene" and app.scene.state == COUNTDOWN and s.retake_queue == [1]


def test_dev_all_leaving_analysis_screen_still_writes_cut_line(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer())
    app.cfg = dataclasses.replace(app.cfg, dev="all")
    finish_cut(app, marked(7))
    assert name(app) == "BurstShowScene" and cut_lines(app) == []
    app.step(0.1, [F5])
    assert name(app) == "IdleScene"
    assert [c["choice"] for c in cut_lines(app)] == ["skipped"]
    tick(app, 21.0)
    assert name(app) == "IdleScene" and len(cut_lines(app)) == 1


def test_dev_all_choice_writes_cut_line_once(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer())
    app.cfg = dataclasses.replace(app.cfg, dev="all")
    finish_cut(app, marked(7))
    app.step(0.1, [ENTER])  # 분석 화면 → 고르기
    app.step(0.1, [LEFT, ENTER])
    assert [c["choice"] for c in cut_lines(app)] == ["as_shot"]


def test_input_resets_the_timer(start):
    app, scene = start(BOTH, FakeAnalyzer())
    finish_cut(app, marked(7))
    tick(app, 4.0)
    app.step(0.1, [LEFT])
    tick(app, 4.0)
    assert name(app) == "ChoiceScene" and app.scene.left() >= 1


def test_pick_as_shot_uses_shutter_frame_and_home_crop(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer())
    base = app.frame
    finish_cut(app, marked(7), CENTER_FACE)
    ch = app.scene
    assert ch.data.as_crop == home_crop(1280, 720, 160, 240)
    app.step(0.1, [LEFT, ENTER])
    assert name(app) == "CaptureScene"
    s = scene.shoot.session
    assert s.cut_choices()[0] == AS_SHOT and s.shot_faces[0] is None
    want = process_cut(app, base, scene.shoot)
    assert s.shots[0].size == (1280, 720) and s.shots[0].tobytes() == want.tobytes()
    # 합성 · 축소판: 얼굴과 상관없이 기본 구도 (모든 슬롯)
    from walnut.scenes.capture import smart_cropper, thumb_crop
    s.shot_faces[0] = [FaceObs((0.0, 0.2, 0.1, 0.4), 0.9, 0.9)]  # 얼굴이 붙어 있어도
    sl = next(x for x in s.frame["slots"] if x["shot"] == 0)
    c = smart_cropper(app, scene.shoot).crop(sl, s.shots[0])
    assert (c.x, c.y, c.w, c.h) == home_crop(1280, 720, 160, 240) and c.reason == "as_shot"
    assert thumb_crop(app, scene.shoot, 0, s.shots[0]) == home_crop(1280, 720, 160, 240)
    assert cut_lines(app)[-1]["choice"] == "as_shot"


def test_pick_ai_keeps_ai_frame_and_faces(start):
    app, scene = start(BOTH, FakeAnalyzer())
    finish_cut(app, marked(7), CENTER_FACE)
    ai = scene.shoot.session.shots[0]
    app.step(0.1, [ENTER])  # 기본 커서는 AI 추천
    s = scene.shoot.session
    assert s.shots[0] is ai and s.shot_faces[0] == CENTER_FACE and s.cut_choices()[0] == AUTO


def test_both_options_go_through_process_cut(start, monkeypatch):
    import walnut.scenes.capture as cap
    seen = []
    real = cap.process_cut
    monkeypatch.setattr(cap, "process_cut", lambda a, raw, shoot: (seen.append(raw), real(a, raw, shoot))[1])
    app, scene = start(BOTH, FakeAnalyzer())
    base = app.frame
    chosen = marked(7)
    finish_cut(app, chosen)
    assert len(seen) == 2 and seen[0] is chosen and seen[1] is base


@pytest.mark.parametrize("env,faces", [(BURST, None), (SMART, CENTER_FACE), (BOTH, CENTER_FACE)])
def test_identical_options_skip_choice(start, env, faces):
    app, scene = start({**env, **LOG}, FakeAnalyzer())
    if faces:
        assert compute_crop(1280, 720, 160, 240, faces).reason == "home"
    finish_cut(app, None, faces)  # 셔터 프레임 그대로 + 기본 구도
    assert name(app) == "CaptureScene" and app.scene is scene
    assert cut_lines(app)[-1]["choice"] == "skipped" and cut_lines(app)[-1]["choice_ms"] == 0


def test_smart_only_no_face_still_asks(start):
    app, scene = start(SMART, FakeAnalyzer())
    finish_cut(app, None, [])  # 같은 프레임이지만 얼굴이 없어 AI 는 가장 넓게, 찍은 그대로는 기본 구도
    assert name(app) == "ChoiceScene"
    assert app.scene.data.ai_crop == cover_crop(1280, 720, 160, 240)


def test_analysis_failure_skips_choice(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer())
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    tick(app, ANALYZE_TIMEOUT + 0.2)
    assert name(app) == "CaptureScene" and app.scene is scene and len(scene.shoot.session.shots) == 1
    assert cut_lines(app)[-1]["choice"] == "skipped"
    while scene.state != "collect":
        app.step(0.1, [])
    tick(app, BURST_AFTER + 0.1)
    app.analyzer.futures[-1].set_exception(RuntimeError("모델 오류"))
    app.step(0.1, [])
    assert name(app) == "CaptureScene" and len(scene.shoot.session.shots) == 2


def test_retake_asks_again_and_replaces_choice(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer())
    s = scene.shoot.session
    for k in range(s.n):
        finish_cut(app, marked(10 + k))
        assert name(app) == "ChoiceScene" and app.scene.data.cut == k
        app.step(0.1, [LEFT, ENTER] if k in (0, 2) else [ENTER])
    assert name(app) == "ReviewScene"
    assert s.cut_choices() == [AS_SHOT, AUTO, AS_SHOT, AUTO]
    app.scene.press("retake")
    rt = app.scene
    rt.keep = [False, True, True, False]  # 0 · 3 번 다시 찍기
    rt._retake()
    finish_cut(app, marked(50))
    assert name(app) == "ChoiceScene" and app.scene.data.cut == 0
    app.step(0.1, [ENTER])  # 이번엔 AI 추천
    finish_cut(app, marked(60))
    assert name(app) == "ChoiceScene" and app.scene.data.cut == 3
    app.step(0.1, [LEFT, ENTER])
    assert name(app) == "ReviewScene"
    assert s.cut_choices() == [AUTO, AUTO, AS_SHOT, AS_SHOT]
    assert s.shots[0].size == (80, 60) and s.shots[3].size == (1280, 720)
    assert [c["choice"] for c in cut_lines(app)] == ["as_shot", "ai", "as_shot", "ai", "ai", "as_shot"]


# ---- 더 찍고 고르기 (extra 모드, Task I) ----
EXTRA = {**SETTINGS, "capture": {**SETTINGS["capture"], "extra_shots": 2}}


def shoot_extra(app, as_shot=(), faces=None, big=False) -> None:
    """extra 모드 6장을 찍으며 사진마다 고른다 (as_shot 에 든 번호는 찍은 그대로). 끝나면 고르기 화면(PickScene).
    big 이면 AI 쪽 프레임도 카메라 크기 (구도 보정이 확대할 수 있게)."""
    s = app.scene.shoot.session
    for k in range(s.total_shots()):
        finish_cut(app, np.full((720, 1280, 3), 10 + k, np.uint8) if big else marked(10 + k), faces)
        assert name(app) == "ChoiceScene" and app.scene.data.cut == k
        app.step(0.1, [LEFT, ENTER] if k in as_shot else [ENTER])
    assert name(app) == "PickScene"


def test_extra_mode_shows_choice(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer(), EXTRA)
    finish_cut(app, marked(7))
    assert name(app) == "ChoiceScene"
    ch = app.scene
    s = scene.shoot.session
    assert ch.data.cut == 0 and ch.data.ratio == s.ratio_for_shot(0)
    assert cut_lines(app) == []  # 고르기가 끝나야 cut 줄을 쓴다
    app.step(0.1, [ENTER])
    assert name(app) == "CaptureScene" and app.scene.state == COUNTDOWN


def test_extra_mode_choice_uses_representative_slot(start):
    from walnut.framing import centered_crop, home_zoom
    from walnut.scenes.capture import representative_slot
    from walnut.settings import preview_ratio

    app, scene = start(BOTH, FakeAnalyzer(), EXTRA)
    s = scene.shoot.session
    base = s.frame["slots"]
    slots = [{**base[0], "w": 240, "h": 160},             # 첫 슬롯은 가로 (대표가 아님)
             dict(base[1]), dict(base[2]),
             {**base[3], "w": 600, "h": 900}]             # 같은 2:3 이지만 커서 기본 배율이 깎인다
    s.frame = {**s.frame, "slots": slots}
    rep = representative_slot(slots)
    assert rep is slots[1] and representative_slot([dict(base[0], w=240, h=160)])["w"] == 240  # 없으면 첫 슬롯
    finish_cut(app, marked(7), [])
    ch = app.scene
    assert name(app) == "ChoiceScene" and ch.data.ratio == preview_ratio(slots)
    assert ch.data.ai_crop == cover_crop(80, 60, 160, 240)  # 얼굴이 없어 가장 넓게 — 대표 슬롯(2:3) 모양
    z = min(home_zoom(1280, 720, sl["w"], sl["h"]) for sl in slots)
    assert z < home_zoom(1280, 720, 160, 240)  # 미리보기 배율이 대표 슬롯의 기본 배율보다 작다
    want = centered_crop(1280, 720, preview_ratio(slots), z)  # 찍은 그대로 = 미리보기에서 본 화면
    assert ch.data.as_crop == want and ch.data.as_crop != home_crop(1280, 720, 160, 240)


def test_extra_mode_choice_home_crop_when_zoom_matches(start):
    app, scene = start(BOTH, FakeAnalyzer(), EXTRA)
    finish_cut(app, marked(7), [])
    assert app.scene.data.as_crop == home_crop(1280, 720, 160, 240)  # 모든 슬롯이 같으면 기본 구도 그대로


def test_extra_mode_as_shot_follows_pick_order(start):
    from walnut.scenes.capture import smart_cropper

    app, scene = start(BOTH, FakeAnalyzer(), EXTRA)
    s = scene.shoot.session
    shoot_extra(app, as_shot=(1,))
    assert s.shot_choice == [AUTO, AS_SHOT, AUTO, AUTO, AUTO, AUTO]  # 사진 번호 자리에 남는다
    for i in (1, 0, 2, 3):
        app.scene._toggle(i)
    assert s.cut_choices() == [AS_SHOT, AUTO, AUTO, AUTO]  # 고른 순서를 따라간다
    app.step(0.1, [ENTER])
    assert name(app) == "ReviewScene"
    cuts = s.cuts()
    assert cuts[0].size == (1280, 720) and cuts[1].size == (80, 60)  # 0번 컷 = 셔터 순간 프레임
    cropper = smart_cropper(app, scene.shoot)
    for sl in s.frame["slots"]:
        c = cropper.crop(sl, cuts[sl["shot"]])
        if sl["shot"] == 0:
            assert (c.x, c.y, c.w, c.h) == home_crop(1280, 720, sl["w"], sl["h"]) and c.reason == "as_shot"
        else:
            assert c.reason != "as_shot"


def test_pick_thumbnails_follow_choice(start):
    from walnut.scenes.capture import cut_thumb, smart_cropper, thumb_crop

    app, scene = start(BOTH, FakeAnalyzer(), EXTRA)
    s = scene.shoot.session
    shoot_extra(app, as_shot=(1,), faces=CENTER_FACE, big=True)
    pk = app.scene
    rep = s.frame["slots"][0]
    cropper = smart_cropper(app, scene.shoot)
    assert thumb_crop(app, scene.shoot, 1, s.shots[1]) == home_crop(1280, 720, 160, 240)  # 찍은 그대로
    ai = thumb_crop(app, scene.shoot, 0, s.shots[0])
    c = compute_crop(1280, 720, rep["w"], rep["h"], CENTER_FACE, cropper._grid(rep))
    assert ai == (c.x, c.y, c.w, c.h)  # AI 추천
    assert ai != cover_crop(1280, 720, 160, 240)  # 예전처럼 1.0배가 아니다
    b, bb = app.stage.tokens["print"]["border"], app.stage.tokens["print"]["border_bottom"]
    box = (pk.lay.paper[0] - 2 * b, pk.lay.paper[1] - b - bb)
    for i in (0, 1):
        want = cut_thumb(s.shots[i], s.ratio_for_shot(i), box, thumb_crop(app, scene.shoot, i, s.shots[i]))
        assert pygame.image.tobytes(pk.thumbs[i], "RGB") == pygame.image.tobytes(want, "RGB")


def test_extra_mode_flags_off_unchanged(start):
    from walnut.scenes.capture import cut_thumb, thumb_crop

    app, scene = start({}, None, EXTRA)
    seen = []
    for _ in range(600):
        app.step(0.1, [])
        seen.append(name(app))
        if name(app) == "PickScene":
            break
    assert "ChoiceScene" not in seen and seen[-1] == "PickScene"
    s = scene.shoot.session
    pk = app.scene
    assert all(thumb_crop(app, scene.shoot, i, im) is None for i, im in enumerate(s.shots))
    b, bb = app.stage.tokens["print"]["border"], app.stage.tokens["print"]["border_bottom"]
    box = (pk.lay.paper[0] - 2 * b, pk.lay.paper[1] - b - bb)
    want = cut_thumb(s.shots[0], s.ratio_for_shot(0), box)
    assert pygame.image.tobytes(pk.thumbs[0], "RGB") == pygame.image.tobytes(want, "RGB")
    for i in (3, 0, 1, 2):
        pk._toggle(i)
    app.step(0.1, [ENTER])
    assert name(app) == "ReviewScene" and s.cut_choices() == [AUTO] * 4
    plain = compose(scene.shoot.frame_png, s.frame["slots"], s.cuts())
    assert app.scene.collage.tobytes() == plain.tobytes()


def test_extra_mode_choice_recorded(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer(), EXTRA)
    shoot_extra(app, as_shot=(0, 4))
    lines = cut_lines(app)
    assert [c["choice"] for c in lines] == ["as_shot", "ai", "ai", "ai", "as_shot", "ai"]  # skipped 가 아니다
    assert [c["cut"] for c in lines] == list(range(6)) and all(isinstance(c["choice_ms"], int) for c in lines)


def test_choice_recorded_in_cut_line(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer())
    finish_cut(app, marked(7))
    assert cut_lines(app) == []  # 고르기가 끝나야 cut 줄을 쓴다
    tick(app, 1.0)
    app.step(0.1, [LEFT, ENTER])
    rec = cut_lines(app)[-1]
    assert rec["choice"] == "as_shot" and isinstance(rec["choice_ms"], int) and 900 <= rec["choice_ms"] <= 1300
    assert rec["cut"] == 0 and rec["reason"] == "best"


def test_leaving_choice_still_writes_cut_line(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer())
    finish_cut(app, marked(7))
    app.step(0.1, [F5])
    assert name(app) == "IdleScene"
    assert cut_lines(app)[-1]["choice"] == "skipped"
    tick(app, CHOICE_SEC + 1)  # 떠난 고르기 화면이 촬영을 되살리지 않는다
    assert name(app) == "IdleScene"


def test_f2_takes_ai(start):
    app, scene = start({**BOTH, **LOG}, FakeAnalyzer())
    finish_cut(app, marked(7))
    app.step(0.1, [F2])
    assert name(app) == "CaptureScene" and scene.shoot.session.cut_choices()[0] == AUTO
    assert cut_lines(app)[-1]["choice"] == "timeout_ai"


def test_dev_all_shows_analysis_then_choice(start):
    app, scene = start(BOTH, FakeAnalyzer())
    app.cfg = dataclasses.replace(app.cfg, dev="all")
    finish_cut(app, marked(7))
    assert name(app) == "BurstShowScene"
    app.step(0.1, [ENTER])
    assert name(app) == "ChoiceScene" and app.scene.data.cut == 0
    app.step(0.1, [ENTER])
    assert name(app) == "CaptureScene"


def test_camera_lost_after_choice_goes_to_camera_state(start):
    app, scene = start(BOTH, FakeAnalyzer())
    finish_cut(app, marked(7))
    app.camera.fail = True
    app.step(0.1, [ENTER])
    from walnut.scenes.capture import CAMERA
    assert name(app) == "CaptureScene" and app.scene.state == CAMERA


# ---- 조작 ----
def test_touch_and_keys_select(start):
    app, scene = start(BOTH, FakeAnalyzer())
    finish_cut(app, marked(7))
    ch = app.scene
    app.step(0.1, [LEFT])
    assert ch.sel == 0
    app.step(0.1, [RIGHT])
    assert ch.sel == 1
    app.step(0.1, [key(pygame.K_UP)])  # 위 · 아래도 옮긴다 (세로 배치에서 두 장이 위아래일 때)
    assert ch.sel == 0
    app.step(0.1, [])  # 그려야 탭 영역이 생긴다
    ch.hits.tap(ch.lay.cards[1].center)  # AI 추천 사진을 누름 → 바로 확정
    assert name(app) == "CaptureScene" and scene.shoot.session.cut_choices()[0] == AUTO
    finish_cut(app, marked(8))
    ch = app.scene
    app.step(0.1, [])
    ch.hits.tap(ch.lay.labels[0].center)  # 이름표를 눌러도 같다
    assert scene.shoot.session.cut_choices()[1] == AS_SHOT


# ---- 배치 ----
@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920), (1280, 720), (768, 1024), (2560, 1080)])
@pytest.mark.parametrize("ratio", [2 / 3, 3 / 4, 1.0, 16 / 9, 4 / 1])
def test_portrait_layout_fits(make_app, size, ratio):
    app = make_app({}, display_size=size)
    st = app.stage
    lay = choice_layout(st, ratio)
    view = st.rect()
    for card, label in zip(lay.cards, lay.labels):
        assert view.contains(card) and view.contains(label)
        assert not card.colliderect(label)
    assert not lay.cards[0].colliderect(lay.cards[1]) and not lay.labels[0].colliderect(lay.labels[1])
    assert lay.cards[0].w >= 120 and lay.cards[0].h >= 80  # 사진이 너무 작아지지 않는다
    assert lay.title[1] < min(c.top for c in lay.cards) and lay.hint[1] > max(lb.bottom for lb in lay.labels)
    assert lay.hint[1] < st.h
    pair = lay.cards[0].union(lay.cards[1])
    assert abs(pair.centerx - st.w // 2) <= 2  # 두 장을 한 덩어리로 가운데에
    gap = max(lay.cards[1].left - lay.cards[0].right, lay.cards[1].top - lay.labels[0].bottom)
    assert 0 < gap <= st.tokens["space"]["step"][5]  # 너무 벌어지지 않는다
    if st.orientation == "portrait":  # 제목 바로 아래부터
        assert pair.top - lay.title[1] <= 200


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920)])
def test_draw_never_raises(start, size):
    app, scene = start({**BOTH, "BOOTH_MOTION": "true"}, FakeAnalyzer())
    finish_cut(app, marked(7))
    ch = app.scene
    for kind in ("key", "touch"):
        app.input_kind = kind
        surf = pygame.Surface((app.stage.w, app.stage.h))
        ch.draw(surf)


def test_layout_pick_stacks_wide_photos_in_portrait(make_app):
    app = make_app({}, display_size=(1080, 1920))
    tall = choice_layout(app.stage, 2 / 3)
    wide = choice_layout(app.stage, 16 / 9)
    assert tall.cards[0].centery == tall.cards[1].centery  # 세로 사진은 나란히
    assert wide.cards[0].centerx == wide.cards[1].centerx  # 가로 사진은 위아래가 더 크다


# ---- 세션 ----
def _session(n=2, extra=0):
    slots = [{"id": k + 1, "shot": k, "cx": 100, "cy": 100 + 200 * k, "w": 150, "h": 200, "rot": 0} for k in range(n)]
    cap = {"extra_shots": extra, "allow_retake": True, "review_auto_sec": 25, "countdown_sec": 3, "between_sec": 1}
    return ShootSession({"slots": slots}, cap)


def test_session_choice_follows_retake_and_pick_order():
    s = _session()
    assert s.add_shot(Image.new("RGB", (4, 4)), ["a"]) == 0
    assert s.add_shot(Image.new("RGB", (4, 4)), ["b"]) == 1
    s.use_as_shot(1, Image.new("RGB", (8, 8)))
    assert s.cut_choices() == [AUTO, AS_SHOT] and s.shot_faces == [["a"], None]
    s.begin_retake([True, False])
    assert s.add_shot(Image.new("RGB", (4, 4)), ["c"]) == 1
    assert s.cut_choices() == [AUTO, AUTO]  # 다시 찍으면 다시 AI 추천부터
    e = _session(n=2, extra=1)
    for k in range(3):
        e.add_shot(Image.new("RGB", (4, 4)))
    e.use_as_shot(2, Image.new("RGB", (4, 4)))
    e.toggle_pick(2)
    e.toggle_pick(0)
    assert e.cut_choices() == [AS_SHOT, AUTO]  # 고른 순서대로
    raw = _session()
    raw.shots = [Image.new("RGB", (4, 4))] * 2  # 직접 넣어 선택 정보가 모자라도
    assert raw.cut_choices() == [AUTO, AUTO]


# ---- 현장 기록 분석 ----
def test_analyze_field_log_reports_ai_adoption(tmp_path):
    from tools.analyze_field_log import format_report, summarize

    def cut(choice, ms=0):
        return {"type": "cut", "shoot_id": "s1", "reason": "best", "choice": choice, "choice_ms": ms}

    recs = [cut("ai", 1200), cut("ai", 800), cut("as_shot", 2000), cut("timeout_ai", 5000), cut("skipped"),
            {"type": "cut", "shoot_id": "s0", "reason": "best"}]  # 예전 줄 (choice 없음)
    s = summarize(recs)
    ch = s["choice"]
    assert ch["counts"] == {"ai": 2, "as_shot": 1, "timeout_ai": 1, "skipped": 1}
    assert ch["asked"] == 4 and ch["ai_rate"] == pytest.approx(3 / 4)
    assert ch["picked"] == 3 and ch["picked_ai_rate"] == pytest.approx(2 / 3)
    assert ch["picked_ms"]["mean"] == pytest.approx((1200 + 800 + 2000) / 3)
    text = format_report({**s, "broken": 0})
    assert "AI 채택률" in text and "75.0%" in text and "66.7%" in text
    empty = format_report({**summarize([{"type": "cut", "reason": "best"}]), "broken": 0})
    assert "AI 채택률" not in empty  # 고르기가 없던 기록은 표를 늘리지 않는다
