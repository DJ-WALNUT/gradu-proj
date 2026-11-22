"""링 버퍼 · 지능형 촬영 플래그 · 측정 기록."""

from __future__ import annotations

import json
import time

import numpy as np

from walnut.burst import CaptureLog, FrameRing, TimedFrame
from walnut.camera import FakeCamera


def _f(n: int = 4) -> np.ndarray:
    return np.zeros((n, n, 3), np.uint8)


def test_ring_skips_frames_closer_than_min_gap():
    ring = FrameRing(min_gap_sec=0.08)
    for t in (0.00, 0.03, 0.09):
        ring.push(t, _f())
    assert [fr.t for fr in ring.between(0, 1)] == [0.00, 0.09]


def test_ring_keeps_frame_exactly_at_min_gap():
    ring = FrameRing(min_gap_sec=0.5)
    ring.push(0.0, _f())
    ring.push(0.5, _f())
    assert len(ring.between(0, 1)) == 2


def test_ring_drops_frames_older_than_keep_sec():
    ring = FrameRing(keep_sec=1.0, min_gap_sec=0.0)
    for t in (0.0, 0.5, 1.0, 1.6):
        ring.push(t, _f())
    assert [fr.t for fr in ring.between(0, 10)] == [1.0, 1.6]


def test_ring_stays_under_max_bytes():
    frame = np.zeros((2160, 3840, 3), np.uint8)  # 4K, 약 25MB
    cap = 128 * 1024 * 1024
    ring = FrameRing(keep_sec=100, min_gap_sec=0.0, max_bytes=cap)
    for i in range(20):
        ring.push(float(i), frame)
        assert sum(fr.rgb.nbytes for fr in ring.between(-1, 100)) <= cap
    assert 0 < len(ring.between(-1, 100)) < 20
    # 가장 최근 프레임은 남는다
    assert ring.between(-1, 100)[-1].t == 19.0


def test_ring_does_not_store_single_frame_over_cap():
    ring = FrameRing(max_bytes=10)
    ring.push(0.0, _f())
    assert ring.between(-1, 1) == []


def test_between_returns_sorted_window_only():
    ring = FrameRing(keep_sec=10, min_gap_sec=0.0)
    for t in (0.0, 0.1, 0.2, 0.3, 0.4):
        ring.push(t, _f())
    got = ring.between(0.1, 0.3)  # 양 끝 포함
    assert [fr.t for fr in got] == [0.1, 0.2, 0.3]
    assert all(isinstance(fr, TimedFrame) for fr in got)


def test_between_is_empty_when_nothing_in_window():
    ring = FrameRing(keep_sec=10, min_gap_sec=0.0)
    ring.push(0.0, _f())
    assert ring.between(1.0, 2.0) == []
    assert FrameRing().between(0.0, 1.0) == []


def test_flags_default_on_and_read_env(tmp_path, monkeypatch):
    from walnut import config

    # 실제 기본값 (2026-11-22 결정): 버스트 · 구도 켬, 기록 끔. conftest 가 시험용으로 끈 것을 되돌려 본다.
    monkeypatch.setattr(config, "DEFAULT_BURST", True)
    monkeypatch.setattr(config, "DEFAULT_SMART_CROP", True)
    cfg = config.load(env={}, root=tmp_path)
    assert (cfg.burst, cfg.smart_crop, cfg.capture_log) == (True, True, False)
    cfg = config.load(env={"BOOTH_BURST": "0", "BOOTH_SMART_CROP": "false"}, root=tmp_path)
    assert (cfg.burst, cfg.smart_crop) == (False, False)
    cfg = config.load(env={"BOOTH_BURST": "1", "BOOTH_SMART_CROP": "true", "BOOTH_CAPTURE_LOG": "on"},
                      root=tmp_path)
    assert (cfg.burst, cfg.smart_crop, cfg.capture_log) == (True, True, True)


def test_capture_log_none_writes_nothing(tmp_path):
    CaptureLog(None).write({"a": 1})
    assert list(tmp_path.iterdir()) == []


def test_capture_log_appends_json_lines(tmp_path):
    path = tmp_path / "logs" / "capture_metrics.jsonl"
    log = CaptureLog(path)
    log.write({"cut": 1, "name": "호두"})
    log.write({"cut": 2})
    log.shoot_id = "abc"
    log.write({"type": "mark", "shoot_id": "keep"})  # 이미 있는 값은 그대로
    lines = path.read_text(encoding="utf-8").splitlines()
    recs = [json.loads(x) for x in lines]
    assert [{k: v for k, v in r.items() if k != "at"} for r in recs] == [
        {"type": None, "shoot_id": None, "cut": 1, "name": "호두"}, {"type": None, "shoot_id": None, "cut": 2},
        {"type": "mark", "shoot_id": "keep"}]
    assert all(len(r["at"]) == 19 for r in recs)  # 기록 시각 (초까지)
    assert "호두" in lines[0]  # ensure_ascii=False


def test_capture_log_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    CaptureLog(blocker / "sub" / "m.jsonl").write({"a": 1})  # 디렉터리를 만들 수 없다
    CaptureLog(tmp_path / "m.jsonl").write({"a": object()})  # 직렬화 불가
    assert not (tmp_path / "m.jsonl").exists() or (tmp_path / "m.jsonl").read_text() == ""


def test_fake_camera_frames_between():
    cam = FakeCamera(8, 8)
    got = cam.frames_between(0.0, 1.0)
    assert len(got) == 1 and got[0].t == 1.0 and got[0].rgb.shape == (8, 8, 3)
    cam.fail = True
    assert cam.frames_between(0.0, 1.0) == []


def test_real_camera_pushes_frames_into_ring(monkeypatch):
    from walnut import camera as cammod

    class Cap:
        def isOpened(self):
            return True

        def read(self):
            time.sleep(0.005)
            return True, np.zeros((4, 4, 3), np.uint8)

        def get(self, *_):
            return 0

        def release(self):
            pass

    monkeypatch.setattr(cammod, "_open", lambda *a: Cap())
    ring = FrameRing(min_gap_sec=0.0)
    cam = cammod.Camera(0, 4, 4, ring=ring)
    try:
        t0 = time.monotonic()
        for _ in range(200):
            if cam.frames_between(t0 - 1, time.monotonic()):
                break
            time.sleep(0.01)
        assert cam.frames_between(t0 - 1, time.monotonic())
    finally:
        cam.release()
    # 링 없이 만든 카메라는 빈 목록 (brief: camera_without_ring)
    cam2 = cammod.Camera(0, 4, 4)
    try:
        assert cam2.frames_between(0, time.monotonic()) == []
    finally:
        cam2.release()
