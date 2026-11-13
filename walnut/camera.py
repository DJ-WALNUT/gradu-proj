"""카메라 — 한 번만 열고 모든 장면이 같이 쓴다.

읽기는 별도 스레드에서 한다. 메인 루프는 '가장 최근 프레임'만 가져가므로
카메라가 느려도 화면 갱신이 막히지 않는다. 연결이 끊기면 스스로 다시 연다.
프레임은 반전하지 않은 RGB 배열이다 (거울 반전은 capture.mirror 설정에 따라 장면이 한다).

계약: read() 가 (n, None) 이면 "지금 새 프레임이 없다" 이다. 읽기 실패·재연결·열기 실패 때는
마지막 프레임을 지우고, STALE_SEC 보다 오래된 프레임도 None 으로 돌려준다.
호출하는 쪽은 connected 가 아니라 None 여부로 판단한다.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

import numpy as np

from .burst import FrameRing, TimedFrame

log = logging.getLogger(__name__)

STALE_SEC = 2.0  # 이보다 오래된 프레임은 없는 것으로 본다


def _cv2():
    import cv2  # 카메라를 실제로 쓸 때만 불러온다

    return cv2


def _open(index: int, width: int, height: int):
    cv2 = _cv2()
    if sys.platform == "win32":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)  # MSMF 보다 여는 속도가 훨씬 빠르다
    elif sys.platform == "darwin":
        cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    else:
        cap = cv2.VideoCapture(index)
    # 1080p 는 MJPG 로 받아야 30fps 가 나오는 웹캠이 많다.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def list_cameras(max_index: int = 6) -> None:
    """--list-cameras: 열리는 카메라 번호와 해상도를 출력한다."""
    cv2 = _cv2()
    found = False
    for i in range(max_index):
        cap = _open(i, 1920, 1080)
        if cap.isOpened():
            found = True
            print(f"  {i}번: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
        cap.release()
    if not found:
        print("  열 수 있는 카메라가 없습니다.")


class Camera:
    def __init__(self, index: int, width: int, height: int, ring: FrameRing | None = None):
        self.index, self.width, self.height = index, width, height
        self._ring = ring  # 있으면 읽은 프레임을 링 버퍼에도 쌓는다 (지능형 촬영)
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_t = 0.0
        self.frame_id = 0
        self.fps = 0.0
        self.connected = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def _drop_frame(self) -> None:
        with self._lock:
            self._frame = None
        self.connected = False

    def _run(self) -> None:
        cv2 = _cv2()
        cap = None
        last_ok = 0.0
        frames, t0 = 0, time.monotonic()
        while not self._stop.is_set():
            if cap is None or not cap.isOpened():
                cap = _open(self.index, self.width, self.height)
                if not cap.isOpened():
                    self._drop_frame()
                    log.warning("%d번 카메라를 열 수 없습니다. 2초 뒤 다시 시도합니다.", self.index)
                    self._stop.wait(2)
                    continue
                log.info("%d번 카메라 연결: %dx%d", self.index,
                         int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
                last_ok = time.monotonic()
            ok, bgr = cap.read()
            now = time.monotonic()
            if not ok:
                self._drop_frame()
                if now - last_ok > STALE_SEC:  # 2초 동안 프레임이 없으면 재연결
                    log.warning("프레임이 끊겨 다시 연결합니다.")
                    cap.release()
                    cap = None
                time.sleep(0.01)
                continue
            last_ok = now
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            with self._lock:
                self._frame = rgb
                self._frame_t = now
                self.frame_id += 1
            if self._ring is not None:
                self._ring.push(now, rgb)
            self.connected = True
            frames += 1
            if now - t0 >= 1.0:
                self.fps, frames, t0 = frames / (now - t0), 0, now
        if cap is not None:
            cap.release()

    def read(self) -> tuple[int, np.ndarray | None]:
        with self._lock:
            fresh = self._frame is not None and time.monotonic() - self._frame_t <= STALE_SEC
            return self.frame_id, (self._frame if fresh else None)

    def frames_between(self, t0: float, t1: float) -> list[TimedFrame]:
        """링 버퍼에서 t0~t1 (time.monotonic) 의 프레임. 링이 없으면 빈 목록."""
        return self._ring.between(t0, t1) if self._ring is not None else []

    def release(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._drop_frame()


class FakeCamera:
    """카메라 없이 화면 흐름을 확인할 때 쓴다 (--no-camera, 테스트). fail=True 면 프레임이 끊긴 상태."""

    fps = 30.0

    def __init__(self, width: int = 1280, height: int = 720):
        y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
        base = np.empty((height, width, 3), np.uint8)
        base[..., 0] = (70 + 40 * y).astype(np.uint8)
        base[..., 1] = (80 + 50 * y).astype(np.uint8)
        base[..., 2] = (110 + 60 * y).astype(np.uint8)
        self._frame = base
        self.frame_id = 0
        self.fail = False

    @property
    def connected(self) -> bool:
        return not self.fail

    def read(self) -> tuple[int, np.ndarray | None]:
        self.frame_id += 1
        return self.frame_id, (None if self.fail else self._frame)

    def frames_between(self, t0: float, t1: float) -> list[TimedFrame]:
        return [] if self.fail else [TimedFrame(t1, self._frame)]

    def release(self) -> None:
        pass
