"""업로드 대기열.

QR 은 업로드가 끝나기를 기다리지 않고 바로 띄운다. 토큰을 부스가 먼저 정하고, 사진은
data/outbox 에 넣어 두면 이 스레드가 서버로 올린다. 와이파이가 잠깐 끊겨도 줄이 멈추지
않고, 프로그램을 껐다 켜도 outbox 에 남은 것부터 다시 올린다.
"""

from __future__ import annotations

import logging
import math
import os
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from walnut.api import BoothApi, Rejected, Revoked, Unreachable

log = logging.getLogger(__name__)

# state() 값
UPLOADING, DONE, RETRYING, NO_SERVER = 0, 1, 2, 3


def new_token() -> str:
    return secrets.token_urlsafe(12)  # 16자, 추측 불가


class Uploader:
    def __init__(self, outbox: Path, api: BoothApi | None, on_revoked: Callable[[], None],
                 *, backoff_base: float = 2.0, backoff_max: float = 60.0) -> None:
        self.outbox = Path(outbox)
        self.outbox.mkdir(parents=True, exist_ok=True)
        self._api = api
        self._on_revoked = on_revoked
        self._base = backoff_base
        self._max = backoff_max
        self.last_error = ""
        self._lock = threading.Lock()
        self._state: dict[str, int] = {}
        self._busy = False
        self._revoked = False
        self._stop = False
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        # 지난 실행에서 못 올린 사진은 대기 상태로 시작한다
        for p in self._files():
            self._state[p.stem] = UPLOADING

    # ---- 바깥에서 쓰는 것 ----

    def enqueue(self, token: str, jpeg: Path) -> None:
        """outbox/<token>.jpg 로 원자적으로 복사하고 스레드를 깨운다. 서버가 없으면 아무것도 안 한다."""
        if self._api is None:
            return
        tmp = self.outbox / f".{token}.tmp"
        shutil.copy2(jpeg, tmp)
        with self._lock:  # 파일이 보이기 전에 상태부터 (스레드가 먼저 올려 DONE 이 되어도 덮어쓰지 않게)
            self._state[token] = UPLOADING
        os.replace(tmp, self.outbox / f"{token}.jpg")
        self._wake.set()

    def state(self, token: str) -> int:
        """0 업로드 중, 1 완료, 2 재시도 중, 3 서버 없음(또는 모르는 토큰)."""
        with self._lock:
            if self._api is None:
                return NO_SERVER
            return self._state.get(token, NO_SERVER)

    def pending(self) -> int:
        return len(self._files())

    def set_api(self, api: BoothApi | None) -> None:
        """재페어링 뒤 교체. 해제로 멈춰 있었다면 다시 올리기 시작한다."""
        with self._lock:
            self._api = api
            self._revoked = False
        self._wake.set()

    def orphan_all(self) -> int:
        """outbox 의 jpg 를 outbox/orphaned/ 로 옮긴다 (연결 해제 시). 옮긴 개수."""
        files = self._files()
        if not files:
            return 0
        dest = self.outbox / "orphaned"
        dest.mkdir(exist_ok=True)
        n = 0
        for p in files:
            with self._lock:
                self._state.pop(p.stem, None)
            try:
                os.replace(p, dest / p.name)
                n += 1
            except OSError:
                log.exception("orphan 이동 실패: %s", p.name)
        return n

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="uploader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()

    def wait_idle(self, timeout: float) -> bool:
        """테스트용: 대기 중인 사진이 없고 올리는 중도 아니면 True."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self._busy and self.pending() == 0:
                return True
            time.sleep(0.01)
        return not self._busy and self.pending() == 0

    # ---- 스레드 ----

    def _files(self) -> list[Path]:
        out = []
        for p in self.outbox.glob("*.jpg"):
            try:
                out.append((p.stat().st_mtime, p))
            except OSError:
                pass  # 그사이 옮겨졌다
        return [p for _, p in sorted(out)]

    def _set(self, token: str, st: int) -> None:
        with self._lock:
            self._state[token] = st

    def _run(self) -> None:
        backoff = self._base
        while not self._stop:
            self._wake.clear()
            with self._lock:
                api, revoked = self._api, self._revoked
            files = self._files() if api is not None and not revoked else []
            if not files:
                self._wake.wait()
                continue
            self._busy = True
            wait: float | None = None
            try:
                for path in files:
                    if self._stop:
                        break
                    try:
                        result = self._upload(api, path)
                    except Exception as e:  # 예상 밖 오류로 스레드가 죽지 않게
                        log.exception("업로드 중 예상 밖 오류: %s", path.name)
                        self.last_error = f"오류: {e.__class__.__name__}"
                        self._set(path.stem, RETRYING)
                        result = "retry"
                    if result == "revoked":
                        with self._lock:
                            current = self._api is api
                            if current:
                                self._revoked = True
                        if current:  # set_api 로 이미 바뀌었다면 옛 api 의 해제는 무시
                            try:
                                self._on_revoked()
                            except Exception:
                                log.exception("on_revoked 콜백 오류")
                        break
                    if isinstance(result, float) or result == "retry":
                        wait = backoff
                        if isinstance(result, float) and math.isfinite(result) and result > 0:
                            wait = min(result, self._max)
                        backoff = min(self._max, backoff * 2)
                        break
                    backoff = self._base
            finally:
                self._busy = False
            if wait is not None:
                self._wake.wait(timeout=wait)

    def _upload(self, api: BoothApi, path: Path):
        """'ok' | 'rejected' | 'revoked' | 'retry' | 재시도까지 기다릴 초(float)."""
        token = path.stem
        try:
            api.upload_photo(token, path.read_bytes())
        except FileNotFoundError:
            return "ok"  # 그사이 orphan 처리됨
        except Revoked:
            return "revoked"
        except Unreachable as e:
            self.last_error = f"서버에 닿지 않음: {e}"
            self._set(token, RETRYING)
            return float(e.retry_after) if e.retry_after is not None else "retry"
        except Rejected as e:
            self.last_error = f"거절됨 {e.status} {e.code}"
            failed = self.outbox / "failed"
            failed.mkdir(exist_ok=True)
            try:
                os.replace(path, failed / path.name)
            except OSError:
                pass
            log.warning("%s 거절됨 (%s) -> outbox/failed 로 이동", path.name, self.last_error)
            self._set(token, NO_SERVER)
            return "rejected"
        self.last_error = ""
        path.unlink(missing_ok=True)
        self._set(token, DONE)
        return "ok"
