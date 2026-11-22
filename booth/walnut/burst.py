"""지능형 촬영 바탕 — 최근 프레임 링 버퍼, 측정 기록, 시퀀스 저장 형식.

링 버퍼는 카메라 스레드가 채우고 촬영 장면이 읽는다. 원본 프레임은 메모리에만 두고 디스크에 쓰지 않는다.
예외는 시퀀스 저장(save_sequence)뿐이다 — 동의를 받은 녹화 도구(tools/record_burst.py)와
현장 시험 샘플 모드(fieldlog.SampleWriter)만 부른다.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimedFrame:
    t: float  # time.monotonic()
    rgb: np.ndarray


class FrameRing:
    """최근 keep_sec 초의 프레임을 보관한다. 프레임은 복사하지 않고 참조만 쥔다.

    - min_gap_sec: 마지막으로 보관한 프레임과 이보다 가까우면 건너뛴다 (같은 값이면 보관).
    - max_bytes: 넘으면 오래된 것부터 버린다. 이보다 큰 프레임 한 장은 아예 보관하지 않는다.
    """

    def __init__(self, keep_sec: float = 1.2, min_gap_sec: float = 0.08,
                 max_bytes: int = 128 * 1024 * 1024):
        self.keep_sec, self.min_gap_sec, self.max_bytes = keep_sec, min_gap_sec, max_bytes
        self._frames: deque[TimedFrame] = deque()
        self._bytes = 0
        self._lock = threading.Lock()

    def _pop_oldest(self) -> None:
        self._bytes -= self._frames.popleft().rgb.nbytes

    def push(self, t: float, rgb: np.ndarray) -> None:
        size = rgb.nbytes
        if size > self.max_bytes:
            return
        with self._lock:
            if self._frames and t - self._frames[-1].t < self.min_gap_sec:
                return
            self._frames.append(TimedFrame(t, rgb))
            self._bytes += size
            while self._frames and self._frames[0].t < t - self.keep_sec:
                self._pop_oldest()
            while self._bytes > self.max_bytes:
                self._pop_oldest()

    def between(self, t0: float, t1: float) -> list[TimedFrame]:
        """t0 ≤ t ≤ t1 인 프레임을 시간순으로."""
        with self._lock:
            return [f for f in self._frames if t0 <= f.t <= t1]


JPEG_QUALITY = 95  # 시퀀스 프레임 저장 품질


def save_sequence(dir: Path, frames: list[TimedFrame], shutter_t: float, meta: dict) -> None:
    """frames 를 000.jpg ... 로, 나머지를 meta.json 에 쓴다. frames 는 읽기만 한다."""
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, f in enumerate(frames):
        name = f"{i:03d}.jpg"
        Image.fromarray(f.rgb).save(dir / name, "JPEG", quality=JPEG_QUALITY)
        entries.append({"file": name, "t": f.t})
    out = {**meta, "shutter_t": shutter_t, "frames": entries}
    (dir / "meta.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def load_sequence(dir: Path) -> tuple[list[TimedFrame], float, dict]:
    dir = Path(dir)
    meta = json.loads((dir / "meta.json").read_text(encoding="utf-8"))
    frames = []
    for e in meta["frames"]:
        with Image.open(dir / e["file"]) as im:
            frames.append(TimedFrame(e["t"], np.asarray(im.convert("RGB"))))
    return frames, meta["shutter_t"], meta


class CaptureLog:
    """측정값을 한 줄 JSON 으로 덧붙인다. 경로가 None 이면 아무것도 하지 않는다.

    줄마다 type · shoot_id(지금 촬영, 없으면 None) · at(기록 시각) 을 앞에 붙인다 — 이미 있으면 그 값을 둔다.
    shoot_id 는 앱이 촬영을 시작할 때 정한다 (QR 토큰과 무관한 무작위 값).
    이미지는 넣지 않는다. 기록 실패가 부스를 멈추면 안 되므로 예외는 삼키고 경고만 남긴다.
    """

    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None
        self.shoot_id: str | None = None
        self._lock = threading.Lock()

    def write(self, record: dict) -> None:
        if self.path is None:
            return
        try:
            stamp = {"type": record.get("type"), "shoot_id": self.shoot_id,
                     "at": datetime.now().isoformat(timespec="seconds")}
            line = json.dumps({**stamp, **record}, ensure_ascii=False)
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except (OSError, TypeError, ValueError) as e:
            log.warning("촬영 측정 기록을 쓰지 못했습니다: %s", e)
