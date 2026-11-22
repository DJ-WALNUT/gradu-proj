"""촬영 장면 ↔ 베스트 컷 분석기 연결 시험.

가짜 분석기를 끼워, Future 가 언제 끝나는지는 시험이 정한다. 모델은 불러오지 않는다.
"""

from __future__ import annotations

import json
from concurrent.futures import Future

import numpy as np
import pygame
import pytest

from walnut.analysis import BurstResult
from walnut.burst import TimedFrame
from walnut.device import Device, DeviceStore
from walnut.bundle import BundleStore
from walnut.scenes.capture import ANALYZE, ANALYZE_TIMEOUT, BURST_AFTER, CAMERA, COLLECT, COUNTDOWN, CaptureScene
from walnut.scenes.idle import IdleScene

KEY = b"k" * 32
SETTINGS = {"capture": {"countdown_sec": 3, "between_sec": 1}, "filters": {"enabled": ["original"]}}


class FakeAnalyzer:
    """submit 이 Future 를 돌려주되 끝내는 시점은 시험이 정한다."""

    def __init__(self, available: bool = True):
        self.available = available
        self.calls: list[tuple[list[TimedFrame], float, bool]] = []
        self.futures: list[Future] = []
        self.closed = False
        self.raise_on_submit: Exception | None = None

    def submit(self, frames, shutter_t, mirror):
        if self.raise_on_submit is not None:
            raise self.raise_on_submit
        self.calls.append((list(frames), shutter_t, mirror))
        fut: Future = Future()
        self.futures.append(fut)
        return fut

    def warm(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def make_result(raw: np.ndarray, reason: str = "best", fallback: bool = False, n: int = 3) -> BurstResult:
    info = {"reason": reason, "fallback_used": fallback, "scores": [None] * n, "index": 0,
            "candidates": [{"t": 0.0, "sharpness": 1.0, "faces": 0, "eye": None, "frontality": None}] * n,
            "timings": {"total": 1.0}, "faces_from": None, "unstable_faces": 0,
            "faces_unstable": [], "person_heads": 0, "person_ms": None}
    return BurstResult(raw, [], info)


def marked(value: int) -> np.ndarray:
    """어느 프레임인지 알아볼 수 있는 작은 프레임."""
    return np.full((60, 80, 3), value, np.uint8)


@pytest.fixture
def start(make_app, make_bundle, tmp_path, fake_server):
    """start(env) → 촬영 장면에 들어선 (app, scene). 분석기는 FakeAnalyzer."""
    fake_server.route("POST", "/api/booth/photos", lambda r: (503, {"Retry-After": "30"}, {"error": "retry_later"}))
    played: list[str] = []

    def _start(env: dict | None = None, analyzer: FakeAnalyzer | None = None, settings: dict | None = None):
        DeviceStore(tmp_path / "data" / "device.json").save(Device(fake_server.url, "tok", KEY, 1, "테스트 행사"))
        raw, assets = make_bundle(version=1, settings_patch=settings or SETTINGS)
        store = BundleStore(tmp_path / "data")
        store.stage(raw, assets.__getitem__)
        store.activate(1)
        app = make_app(env)
        app.step(1 / 60, [])
        assert isinstance(app.scene, IdleScene)
        if analyzer is not None:  # 플래그와 상관없이 그대로 끼운다 (꺼진 경우 가드가 막는지 보려고)
            if app.analyzer is not None:
                app.analyzer.close()
            app.analyzer = analyzer
        app.start_shoot()
        assert isinstance(app.scene, CaptureScene)
        import walnut.scenes.capture as cap
        cap.sfx.play = lambda name, *a, **k: played.append(name)  # 소리 호출만 센다
        app.played = played
        return app, app.scene

    return _start


@pytest.fixture(autouse=True)
def _restore_sfx():
    import walnut.sfx as sfx
    orig = sfx.play
    yield
    sfx.play = orig


BURST = {"BOOTH_BURST": "1"}
SMART = {"BOOTH_SMART_CROP": "1"}


def tick(app, secs: float, dt: float = 0.1) -> None:
    for _ in range(int(round(secs / dt))):
        app.step(dt, [])


def to_shutter(app, scene) -> None:
    """카운트다운을 끝내 셔터 직후 상태로 만든다."""
    while scene.state == COUNTDOWN:
        app.step(0.1, [])


def shots(scene) -> int:
    return len(scene.shoot.session.shots)


def test_flags_off_path_never_touches_analyzer(start):
    fake = FakeAnalyzer()
    app, scene = start({}, fake)  # 플래그가 꺼진 앱에 분석기를 억지로 끼워도 쓰지 않아야 한다
    assert app.analyzer is fake
    states = set()
    for _ in range(80):
        app.step(0.1, [])
        states.add(scene.state)
    assert COLLECT not in states and ANALYZE not in states
    assert shots(scene) >= 1
    assert fake.calls == []


def test_no_analyzer_without_flags(make_app):
    assert make_app({}).analyzer is None


@pytest.mark.parametrize("env", [BURST, SMART])
def test_analyzer_is_created_warmed_and_closed(make_app, monkeypatch, env):
    from walnut.analysis import BurstAnalyzer
    events: list[str] = []
    orig_close = BurstAnalyzer.close
    monkeypatch.setattr(BurstAnalyzer, "warm", lambda self: events.append("warm"))
    monkeypatch.setattr(BurstAnalyzer, "close", lambda self: (events.append("close"), orig_close(self))[1])
    app = make_app(env)
    assert isinstance(app.analyzer, BurstAnalyzer)
    assert app.analyzer.model_path == app.cfg.models_dir / "face_landmarker.task"
    assert events == ["warm"]
    app.shutdown()
    assert events == ["warm", "close"]


def test_shot_count_is_one_per_shutter(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    to_shutter(app, scene)
    assert scene.state == COLLECT and shots(scene) == 0
    tick(app, BURST_AFTER + 0.1)
    assert scene.state == ANALYZE and len(an.calls) == 1
    an.futures[0].set_result(make_result(app.frame))
    app.step(0.1, [])
    assert shots(scene) == 1
    assert len(an.calls) == 1


def test_selected_frame_goes_through_process_cut(start, monkeypatch):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    seen = []
    import walnut.scenes.capture as cap
    real = cap.process_cut
    monkeypatch.setattr(cap, "process_cut", lambda a, raw, shoot: (seen.append(raw), real(a, raw, shoot))[1])
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    chosen = marked(200)
    faces = [object()]
    res = make_result(chosen)
    res.faces = faces
    an.futures[0].set_result(res)
    app.step(0.1, [])
    # 고른 컷이 먼저, 그다음 '찍은 그대로' 고르기용 셔터 프레임 (Task G)
    assert seen[0] is chosen and len(seen) == 2 and seen[1] is not chosen
    s = scene.shoot.session
    assert s.shot_faces == [faces]
    assert s.shots[0].size == (80, 60)


@pytest.mark.parametrize("mirror", [True, False])
def test_candidates_come_from_the_window_around_shutter(start, mirror):
    an = FakeAnalyzer()
    app, scene = start(BURST, an, {**SETTINGS, "capture": {**SETTINGS["capture"], "mirror": mirror}})
    assert scene.shoot.mirror is mirror
    asked = []
    orig = app.camera.frames_between
    app.camera.frames_between = lambda t0, t1: (asked.append((t0, t1)), orig(t0, t1))[1]
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    (t0, t1), = asked
    t = an.calls[0][1]
    assert t0 == pytest.approx(t - 0.7) and t1 == pytest.approx(t + 0.3)
    assert an.calls[0][2] is scene.shoot.mirror


def test_no_candidates_uses_base_frame(start):
    an = FakeAnalyzer()
    app, scene = start({**BURST, "BOOTH_CAPTURE_LOG": "1"}, an)
    app.camera.frames_between = lambda t0, t1: []
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    assert an.calls == []  # 맡길 후보가 없다
    s = scene.shoot.session
    assert len(s.shots) == 1 and s.shot_faces == [None]
    rec = read_records(app)[-1]
    assert rec["reason"] == "no_candidates" and rec["fallback_used"] is True and rec["candidates"] == 0
    assert scene.state != CAMERA  # 카메라는 살아 있으니 기존 흐름대로 간다


def test_camera_lost_during_collect_goes_to_existing_camera_state(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    to_shutter(app, scene)
    app.camera.fail = True  # 수집 중 케이블 빠짐
    tick(app, BURST_AFTER + 0.1)
    # 후보가 없어 기준 프레임으로 컷이 끝나고, 프레임이 없으니 바로 '카메라 연결 중'
    assert shots(scene) == 1 and scene.state == CAMERA
    app.camera.fail = False
    app.step(0.1, [])
    assert scene.state == COUNTDOWN


def test_camera_lost_but_ring_has_frames_still_analyzes(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    to_shutter(app, scene)
    app.camera.fail = True
    app.camera.frames_between = lambda t0, t1: [TimedFrame(t0, marked(9))]  # 링에 남은 프레임
    tick(app, BURST_AFTER + 0.1)
    assert scene.state == ANALYZE and len(an.calls) == 1
    an.futures[0].set_result(make_result(marked(9)))
    app.step(0.1, [])
    assert shots(scene) == 1
    assert type(app.scene).__name__ == "ChoiceScene"  # 셔터 프레임과 달라 고르기를 거친다 (Task G)
    app.step(0.1, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0, scancode=0)])
    assert app.scene.state == CAMERA


def test_timeout_uses_base_frame(start):
    an = FakeAnalyzer()
    app, scene = start({**BURST, "BOOTH_CAPTURE_LOG": "1"}, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    assert scene.state == ANALYZE
    tick(app, ANALYZE_TIMEOUT + 0.2)
    s = scene.shoot.session
    assert len(s.shots) == 1 and s.shot_faces == [None]
    assert an.futures[0].cancelled()
    rec = read_records(app)[-1]
    assert rec["reason"] == "timeout" and rec["fallback_used"] is True
    assert rec["candidates"] == 1  # 맡긴 후보 수 (FakeCamera 는 한 장을 돌려준다)


def test_timeout_counts_real_time_when_frames_are_slow(start):
    # 앱의 dt 는 0.05초로 잘린다 — 화면이 느려 dt 누적이 2초에 못 미쳐도 실제로 2초가 지났으면 기준 프레임으로 간다
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    assert scene.state == ANALYZE
    scene._t_submit -= ANALYZE_TIMEOUT + 0.1          # 맡긴 지 실제로 2초 넘게 지난 것처럼
    app.step(0.05, [])
    assert an.futures[0].cancelled()
    assert scene.shoot.session.shot_faces == [None]


def test_analyzer_exception_uses_base_frame(start, caplog):
    an = FakeAnalyzer()
    app, scene = start({**BURST, "BOOTH_CAPTURE_LOG": "1"}, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    an.futures[0].set_exception(RuntimeError("모델 오류"))
    with caplog.at_level("WARNING"):
        app.step(0.1, [])
    assert shots(scene) == 1 and scene.shoot.session.shot_faces == [None]
    rec = read_records(app)[-1]
    assert rec["reason"] == "error" and rec["candidates"] == 1
    assert "분석 오류" in caplog.text


def test_malformed_result_uses_base_frame(start, caplog):
    an = FakeAnalyzer()
    app, scene = start({**BURST, "BOOTH_CAPTURE_LOG": "1"}, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    bad = make_result(marked(5))
    bad.info = {}  # reason · candidates 가 없다
    an.futures[0].set_result(bad)
    with caplog.at_level("WARNING"):
        app.step(0.1, [])
    assert shots(scene) == 1 and scene.shoot.session.shot_faces == [None]
    assert read_records(app)[-1]["reason"] == "error"


def test_whole_shoot_one_shot_per_shutter(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    total = scene.shoot.session.total_shots()
    for k in range(total):
        while scene.state != COLLECT:
            app.step(0.1, [])
        assert shots(scene) == k
        tick(app, BURST_AFTER + 0.1)
        assert scene.state == ANALYZE and len(an.calls) == k + 1
        an.futures[k].set_result(make_result(app.frame))
        app.step(0.1, [])
        if k < total - 1:
            assert shots(scene) == k + 1
    assert app.scene is not scene and not isinstance(app.scene, CaptureScene)
    assert len(scene.shoot.session.shots) == total and len(scene.shoot.session.shot_faces) == total
    assert len(an.calls) == total


def test_submit_failure_uses_base_frame(start):
    an = FakeAnalyzer()
    an.raise_on_submit = RuntimeError("닫힘")
    app, scene = start(BURST, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    assert shots(scene) == 1


def test_late_result_is_ignored_after_timeout(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    first = an.futures[0]
    first.set_running_or_notify_cancel()  # 이미 돌고 있는 분석은 취소되지 않고 나중에 끝난다
    tick(app, ANALYZE_TIMEOUT + 0.2)
    assert shots(scene) == 1
    # 다음 컷 — 첫 Future 가 뒤늦게 끝나도 둘째 컷에 붙지 않는다
    while scene.state != COLLECT:
        app.step(0.1, [])
    tick(app, BURST_AFTER + 0.1)
    assert scene.state == ANALYZE and len(an.futures) == 2
    first.set_result(make_result(marked(1)))  # 늦게 끝난 결과
    app.step(0.1, [])
    assert shots(scene) == 1 and scene.state == ANALYZE
    an.futures[1].set_result(make_result(marked(2)))
    app.step(0.1, [])
    assert shots(scene) == 2


def test_late_result_is_ignored_after_home(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    fut = an.futures[0]
    app.home()
    assert not isinstance(app.scene, CaptureScene)
    assert fut.cancelled()
    session = scene.shoot.session
    scene.update(0.1)  # 옛 장면이 혹시 더 갱신돼도 세션을 건드리지 않는다
    assert session.shots == [] and scene._future is None


def test_f2_during_collect_does_not_take_twice(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    to_shutter(app, scene)
    assert scene.state == COLLECT
    scene.skip()
    assert scene.state == COLLECT
    tick(app, BURST_AFTER + 0.1)
    scene.skip()
    assert scene.state == ANALYZE and len(an.calls) == 1
    an.futures[0].set_result(make_result(app.frame))
    app.step(0.1, [])
    assert shots(scene) == 1


def test_remote_line_format_unchanged_during_collect(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    before = scene.remote_state()
    assert before.split("|")[0] == "C" and len(before.split("|")) == 5
    to_shutter(app, scene)
    assert scene.state == COLLECT
    line = scene.remote_state()
    assert line == "C|0|4|0|30"
    tick(app, BURST_AFTER + 0.1)
    assert scene.state == ANALYZE and scene.remote_state() == "C|0|4|0|30"


def test_shutter_sound_once(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    an.futures[0].set_result(make_result(app.frame))
    app.step(0.1, [])
    assert app.played.count("shutter") == 1


def test_analyzer_unavailable_behaves_like_flags_off(start):
    an = FakeAnalyzer(available=False)
    app, scene = start(BURST, an)
    states = set()
    for _ in range(40):
        app.step(0.1, [])
        states.add(scene.state)
    assert COLLECT not in states and ANALYZE not in states
    assert an.calls == [] and shots(scene) >= 1


def test_smart_crop_only_skips_collect(start):
    an = FakeAnalyzer()
    app, scene = start({**SMART, "BOOTH_CAPTURE_LOG": "1"}, an)
    to_shutter(app, scene)
    assert scene.state == ANALYZE
    frames, _, _ = an.calls[0]
    assert len(frames) == 1
    an.futures[0].set_result(make_result(app.frame, n=1))
    app.step(0.1, [])
    assert shots(scene) == 1
    # 얼굴이 없어 AI 는 가장 넓게, 찍은 그대로는 기본 구도 — 고르기를 거쳐야 cut 줄이 써진다 (Task G)
    app.step(0.1, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0, scancode=0)])
    assert read_records(app)[-1]["collect_ms"] < 50  # 수집 단계가 없다


def test_retake_replaces_faces_at_same_position(start):
    an = FakeAnalyzer()
    app, scene = start(BURST, an)
    s = scene.shoot.session
    from PIL import Image
    for k in range(4):
        s.add_shot(Image.new("RGB", (4, 4)), [k])
    s.retake_queue = [2]
    s.add_shot(Image.new("RGB", (4, 4)), None)
    assert s.shot_faces == [[0], [1], None, [3]]


def read_records(app) -> list[dict]:
    path = app.capture_log.path
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_metrics_written_without_image_data(start):
    an = FakeAnalyzer()
    app, scene = start({**BURST, "BOOTH_CAPTURE_LOG": "1"}, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    res = make_result(app.frame, reason="best", n=5)
    res.info["detect_mode"] = "full+halves"
    an.futures[0].set_result(res)
    app.step(0.1, [])
    rec = read_records(app)[-1]
    assert rec["detect_mode"] == "full+halves"  # 분석기가 쓴 검출 전략
    assert set(rec) == {"type", "shoot_id", "at", "collect_ms", "analyze_ms", "total_ms", "candidates", "reason",
                        "fallback_used", "cut", "preview_fps", "index", "cands", "faces", "faces_from", "unstable_faces", "faces_unstable",
                        "detect_mode", "choice", "choice_ms", "person_heads", "person_ms", "refined", "refine_ms"}
    assert rec["choice"] == "skipped" and rec["choice_ms"] == 0  # 셔터 프레임 그대로라 고를 것이 없다
    assert rec["type"] == "cut" and rec["candidates"] == 5 and rec["reason"] == "best"
    assert rec["fallback_used"] is False and rec["shoot_id"] == app.shoot_id and len(rec["cands"]) == 5
    assert all(isinstance(v, (str, int, float, bool)) for k, v in rec.items()
               if k not in ("cands", "faces", "faces_from", "faces_unstable", "person_ms", "refined", "refine_ms"))
    assert rec["faces_from"] is None and rec["unstable_faces"] == 0 and rec["faces_unstable"] == []  # 빌리지 않음 · 걸러진 얼굴 없음
    assert rec["collect_ms"] >= 0 and rec["analyze_ms"] >= 0  # 실제 경과 시간 (시험은 가짜 시간이라 작다)
    assert rec["total_ms"] == pytest.approx(rec["collect_ms"] + rec["analyze_ms"], abs=0.2)


def test_flags_off_writes_no_cut_record(start):
    app, scene = start({"BOOTH_CAPTURE_LOG": "1"}, None)
    tick(app, 6)
    assert shots(scene) >= 1
    assert [r["type"] for r in read_records(app)] == ["session"]  # 촬영 시작 줄만, cut 줄 없음


# ---- 미리보기 (스마트 크롭이면 기본 구도로 고정) ----
def _live(app, scene) -> dict:
    """장면을 한 번 그리며 LiveView.render 에 넘긴 값과 결과를 잡는다."""
    import pygame

    got: dict = {}
    orig = scene.live.render

    def spy(*a, **k):
        got["args"], got["surf"] = a, orig(*a, **k)
        return got["surf"]

    scene.live.render = spy
    scene.draw(pygame.Surface((app.stage.w, app.stage.h)))
    return got


def _expected(frame, ratio, size, mirror, crop) -> bytes:
    """미리보기 처리 과정을 그대로 따라 만든 픽셀 (자르기 → 줄이기 → 거울 → 필터)."""
    import cv2
    import pygame
    from walnut import ui
    from walnut.filters import apply_filter
    from walnut.scenes.capture import fit, mirrored

    x, y, cw, ch = crop
    w, h = fit(ratio, size)
    small = cv2.resize(frame[y:y + ch, x:x + cw], (w, h), interpolation=cv2.INTER_AREA)
    small = apply_filter(np.ascontiguousarray(mirrored(small, mirror)), "original")
    return pygame.image.tobytes(ui.np_to_surface(small), "RGB")


def test_preview_unchanged_when_flag_off(start):
    import pygame
    from walnut.compose import cover_crop

    app, scene = start({}, None)
    got = _live(app, scene)
    ratio, size, filt, sticker, mirror = got["args"][:5]
    assert len(got["args"]) == 5 or got["args"][5] == 1.0
    fh, fw = app.frame.shape[:2]
    want = _expected(app.frame, ratio, size, mirror, cover_crop(fw, fh, ratio, 1.0))
    assert pygame.image.tobytes(got["surf"], "RGB") == want   # 픽셀까지 지금과 같다


def test_preview_shows_home_when_smart_crop_on(start):
    import pygame
    from walnut.compose import cover_crop
    from walnut.framing import BASE_ZOOM, centered_crop, home_crop

    app, scene = start(SMART, FakeAnalyzer())
    got = _live(app, scene)
    ratio, size, filt, sticker, mirror, zoom = got["args"]
    fh, fw = app.frame.shape[:2]
    sl = next(x for x in scene.shoot.session.frame["slots"] if x["shot"] == 0)
    assert zoom == BASE_ZOOM
    assert centered_crop(fw, fh, ratio, zoom) == home_crop(fw, fh, sl["w"], sl["h"])  # 결과 사진의 기본 구도와 같다
    want = _expected(app.frame, ratio, size, mirror, centered_crop(fw, fh, ratio, zoom))
    plain = _expected(app.frame, ratio, size, mirror, cover_crop(fw, fh, ratio, 1.0))
    out = pygame.image.tobytes(got["surf"], "RGB")
    assert out == want and out != plain


def test_preview_zoom_respects_slot_upscale_limit(start, monkeypatch):
    from walnut import framing
    from walnut.scenes.capture import preview_zoom

    app, scene = start(SMART, FakeAnalyzer())
    monkeypatch.setattr(framing, "MAX_UPSCALE", 0.1)  # 어떤 배율도 한계를 넘는다 → 1배
    assert preview_zoom(app, scene.shoot, 0, 1280, 720) == 1.0
    app.cfg = __import__("dataclasses").replace(app.cfg, smart_crop=False)
    monkeypatch.undo()
    assert preview_zoom(app, scene.shoot, 0, 1280, 720) == 1.0  # 꺼져 있으면 언제나 1배


def test_timeout_cut_line_records_configured_detect_mode(start):
    from walnut import analysis

    an = FakeAnalyzer()
    app, scene = start({**BURST, "BOOTH_CAPTURE_LOG": "1"}, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    tick(app, ANALYZE_TIMEOUT + 0.2)
    rec = read_records(app)[-1]
    assert rec["reason"] == "timeout"
    assert rec["detect_mode"] == analysis.DETECT_MODE   # 결과가 없어도 분석기 설정을 남긴다


def test_error_cut_line_records_analyzer_detect_mode(start):
    an = FakeAnalyzer()
    an.detect_mode = "full"                              # 분석기에 따로 정한 전략이 있으면 그것
    app, scene = start({**BURST, "BOOTH_CAPTURE_LOG": "1"}, an)
    to_shutter(app, scene)
    tick(app, BURST_AFTER + 0.1)
    an.futures[0].set_exception(RuntimeError("분석 실패"))
    app.step(0.1, [])
    rec = read_records(app)[-1]
    assert rec["reason"] == "error" and rec["detect_mode"] == "full"
