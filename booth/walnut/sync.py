"""번들 동기화 스레드: 주기마다 번들을 확인·받아 두고 하트비트를 보낸다.

받은 새 번들은 stage 까지만 하고 ready_version 에 표시한다. 적용(activate)은 앱이 대기 화면일 때 한다.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from walnut.version import app_version
from walnut.api import BoothApi, NotPublished, Rejected, Revoked, Unreachable
from walnut.bundle import BundleStore

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 30
MAX_DELAY = 300
MIN_FAIL_DELAY = 1


class SyncWorker:
    def __init__(self, api: BoothApi, store: BundleStore, status: Callable[[], dict],
                 interval_override: int | None, on_revoked: Callable[[], None],
                 clock=time.monotonic) -> None:
        self.api = api
        self.store = store
        self._status = status
        self._override = interval_override
        self._on_revoked = on_revoked
        self._clock = clock
        # 이 워커를 만든 뒤 store.clear() (재페어링) 가 있었으면 받은 번들을 남기지 않는다
        self._epoch = store.epoch
        # 읽기 전용 상태 (다른 스레드가 읽는다)
        self.ready_version: int | None = None
        self.last_ok_at: float | None = None
        self.last_error = ""
        self.online = False
        self.not_published = False
        self._failures = 0
        self._revoked = False
        self._stop = False
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- 한 주기 ----

    def _base_interval(self, cur) -> int:
        if self._override:
            return self._override
        if cur is not None:
            return cur.settings["sync"]["interval_sec"]
        return DEFAULT_INTERVAL

    def _fail(self, msg: str, base: int, retry_after: float | None = None) -> float:
        self._failures += 1
        self.last_error = msg
        if retry_after is not None:
            delay = min(retry_after, MAX_DELAY)
        else:
            delay = min(base * 2 ** self._failures, MAX_DELAY)
        return max(MIN_FAIL_DELAY, delay)  # Retry-After: 0 이어도 바쁜 루프가 되지 않게

    def _revoke(self) -> None:
        if not self._revoked:
            self._revoked = True
            log.warning("서버가 이 기기를 해제함")
            self._on_revoked()

    def run_once(self) -> float:
        """한 주기를 실행하고 다음 대기 초를 돌려준다. 해제된 뒤에는 아무것도 하지 않는다."""
        cur = self.store.current()
        base = self._base_interval(cur)
        if self._revoked:
            return base
        cur_v = cur.version if cur else None
        if self.ready_version is not None and cur_v is not None and cur_v >= self.ready_version:
            self.ready_version = None  # 앱이 이미 적용함
        known = [v for v in (cur_v, self.ready_version) if v is not None]
        etag = f'"v{max(known)}"' if known else None

        try:
            got = self.api.get_bundle(etag)
            if got is not None:
                version = self.store.stage(got[0], self.api.get_asset, epoch=self._epoch)
                if version != cur_v:
                    self.ready_version = version
                    log.info("새 번들 %s 받아 둠", version)
            self.not_published = False
            self._ok()
            delay = base
        except Revoked:
            self._revoke()
            return base
        except NotPublished:
            self.not_published = True
            self._ok()
            delay = base
        except Unreachable as e:
            self.online = False
            log.warning("서버에 닿지 않음: %s", e)
            delay = self._fail("서버에 연결할 수 없음", base, e.retry_after)
        except (Rejected, ValueError) as e:
            log.warning("번들 받기 실패: %s", e)
            delay = self._fail("번들을 받지 못함", base)

        self._heartbeat(cur)
        return 0 if self._revoked else delay

    def _ok(self) -> None:
        self.online = True
        self.last_ok_at = self._clock()
        self.last_error = ""
        self._failures = 0

    def _heartbeat(self, cur) -> None:
        payload = {"app_version": app_version()}
        if cur is not None:
            payload["bundle_version"] = cur.version
        try:
            payload.update(self._status())
            self.api.heartbeat(payload)
        except Revoked:
            self._revoke()
        except Exception as e:  # 하트비트 실패는 번들 간격에 영향 없음
            log.warning("하트비트 실패: %s", e)

    # ---- 스레드 ----

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="sync", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop and not self._revoked:
            try:
                delay = self.run_once()
            except Exception:
                log.exception("동기화 주기 오류")
                delay = 60
            if self._stop or self._revoked:
                break
            self._wake.wait(delay)
            self._wake.clear()

    def sync_now(self) -> None:
        """대기 중이면 깨워 바로 한 주기를 돌린다."""
        self._wake.set()

    def stop(self, timeout: float = 10) -> None:
        """멈춤을 알리고 timeout 초까지 기다린다 (요청 도중이면 그 요청이 끝나야 멈춘다)."""
        self._stop = True
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)
