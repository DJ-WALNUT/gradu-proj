from __future__ import annotations

import numpy as np
import pytest

from tests.facekit import fake_face
from walnut import ar
from walnut.camera import FakeCamera
from walnut.vision import FaceDetector


def test_geometry_upright_and_rolled():
    g = ar.geometry(fake_face(roll=0), 1000, 1000)
    assert abs(g.roll_deg) < 1e-4 and abs(g.width - 160) < 1e-3 and abs(g.height - 200) < 1e-3
    assert abs(g.nose[1] - 530) < 1e-3
    g30 = ar.geometry(fake_face(roll=30), 1000, 1000)
    assert abs(g30.roll_deg - 30) < 1e-3


def test_tracker_jitter_hold_follow():
    rng = np.random.default_rng(0)
    tr = ar.FaceTracker()
    raw_x, out_x = [], []
    for k in range(90):
        x = 0.5 + rng.normal(0, 0.004)
        raw_x.append(x)
        out_x.append(tr.update([fake_face(x, 0.5)], k / 30)[0][10].x)
    assert np.std(out_x[30:]) < np.std(raw_x[30:]) / 3
    assert len(tr.update([], 3.2)) == 1  # 0.2초 끊겨도 유지
    assert len(tr.update([], 3.5)) == 0  # 0.3초 넘기면 사라짐

    tr = ar.FaceTracker()
    for k in range(10):
        tr.update([fake_face(0.3, 0.5)], k / 30)
    for k in range(10, 25):
        out = tr.update([fake_face(0.3 + 0.1 * (k - 9) / 15, 0.5)], k / 30)
    assert len(out) == 1 and abs(out[0][10].x - 0.4) < 0.02


def test_tracker_keeps_nose():
    out = ar.FaceTracker().update([fake_face()], 0.0)
    assert 1 in out[0]


def test_detector_unavailable_without_model(tmp_path):
    d = FaceDetector(tmp_path / "none.task")
    assert d.available is False
    assert d.faces(np.zeros((10, 10, 3), np.uint8)) == []
    d.close()


def test_fake_camera():
    cam = FakeCamera(64, 48)
    n, f = cam.read()
    assert f.shape == (48, 64, 3) and cam.connected
    cam.fail = True
    n2, f2 = cam.read()
    assert n2 > n and f2 is None and cam.connected is False
    cam.fail = False
    assert cam.read()[1] is not None and cam.connected
    cam.release()


def test_real_camera_returns_none_when_not_delivering(monkeypatch):
    import time

    from walnut import camera as cammod

    class Cap:
        ok = True

        def isOpened(self):
            return True

        def read(self):
            time.sleep(0.005)
            return (True, np.zeros((4, 4, 3), np.uint8)) if self.ok else (False, None)

        def get(self, *_):
            return 0

        def release(self):
            pass

    cap = Cap()
    monkeypatch.setattr(cammod, "_open", lambda *a: cap)
    cam = cammod.Camera(0, 4, 4)

    def wait(cond):
        for _ in range(200):
            if cond():
                return True
            time.sleep(0.01)
        return False

    try:
        assert wait(lambda: cam.read()[1] is not None)
        cap.ok = False  # 케이블 빠짐: 오래된 프레임을 돌려주면 안 된다
        assert wait(lambda: cam.read()[1] is None)
        assert cam.connected is False
        cap.ok = True
        assert wait(lambda: cam.read()[1] is not None)
    finally:
        cam.release()
    assert cam.read()[1] is None
