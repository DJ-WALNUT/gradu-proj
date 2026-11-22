"""리모컨 OLED 연동 — 지금 장면의 상태를 USB 시리얼로 리모컨에 보낸다 (스펙 7.1).

리모컨(controller/)은 USB 키보드 + 시리얼 복합 장치다. 키 입력은 키보드로 들어오므로 여기서는 받지 않는다.
부스는 '지금 무엇을 하는 중인지'를 한 줄씩 보내고, 리모컨이 그에 맞는 화면을 그린다.

    L|F|2|6|따뜻하게        필터 6개 중 세 번째를 고르는 중
    A|1|73|100             컷마다 고르기: 'AI 추천' 쪽에 커서, 10초 중 7.3초 남음 (0 = 찍은 그대로)

바뀔 때 바로 보내고, 그대로여도 1초마다 다시 보낸다 (리모컨은 3초 끊기면 '부스 연결 대기').
H 줄(인사 + 프로토콜 버전 + 행사 제목)은 연결 직후와 10초마다 상태 줄보다 먼저 보낸다.
리모컨이 없거나 pyserial 이 없어도 부스는 그대로 돈다. 꽂았다 뺐다 해도 알아서 다시 잇는다.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

RP2040_VID = 0x2E8A  # Raspberry Pi — RP2040 보드의 USB 제조사 번호
BAUD = 115200
HEARTBEAT = 1.0
HELLO_EVERY = 10.0
RETRY = 2.0
TICK = 0.25
MAX_FIELD_BYTES = 47
PROTOCOL = 1


def fmt_line(*fields: object) -> str:
    """필드를 `|` 로 잇는다. 각 필드에서 `|`·줄바꿈을 지우고 UTF-8 경계를 지켜 47바이트로 자른다."""
    out = []
    for f in fields:
        s = str(f)
        for ch in "|\r\n":
            s = s.replace(ch, "")
        out.append(s.encode("utf-8")[:MAX_FIELD_BYTES].decode("utf-8", "ignore"))
    return "|".join(out)


class Remote:
    def __init__(self, port: str = "", *, clock: Callable[[], float] = time.monotonic,
                 serial_factory: Callable[[str], Any] | None = None, start: bool = True) -> None:
        """port: 비우면 자동으로 찾는다. 'off' 면 쓰지 않는다. COM5 처럼 직접 지정할 수도 있다.

        serial_factory(포트 이름) 은 write(bytes)·close() 가 있는 객체를 돌려준다 (기본은 pyserial).
        start=False 면 스레드를 띄우지 않는다 — 테스트가 _tick() 을 직접 부른다."""
        self.port = port.strip()
        self.connected = False
        self._clock = clock
        self._factory = serial_factory
        self._line = "-"
        self._title = ""
        self._ser: Any = None
        self._sent: str | None = None
        self._sent_at = 0.0
        self._hello_at: float | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._off = self.port.lower() == "off"
        if self._off:
            return
        if self._factory is None:
            try:
                import serial
            except ImportError:
                log.warning("[remote] pyserial 이 없어 리모컨 화면 연동을 끕니다 (pip install pyserial).")
                self._off = True
                return
            self._factory = lambda name: serial.Serial(name, BAUD, timeout=0, write_timeout=0.5)
        if start:
            self._thread = threading.Thread(target=self._run, name="remote", daemon=True)
            self._thread.start()

    def set(self, line: str) -> None:
        if line != self._line:
            self._line = line
            self._wake.set()

    def set_title(self, title: str) -> None:
        self._title = title

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._drop()

    def _find(self) -> str | None:
        if self.port:
            return self.port
        try:
            from serial.tools import list_ports
        except ImportError:
            return None
        for p in list_ports.comports():
            if p.vid == RP2040_VID:
                return p.device
        return None

    def _drop(self) -> None:
        ser, self._ser = self._ser, None
        self.connected = False
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def _send(self, line: str) -> None:
        self._ser.write((line + "\n").encode("utf-8"))

    def _tick(self) -> float:
        """한 번 돌린다. 다음 호출까지 기다릴 초를 돌려준다."""
        if self._off:
            return RETRY
        if self._ser is None:
            name = self._find()
            if name:
                try:
                    self._ser = self._factory(name)
                    log.info("[remote] 리모컨 연결: %s", name)
                    self.connected = True
                    self._sent = None
                    self._hello_at = None
                except OSError:
                    self._ser = None
            if self._ser is None:
                return RETRY
        now = self._clock()
        try:
            if self._hello_at is None or now - self._hello_at >= HELLO_EVERY:
                self._send(fmt_line("H", PROTOCOL, self._title))
                self._hello_at = now
            line = self._line
            if line != self._sent or now - self._sent_at >= HEARTBEAT:
                self._send(line)
                self._sent, self._sent_at = line, now
            reset = getattr(self._ser, "reset_input_buffer", None)
            if reset is not None:
                reset()  # 리모컨이 찍는 키 로그는 버린다 (쌓이면 리모컨 쪽 쓰기가 막힐 수 있다)
        except OSError:
            log.warning("[remote] 리모컨 연결이 끊겼습니다. 다시 찾는 중…")
            self._drop()
            return RETRY
        return TICK

    def _run(self) -> None:
        while not self._stop.is_set():
            wait = self._tick()
            self._wake.wait(wait)
            self._wake.clear()
