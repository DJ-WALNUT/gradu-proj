"""베스트 컷 분석 화면 (--dev-mode-all) — 후보 · 탈락 사유 · 고른 이유를 보여 주고 다음 컷으로 넘긴다."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pygame
import pytest

from test_capture_burst import (BURST, FakeAnalyzer, _restore_sfx, make_result, marked, start, tick,  # noqa: F401
                                to_shutter)
from walnut.burst import TimedFrame
from walnut.scenes.burst_show import (AUTO_SEC, REJECT_LABEL, BurstShowScene, ShowData, reason_text,
                                      shutter_index)
from walnut.scenes.capture import ANALYZE_TIMEOUT, BURST_AFTER, COUNTDOWN


def key(k: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode="", mod=0, scancode=0)


ENTER, SPACE, F2, F5 = (key(k) for k in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_F2, pygame.K_F5))


def name(app) -> str:
    return type(app.scene).__name__


def info(reason="best", index=1, scores=(0.6, 0.9, None), rejects=(None, None, "eye"), ts=(9.5, 9.84, 10.0)):
    return {"reason": reason, "index": index, "scores": list(scores), "rejects": list(rejects), "fallback_used": False,
            "candidates": [{"t": t, "sharpness": 100.0, "faces": 1, "eye": 0.9, "frontality": 0.8} for t in ts]}


# ---- 순수 함수 ----

def test_shutter_index():
    assert shutter_index([9.5, 9.84, 10.0, 10.2], 10.0) == 2
    assert shutter_index([9.9, 10.1], 10.0) == 0  # 같으면 이른 쪽
    assert shutter_index([], 10.0) == -1


def test_reject_labels():
    assert REJECT_LABEL == {"blur": "흔들림", "eye": "눈 감음", "faces": "얼굴 수 부족"}


def test_reason_texts():
    assert reason_text(None, "timeout", -1) == "분석을 끝내지 못해 카운트다운 순간의 컷을 그대로 썼어요"
    assert reason_text(info(), "error", 2) == "분석을 끝내지 못해 카운트다운 순간의 컷을 그대로 썼어요"
    assert reason_text(info(reason="single"), "single", 0) == "후보가 한 장뿐이라 그대로 썼어요"
    assert reason_text(info(reason="no_face"), "no_face", 2) == "얼굴을 찾지 못해 가장 선명한 컷을 골랐어요"
    assert reason_text(info(reason="all_rejected", rejects=("blur",) * 3), "all_rejected", 2) == "모든 후보가 탈락해 셔터에 가장 가까운 컷을 썼어요"
    assert reason_text(info(index=2, scores=(0.6, 0.7, 0.9), rejects=(None,) * 3), "best", 2) == "카운트다운 순간의 컷이 가장 좋았어요"
    assert reason_text(info(), "best", 2) == "카운트다운 순간은 눈 감음으로 탈락 → -0.16초 컷이 가장 좋아요"
    assert reason_text(info(scores=(0.6, 0.9, 0.7), rejects=(None,) * 3), "best", 2) == "-0.16초 컷의 점수가 더 높아요 (0.90 > 0.70)"


def test_reason_text_all_eye_rejected_says_widest_eyes():
    eyes = info(reason="all_rejected", scores=(None,) * 3, rejects=("eye", "faces", "eye"))
    assert reason_text(eyes, "all_rejected", 2) == "모든 후보가 눈 감음으로 탈락해 눈을 가장 크게 뜬 컷을 골랐어요"
    blur = info(reason="all_rejected", scores=(None,) * 3, rejects=("blur", "blur", "faces"))
    assert reason_text(blur, "all_rejected", 2) == "모든 후보가 탈락해 셔터에 가장 가까운 컷을 썼어요"


def test_reason_text_survives_info_without_rejects():
    old = info(scores=(0.6, 0.9, 0.7))
    del old["rejects"]
    assert reason_text(old, "best", 2) == "-0.16초 컷의 점수가 더 높아요 (0.90 > 0.70)"


# ---- 장면 ----

def show_data(n: int = 3, reason: str = "best") -> ShowData:
    frames = [TimedFrame(10.0 - 0.1 * (n - 1 - i), np.full((60, 80, 3), 40 * i % 255, np.uint8)) for i in range(n)]
    data_info = None
    if reason not in ("timeout", "error", "no_candidates") and n:
        rejects = ["eye" if i == n - 1 and n > 1 else None for i in range(n)]
        scores = [None if r else 0.5 + 0.01 * i for i, r in enumerate(rejects)]
        data_info = {"reason": reason, "index": max(0, n - 2), "scores": scores, "rejects": rejects,
                     "fallback_used": False,
                     "candidates": [{"t": f.t, "sharpness": 100.0 + i, "faces": 1, "eye": 0.9, "frontality": None}
                                    for i, f in enumerate(frames)]}
    return ShowData(frames=frames, shutter_t=10.0, info=data_info, reason=reason, ratio=3 / 4, mirror=True, cut=0)


@pytest.fixture
def shown(make_app):
    """shown(env, n, reason, display_size) → (app, scene, done 호출 목록)."""
    def _make(env=None, n=3, reason="best", display_size=(1920, 1080)):
        app = make_app(env, display_size=display_size)
        app.start_local()
        done: list[int] = []
        scene = BurstShowScene(app, show_data(n, reason), on_done=lambda: done.append(1))
        app.go(scene)
        return app, scene, done

    return _make


def test_enter_calls_on_done_once(shown):
    app, scene, done = shown()
    app.step(0.1, [ENTER, ENTER])
    app.step(0.1, [SPACE])
    assert done == [1]


def test_f2_and_tap_advance(shown):
    app, scene, done = shown()
    app.step(0.1, [F2])
    assert done == [1]
    app, scene, done = shown()
    app.step(0.1, [])  # 그려야 탭 영역이 생긴다
    scene.hits.tap((app.stage.w // 2, app.stage.h // 2))
    assert done == [1]


def test_auto_advance_after_20s(shown):
    app, scene, done = shown()
    assert AUTO_SEC == 20.0
    for _ in range(199):
        app.step(0.1, [])
    assert done == []
    for _ in range(3):
        app.step(0.1, [])
    assert done == [1]


def test_phases_with_motion(shown):
    app, scene, done = shown({"BOOTH_MOTION": "true"})
    seen = []
    for _ in range(15):
        app.step(0.1, [])
        seen.append(scene.phase())
    assert seen[2] == "appear" and seen[7] == "dim" and seen[-1] == "best"


def test_no_motion_shows_result_at_once(shown):
    app, scene, done = shown({"BOOTH_MOTION": "false"})
    assert scene.phase() == "best"


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920), (1280, 720)])
@pytest.mark.parametrize("n,reason", [(0, "timeout"), (0, "no_candidates"), (1, "single"), (3, "best"), (3, "timeout"),
                                      (13, "best"), (4, "all_rejected"), (2, "no_face")])
def test_draw_never_raises(shown, size, n, reason):
    app, scene, done = shown({"BOOTH_MOTION": "true"}, n=n, reason=reason, display_size=size)
    errors = []
    app._safe = lambda fn: _call(fn, errors)  # 장면 오류를 삼키지 않고 모은다
    for _ in range(20):
        app.step(0.1, [])
    assert errors == [] and app.scene is scene


def _call(fn, errors):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        errors.append(repr(exc))


def test_reason_line_is_drawn(shown, monkeypatch):
    from walnut import ui

    texts: list[str] = []
    orig = ui.text
    monkeypatch.setattr(ui, "text", lambda surf, s, *a, **k: (texts.append(s), orig(surf, s, *a, **k))[1])
    app, scene, done = shown({"BOOTH_MOTION": "false"}, n=3, reason="best")
    app.step(0.1, [])
    assert scene.reason in texts and "탈락" in scene.reason
    assert "눈 감음 0.90" in texts and "카운트다운 순간" in texts and "베스트 컷" in texts


# ---- 촬영 장면 연결 ----

def set_dev(app, mode: str) -> None:
    app.cfg = dataclasses.replace(app.cfg, dev=mode)


def take_cut(app, value: int | None = None) -> None:
    """지금 촬영 장면에서 한 컷: 카운트다운 → 수집 → 분석 끝.

    value 가 없으면 셔터 프레임 그대로를 고른 결과 — 버스트만 켜져 있으면 '찍은 그대로' 와 같아 고르기 화면이 없다."""
    scene = app.scene
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    app.analyzer.futures[-1].set_result(make_result(app.frame if value is None else marked(value)))
    app.step(0.1, [])


def test_show_scene_after_each_cut(start):
    app, scene = start(BURST, FakeAnalyzer())
    set_dev(app, "all")
    take_cut(app)
    assert name(app) == "BurstShowScene" and len(scene.shoot.session.shots) == 1
    assert app.scene.data.cut == 0 and app.scene.data.info is not None and len(app.scene.data.frames) >= 1
    app.step(0.1, [ENTER])
    assert name(app) == "CaptureScene" and app.scene is not scene and app.scene.state == COUNTDOWN
    assert len(app.scene.shoot.session.shots) == 1


def test_show_scene_then_review_after_last_cut(start):
    app, scene = start(BURST, FakeAnalyzer())
    set_dev(app, "all")
    for i in range(4):
        take_cut(app)
        assert name(app) == "BurstShowScene" and app.scene.data.cut == i
        app.step(0.1, [ENTER])
    assert name(app) == "ReviewScene"


def test_show_scene_on_timeout_explains_fallback(start):
    app, scene = start(BURST, FakeAnalyzer())
    set_dev(app, "all")
    to_shutter(app, scene)
    tick(app, BURST_AFTER + ANALYZE_TIMEOUT + 0.3)
    assert name(app) == "BurstShowScene" and app.scene.data.info is None and app.scene.data.reason == "timeout"
    assert len(scene.shoot.session.shots) == 1


def test_f5_from_show_scene_goes_home(start):
    app, scene = start(BURST, FakeAnalyzer())
    set_dev(app, "all")
    take_cut(app)
    app.step(0.1, [F5])
    assert name(app) == "IdleScene"
    app.step(21.0, [])  # 떠난 분석 화면의 자동 넘김이 촬영을 되살리지 않는다
    assert name(app) == "IdleScene"


def test_dev_on_never_shows(start):
    app, scene = start(BURST, FakeAnalyzer())
    set_dev(app, "on")
    take_cut(app)
    assert name(app) == "CaptureScene" and app.scene is scene and len(scene.shoot.session.shots) == 1


def test_capture_log_unchanged_in_dev_all(start, tmp_path):
    app, scene = start({**BURST, "BOOTH_CAPTURE_LOG": "1"}, FakeAnalyzer())
    set_dev(app, "all")
    take_cut(app)
    lines = (tmp_path / "data" / "logs" / "capture_metrics.jsonl").read_text(encoding="utf-8").splitlines()
    cut = [json.loads(x) for x in lines if json.loads(x).get("type") == "cut"][-1]
    assert set(cut) == {"type", "shoot_id", "at", "collect_ms", "analyze_ms", "total_ms", "candidates", "reason",
                        "fallback_used", "cut", "preview_fps", "index", "cands", "faces", "faces_from", "unstable_faces", "faces_unstable",
                        "detect_mode", "choice", "choice_ms", "person_heads", "person_ms", "refined", "refine_ms"}


def test_reason_time_matches_the_strip_labels():
    """이유 문장의 시간은 후보 줄 아래 숫자(실제 셔터 시각 기준)와 같아야 한다."""
    late = info(ts=(9.5, 9.78, 9.96))  # 셔터 컷이 셔터 시각보다 0.04초 이르다
    assert reason_text(late, "best", 2, shutter_t=10.0) == "카운트다운 순간은 눈 감음으로 탈락 → -0.22초 컷이 가장 좋아요"


def test_reject_note_carries_the_value_that_failed():
    from walnut.scenes.burst_show import reject_note

    cand = {"t": 0.0, "sharpness": 12.0, "faces": 1, "eye": 0.52, "frontality": 0.9}
    assert reject_note("eye", cand) == "눈 감음 0.52"
    assert reject_note("faces", cand) == "얼굴 1명"
    assert reject_note("blur", cand) == "흔들림"
    assert reject_note("eye", None) == "눈 감음" and reject_note("eye", {**cand, "eye": None}) == "눈 감음"


# ---- 사람 찾기 표시 (Task H) ----

def test_person_note():
    from walnut.scenes.burst_show import person_note
    assert person_note({"person_heads": 2}) == "사람 위치로 구도를 잡았어요 (머리 2)"
    assert person_note({"person_heads": 0}) is None
    assert person_note({}) is None and person_note(None) is None


def test_person_note_is_drawn_in_hint_line(make_app, monkeypatch):
    from walnut import ui

    texts: list[str] = []
    orig = ui.text
    monkeypatch.setattr(ui, "text", lambda surf, s, *a, **k: (texts.append(s), orig(surf, s, *a, **k))[1])
    app = make_app({"BOOTH_MOTION": "false"})
    app.start_local()
    data = show_data(3, "no_face")
    data.info["person_heads"] = 2
    app.go(BurstShowScene(app, data, on_done=lambda: None))
    app.step(0.1, [])
    assert any(t.startswith("사람 위치로 구도를 잡았어요 (머리 2)  ·  Enter 다음 컷") for t in texts)
