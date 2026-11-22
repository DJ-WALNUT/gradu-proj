"""현장 기록 — 지인 · 행사에서 돌린 뒤 알고리즘을 고치려고 남기는 것.

    1 진단 로그   항상          data/logs/booth-YYYY-MM-DD.log (일별, 파일당 5MB, 14일 보관)
    2 촬영 기록   BOOTH_CAPTURE_LOG=1   data/logs/capture_metrics.jsonl (수치만 — burst.CaptureLog)
    3 샘플       BOOTH_FIELD_SAMPLES=1 + BOOTH_FIELD_CONSENT=<테스트 이름>
                 eval_data/field_<날짜>_<테스트 이름>/ 에 버스트 후보 원본 시퀀스. 동의한 지인 시험만, 행사에서는 쓰지 않는다.

어느 것도 실패해서 촬영이나 앱 시작을 멈추면 안 된다. 어느 것도 업로드하지 않는다.
QR 토큰 · 합성본 파일 이름은 기록에 넣지 않는다 (촬영은 무작위 shoot_id 로 구분한다).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable

from .burst import TimedFrame, save_sequence

log = logging.getLogger(__name__)

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_KEEP_DAYS = 14
LOG_BACKUPS = 9  # 하루에 크기로 회전한 파일을 이만큼까지 (booth-날짜.1.log ...)
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
SAMPLE_MAX_BYTES = 2 * 1024 ** 3
SAMPLE_QUEUE = 4

SAMPLE_NOTE = "테스트 촬영 중 — 사진이 분석용으로 저장됩니다"
MARK_NOTICE = "문제 표시를 남겼어요"
MARK_NO_LOG = "문제 표시는 진단 로그에만 남았어요 (촬영 기록 꺼짐)"

_LOG_NAME = re.compile(r"^booth-(\d{4}-\d{2}-\d{2})(?:\.\d+)?\.log$")


# ---- 1 진단 로그 ----
class DailyFileHandler(logging.Handler):
    """booth-YYYY-MM-DD.log 에 쓴다. 날짜가 바뀌면 새 파일, max_bytes 를 넘으면 .1 .2 … 로 밀어 낸다.

    keep_days 보다 오래된 파일은 열 때마다 지운다.
    """

    def __init__(self, logs_dir: Path, max_bytes: int = LOG_MAX_BYTES, keep_days: int = LOG_KEEP_DAYS,
                 today: Callable[[], date] = date.today):
        super().__init__()
        self.dir = Path(logs_dir)
        self.max_bytes, self.keep_days, self._today = max_bytes, keep_days, today
        self._day = ""
        self._stream = None
        self._size = 0
        self._open(self._today().isoformat())  # 여기서 실패하면 setup_file_log 가 잡는다

    def _path(self, day: str, k: int = 0) -> Path:
        return self.dir / (f"booth-{day}.log" if k == 0 else f"booth-{day}.{k}.log")

    def _open(self, day: str) -> None:
        self._close_stream()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._day = day
        path = self._path(day)
        self._stream = path.open("ab")
        self._size = path.stat().st_size
        self._prune()

    def _prune(self) -> None:
        cut = (self._today() - timedelta(days=self.keep_days)).isoformat()
        for p in self.dir.glob("booth-*.log"):
            m = _LOG_NAME.match(p.name)
            if m and m.group(1) < cut:
                try:
                    p.unlink()
                except OSError:
                    pass

    def _roll(self) -> None:
        self._close_stream()
        for k in range(LOG_BACKUPS - 1, 0, -1):
            src = self._path(self._day, k)
            if src.exists():
                os.replace(src, self._path(self._day, k + 1))
        os.replace(self._path(self._day), self._path(self._day, 1))
        self._open(self._day)

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            finally:
                self._stream = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            data = (self.format(record) + "\n").encode("utf-8", "replace")
            day = self._today().isoformat()
            if day != self._day or self._stream is None:
                self._open(day)
            elif self._size > 0 and self._size + len(data) > self.max_bytes:
                self._roll()
            self._stream.write(data)
            self._stream.flush()
            self._size += len(data)
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self.acquire()
        try:
            self._close_stream()
        finally:
            self.release()
        super().close()


def setup_file_log(logs_dir: Path, *, max_bytes: int = LOG_MAX_BYTES,
                   keep_days: int = LOG_KEEP_DAYS) -> DailyFileHandler | None:
    """회전 파일 핸들러를 루트 로거(콘솔 로그)에 더한다. 실패하면 경고만 남기고 None — 앱은 그대로 뜬다.

    앱(App)이 자기 data 폴더 아래로 부르고 종료 때 remove_file_log 로 뗀다 (시험이 실제 data/ 에 쓰지 않게).
    먼저 붙어 있던 진단 로그 핸들러는 떼어 낸다 — 한 프로세스에 하나만 (같은 줄이 두 번 쓰이지 않게)."""
    root = logging.getLogger()
    for old in [x for x in root.handlers if isinstance(x, DailyFileHandler)]:
        remove_file_log(old)
    try:
        h = DailyFileHandler(logs_dir, max_bytes, keep_days)
    except OSError as e:
        log.warning("진단 로그 파일을 열지 못해 콘솔에만 남깁니다: %s", e)
        return None
    h.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(h)
    return h


def remove_file_log(h: logging.Handler | None) -> None:
    """setup_file_log 가 붙인 핸들러를 떼고 닫는다 (None 이면 아무것도 안 한다)."""
    if h is None:
        return
    logging.getLogger().removeHandler(h)
    h.close()


# ---- 2 촬영 기록 ----
def new_shoot_id() -> str:
    """손님 촬영 하나의 구분 값. QR 토큰과 무관한 무작위 값이라 기록으로 사진 주소를 알 수 없다."""
    return uuid.uuid4().hex[:12]


def _r(v, nd: int):
    return None if v is None else round(float(v), nd)


def cut_details(info: dict | None, shutter_t: float, faces, default_mode: str | None = None) -> dict:
    """cut 줄에 덧붙일 후보별 수치 · 고른 번호 · 얼굴 박스 · 검출 전략. 이미지는 없다.

    detect_mode 는 분석기가 쓴 검출 전략 (walnut/analysis.py DETECT_MODE). info 에 없으면 (시간 초과 ·
    오류로 결과가 없음) default_mode — 분석기에 설정된 전략, 그것도 없으면 None.
    faces_from 은 구도용 얼굴을 빌려 온 후보 번호 (빌리지 않았으면 None), unstable_faces 는 꾸준히 잡히지 않아
    고르기에서 뺀 얼굴 수 (후보마다 센 합), faces_unstable 은 faces(구도용) 중 꾸준하지 않은 얼굴의 번호
    (고르기에서는 뺐지만 구도에는 담았다). person_heads 는 사람 찾기로 구도에 더한 추정 머리 수 (faces 끝에 붙는다),
    person_ms 는 사람 찾기 시간 (돌지 않았으면 None), refined 는 머리 둘레를 잘라 얼굴을 다시 찾은 사람 수 · refine_ms 는
    그 시간 (walnut/analysis.py Task K). 모두 info 가 없으면 None.
    """
    out: dict = {"index": None, "cands": [], "faces": [],
                 "detect_mode": (info or {}).get("detect_mode") or default_mode,
                 "faces_from": (info or {}).get("faces_from"),
                 "unstable_faces": (info or {}).get("unstable_faces"),
                 "faces_unstable": (info or {}).get("faces_unstable"),
                 "person_heads": (info or {}).get("person_heads"),
                 "person_ms": _r((info or {}).get("person_ms"), 1),
                 "refined": (info or {}).get("refined"),
                 "refine_ms": _r((info or {}).get("refine_ms"), 1)}
    if faces:
        out["faces"] = [[_r(x, 3) for x in f.box] for f in faces]
    if not info:
        return out
    if "faces_added" in info:  # 고른 프레임에 없어 다른 후보에서 구도에 더한 얼굴 수 (faces 끝에 붙는다)
        out["faces_added"] = info["faces_added"]
    scores = info.get("scores") or []
    rejects = info.get("rejects") or []
    cands = []
    for i, c in enumerate(info.get("candidates") or []):
        cands.append({
            "dt": _r(c.get("t", shutter_t) - shutter_t, 3),
            "score": _r(scores[i], 4) if i < len(scores) else None,
            "sharpness": _r(c.get("sharpness"), 1), "faces": c.get("faces"),
            "eye": _r(c.get("eye"), 3), "frontality": _r(c.get("frontality"), 3),
            "reject": rejects[i] if i < len(rejects) else None,
        })
    out["index"] = info.get("index")
    out["cands"] = cands
    return out


def session_record(app, frame: dict, session) -> dict:
    """session 줄: 앱 판, 플래그, 평가 상수, 카메라, 행사 · 프레임."""
    from . import quality
    from .scenes import capture
    from .version import app_version

    cfg = app.cfg
    raw = app.frame
    cam = [int(raw.shape[1]), int(raw.shape[0])] if raw is not None else [cfg.camera_width, cfg.camera_height]
    return {
        "type": "session", "app_version": app_version(),
        "flags": {"burst": cfg.burst, "smart_crop": cfg.smart_crop, "capture_log": cfg.capture_log,
                  "samples": app.samples is not None, "dev": cfg.dev},
        "consts": {"W_SHARP": quality.W_SHARP, "W_EYE": quality.W_EYE, "W_POSE": quality.W_POSE,
                   "BLUR_REJECT": quality.BLUR_REJECT, "EYE_REJECT": quality.EYE_REJECT,
                   "POSE_MAX_DEG": quality.POSE_MAX_DEG, "BURST_BEFORE": capture.BURST_BEFORE,
                   "BURST_AFTER": capture.BURST_AFTER, "ANALYZE_TIMEOUT": capture.ANALYZE_TIMEOUT},
        "camera": cam, "camera_fps": round(float(app.camera.fps), 1),
        "event_id": app.bundle.event_id if app.bundle else None,
        "frame_id": frame.get("id"), "slots": len(frame.get("slots") or []),
        "cuts": session.n, "extra_shots": session.extra, "local": bool(app.local),
    }


def parse_lines(lines: Iterable[str]) -> tuple[list[dict], int]:
    """jsonl 줄들 → (기록, 건너뛴 줄 수). 잘린 줄 · 객체가 아닌 줄은 건너뛴다 (전원 차단 대비)."""
    out, broken = [], 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            broken += 1
            continue
        if isinstance(rec, dict):
            out.append(rec)
        else:
            broken += 1
    return out, broken


# ---- 3 샘플 ----
def samples_requested(cfg) -> bool:
    """샘플 모드는 플래그와 동의한 테스트 이름이 둘 다 있어야 켜진다."""
    return bool(cfg.field_samples and str(cfg.field_consent).strip())


def safe_name(s: str) -> str:
    """폴더 이름에 넣어도 상위 폴더로 나가지 못하게 문자만 남긴다."""
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE).strip("_.")
    return s[:40] or "test"


def _dir_bytes(d: Path) -> int:
    try:
        return sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
    except OSError:
        return 0


class SampleWriter:
    """버스트 후보 원본 시퀀스를 작업 스레드에서 저장한다. 촬영 흐름을 기다리게 하지 않는다.

    - save 는 바로 돌아온다: "queued" · 대기열이 차면 "dropped" (버리고 경고) · 용량을 넘었으면 "full".
    - 저장한 총량이 max_bytes 를 넘으면 그 뒤로는 저장하지 않는다.
    - 형식은 tools/record_burst.py 시퀀스와 같다 (compare_best.py --root <폴더> 로 그대로 재생).
    """

    def __init__(self, root: Path, consent: str, max_bytes: int = SAMPLE_MAX_BYTES,
                 queue_size: int = SAMPLE_QUEUE):
        self.consent = consent
        self.dir = Path(root) / f"field_{date.today():%Y%m%d}_{safe_name(consent)}"
        self.max_bytes = max_bytes
        self._bytes = _dir_bytes(self.dir) if self.dir.is_dir() else 0
        self.saved = sum(1 for _ in self.dir.glob("*/meta.json")) if self.dir.is_dir() else 0
        self.full = self._bytes >= max_bytes
        self.dropped = 0
        self._q: queue.Queue = queue.Queue(maxsize=max(1, queue_size))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="field-samples", daemon=True)
        self._thread.start()
        log.warning("현장 시험 샘플 모드: 버스트 후보 원본을 %s 에 저장합니다 (테스트 이름 %s)", self.dir, consent)

    def save(self, frames: list[TimedFrame], shutter_t: float, meta: dict) -> str:
        if self.full or self._stop.is_set():
            return "full"
        try:
            self._q.put_nowait((list(frames), float(shutter_t), dict(meta)))
        except queue.Full:
            self.dropped += 1
            log.warning("샘플 저장이 밀려 이번 컷은 버립니다 (누적 %d)", self.dropped)
            return "dropped"
        return "queued"

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._write(*item)
            except Exception as e:
                log.warning("샘플을 저장하지 못했습니다: %s", e)
            finally:
                self._q.task_done()

    def _write(self, frames: list[TimedFrame], shutter_t: float, meta: dict) -> None:
        if self.full:
            return
        base = f"{safe_name(str(meta.get('shoot_id') or 'shoot'))}_c{meta.get('cut', 0)}"
        d, k = self.dir / base, 2
        while d.exists():
            d, k = self.dir / f"{base}_{k}", k + 1
        h, w = frames[0].rgb.shape[:2] if frames else (0, 0)
        save_sequence(d, frames, shutter_t, {"subject": self.consent, "conditions": ["현장"], "field": True,
                                             "camera": [int(w), int(h)], **meta})
        self._bytes += _dir_bytes(d)
        self.saved += 1
        if self._bytes >= self.max_bytes:
            self.full = True
            log.warning("샘플이 %.1fMB 를 넘어 저장을 멈춥니다", self.max_bytes / 1024 ** 2)

    def flush(self, timeout: float = 5.0) -> bool:
        """대기열이 빌 때까지 기다린다 (시험 · 종료용)."""
        end = time.monotonic() + timeout
        with self._q.all_tasks_done:
            while self._q.unfinished_tasks:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._q.all_tasks_done.wait(left)
        return True

    def close(self, timeout: float = 2.0) -> None:
        self.flush(timeout)
        self._stop.set()
        self._thread.join(timeout=1.0)

    def status(self) -> str:
        s = f"분석용 샘플  {self.saved}건 저장"
        if self.full:
            s += "  (용량이 차서 멈춤)"
        if self.dropped:
            s += f"  밀려서 버림 {self.dropped}"
        return s
