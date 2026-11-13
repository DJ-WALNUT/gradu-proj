"""관리자 PIN 확인. 번들에는 HMAC-SHA256(key, pin) 만 있고 평문은 없다.

5회 연속 틀리면 60초 동안 잠근다. 잠겨 있는 동안의 입력은 횟수에 세지 않는다.
"""

from __future__ import annotations

import hmac
import time
from typing import Callable

MAX_FAILS = 5
LOCK_SECONDS = 60.0


class PinGate:
    def __init__(self, pin_hash: str, key: bytes, clock: Callable[[], float] = time.monotonic) -> None:
        self._hash = pin_hash or ""
        self._key = key
        self._clock = clock
        self._fails = 0
        self._lock_until = 0.0

    def locked_for(self) -> float:
        """잠금이 풀릴 때까지 남은 초 (잠겨 있지 않으면 0)."""
        return max(0.0, self._lock_until - self._clock())

    def check(self, pin: str) -> bool:
        if self.locked_for() > 0 or not self._hash:  # PIN 이 없으면 아무것도 통과시키지 않는다
            return False
        digest = hmac.new(self._key, pin.encode("utf-8"), "sha256").hexdigest()
        if hmac.compare_digest(digest, self._hash):
            self._fails = 0
            return True
        self._fails += 1
        if self._fails >= MAX_FAILS:
            self._lock_until = self._clock() + LOCK_SECONDS
            self._fails = 0
        return False
