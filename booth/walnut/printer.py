"""프린터.

- DummyPrinter: 인쇄할 이미지를 data/print_spool/ 에 PNG 로 쌓는다 (개발용, PRINTER_PORT=dummy).
- ReceiptPrinter: CPP-3000 영수증 프린터 (80mm 감열, 203dpi, 가로 576점). USB 가상 시리얼로 ESC/POS 래스터를
  직접 보낸다 — 드라이버가 필요 없다. 포트는 USB 번호(1CBE:0002)로 스스로 찾는다 (PRINTER_PORT 로 덮어쓰기).
  명령은 D:\\projects\\receipt-printer\\receipt.py 의 send 와 같다.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

import qrcode
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFont, ImageOps

log = logging.getLogger(__name__)

PRINTER_VID = 0x1CBE   # CPP-3000 USB 가상 시리얼
PRINTER_PID = 0x0002
PAPER_W = 576          # 72mm @ 203dpi
BAUD = 38400
BAND = 64              # GS v 0 한 번에 보내는 줄 수
FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Paperlogy-8ExtraBold.ttf"
SERVICE_NAME = "호두네사진관"

# 사진 톤 — 감열지는 점이 번져 화면보다 어둡게 나온다. 밝기 조절은 여기서 (tools/print_tune.py 로 한 장에 비교 인쇄)
PHOTO_GAMMA = 0.5        # 1.0 그대로, 작을수록 중간 톤이 밝아진다 (0.5~0.8 권장)
PHOTO_BRIGHTNESS = 1.2   # 1.0 그대로, 클수록 전체가 밝아진다
PHOTO_CONTRAST = 1.1     # 1.0 그대로, 클수록 진하고 또렷해진다 (너무 크면 얼굴이 하얗게 날아간다)
# 위 세 값은 2026-11-20 CPP-3000 비교 인쇄 두 장에서 사용자가 고른 것 (더 밝고 진한 값들보다 이쪽이 나았다)


class Printer(Protocol):
    def available(self) -> bool: ...

    def print(self, image: Image.Image, copies: int, *, token: str = "", url: str | None = None) -> None: ...


class DummyPrinter:
    def __init__(self, spool: Path, clock: Callable[[], datetime] = datetime.now) -> None:
        self.spool = Path(spool)
        self._clock = clock

    def available(self) -> bool:
        return True

    def print(self, image: Image.Image, copies: int, *, token: str = "", url: str | None = None) -> None:
        self.spool.mkdir(parents=True, exist_ok=True)
        name = f"{self._clock():%Y%m%d-%H%M%S}_{token}_x{copies}.png"
        path = self.spool / name
        tmp = path.with_name(path.name + ".tmp")
        image.save(tmp, format="PNG")
        os.replace(tmp, path)  # 반쯤 쓴 파일을 남기지 않는다
        log.info("[printer] 더미 인쇄 %d매 → %s", copies, self.spool)  # 파일 이름(토큰)은 로그에 남기지 않는다


# ---- 포트 고르기 ----

def find_port(setting: str, ports=None) -> str | None:
    """PRINTER_PORT 값으로 포트를 고른다. "" = USB 번호로 자동, "COMx" = 그 포트, off · dummy = 없음."""
    s = (setting or "").strip()
    if s.lower() in ("off", "dummy"):
        return None
    if s:
        return s.upper() if s.lower().startswith("com") else s
    if ports is None:
        try:
            from serial.tools import list_ports
        except ImportError:
            return None
        ports = list_ports.comports()
    for p in ports:
        if getattr(p, "vid", None) == PRINTER_VID and getattr(p, "pid", None) == PRINTER_PID:
            return p.device
    return None


# ---- 영수증 이미지 (모드 "1", 가로 576) ----

def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except OSError:
        return ImageFont.load_default(size)


def photo_dots(photo: Image.Image, gamma: float = PHOTO_GAMMA, brightness: float = PHOTO_BRIGHTNESS,
               contrast: float = PHOTO_CONTRAST) -> Image.Image:
    """사진을 가로 576 흑백 점묘로: 흑백 → 대비 자동 맞춤 → 감마 → 밝기 → 대비 → 줄이기 → 점묘."""
    g = ImageOps.autocontrast(ImageOps.grayscale(photo.convert("RGB")), cutoff=1)
    if gamma != 1.0:
        g = g.point([round(255 * (v / 255) ** gamma) for v in range(256)])
    if brightness != 1.0:
        g = ImageEnhance.Brightness(g).enhance(brightness)
    if contrast != 1.0:
        g = ImageEnhance.Contrast(g).enhance(contrast)
    h = max(1, round(g.height * PAPER_W / g.width))
    return g.resize((PAPER_W, h), Image.LANCZOS).convert("1")  # 기본 Floyd–Steinberg


def _qr(url: str, size: int) -> Image.Image:
    qr = qrcode.QRCode(border=1, box_size=8, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").get_image().convert("L")
    return img.resize((size, size), Image.NEAREST)


def _footer(url: str | None, when: datetime) -> Image.Image:
    date = f"{when:%Y.%m.%d}"
    if url:
        qs, pad = 200, 24
        im = Image.new("L", (PAPER_W, qs + 2 * pad), 255)
        im.paste(_qr(url, qs), (pad, pad))
        d = ImageDraw.Draw(im)
        x = pad + qs + 24
        d.text((x, pad + 18), "컬러 원본은", font=_font(30), fill=0)
        d.text((x, pad + 56), "QR 로 받으세요", font=_font(30), fill=0)
        d.text((x, pad + 118), SERVICE_NAME, font=_font(34), fill=0)
        d.text((x, pad + 162), date, font=_font(26), fill=0)
    else:
        im = Image.new("L", (PAPER_W, 120), 255)
        d = ImageDraw.Draw(im)
        d.text((PAPER_W // 2, 40), SERVICE_NAME, font=_font(34), fill=0, anchor="mm")
        d.text((PAPER_W // 2, 86), date, font=_font(26), fill=0, anchor="mm")
    return im.convert("1", dither=Image.NONE)


def _stack(*parts: Image.Image) -> Image.Image:
    sheet = Image.new("1", (PAPER_W, sum(p.height for p in parts)), 1)
    y = 0
    for p in parts:
        sheet.paste(p, (0, y))
        y += p.height
    return sheet


def receipt_image(photo: Image.Image, url: str | None, when: datetime) -> Image.Image:
    """사진(점묘) + 아래 칸 (QR · '컬러 원본은 QR 로' · 호두네사진관 · 날짜, 주소가 없으면 이름 · 날짜만)."""
    gap = Image.new("1", (PAPER_W, 12), 1)
    return _stack(photo_dots(photo), gap, _footer(url, when))


def test_image(port: str, when: datetime) -> Image.Image:
    """시험 인쇄 한 장: 제목 · 포트 · 시각 · 회색 띠 (점묘가 고르게 나오는지 본다)."""
    im = Image.new("L", (PAPER_W, 300), 255)
    d = ImageDraw.Draw(im)
    d.text((PAPER_W // 2, 40), f"{SERVICE_NAME} 시험 인쇄", font=_font(34), fill=0, anchor="mm")
    d.text((PAPER_W // 2, 90), f"포트 {port}  ·  {when:%Y.%m.%d %H:%M}", font=_font(24), fill=0, anchor="mm")
    for x in range(PAPER_W):  # 흰색 → 검정 띠
        d.line([(x, 130), (x, 230)], fill=255 - round(255 * x / (PAPER_W - 1)))
    d.text((PAPER_W // 2, 270), "이 띠가 고르게 이어지면 정상입니다", font=_font(22), fill=0, anchor="mm")
    return im.convert("1")


# ---- ESC/POS ----

def escpos_bytes(sheet: Image.Image) -> bytes:
    """한 장 전체: 초기화 → GS v 0 래스터를 BAND 줄씩 → 4줄 넘김 → 자르기."""
    return b"".join(escpos_chunks(sheet))


def escpos_chunks(sheet: Image.Image) -> list[bytes]:
    """escpos_bytes 를 보낼 단위로 나눈 것 (중간에 flush · 잠깐 쉬려고)."""
    raster = ImageChops.invert(sheet.convert("L")).convert("1").tobytes()  # 1 = 검은 점
    wb = PAPER_W // 8
    out = [b"\x1b@"]
    for y in range(0, sheet.height, BAND):
        n = min(BAND, sheet.height - y)
        out.append(b"\x1dv0\x00" + bytes([wb & 255, wb >> 8, n & 255, n >> 8]) + raster[y * wb:(y + n) * wb])
    out.append(b"\x1bd\x04")
    out.append(b"\x1dVB\x00")
    return out


# ---- 인쇄 스레드 ----

class ReceiptPrinter:
    """영수증 프린터. print() 는 큐에 넣고 바로 돌아오고, 인쇄 스레드 하나가 순서대로 보낸다.

    포트는 장마다 다시 찾는다 (꽂았다 뺐다 해도 된다). 실패는 로그 한 줄만 남기고 다음 장으로 — 예외를 밖에 내지 않는다.
    로그에는 토큰 · 주소를 남기지 않는다.
    """

    PORTS_TTL = 1.0  # 포트 목록을 이만큼 다시 쓴다 (관리자 패널이 매 프레임 상태를 그린다)

    def __init__(self, setting: str, opener: Callable[[str], object] | None = None, ports=None,
                 clock: Callable[[], datetime] = datetime.now, start: bool = True,
                 pause: float = 0.05, retry_wait: float = 0.5,
                 lister: Callable[[], list] | None = None, monotonic: Callable[[], float] | None = None) -> None:
        import queue
        import threading
        import time

        self.setting = (setting or "").strip()
        self._opener = opener or _serial_open
        self._ports = ports          # 시험용 고정 목록 (있으면 lister 보다 먼저)
        self._lister = lister
        self._monotonic = monotonic or time.monotonic
        self._cache: tuple[float, list | None] | None = None
        self._clock = clock
        self._pause = pause
        self._retry_wait = retry_wait
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._pending = 0
        self._thread = None
        if start:
            self._thread = threading.Thread(target=self._run, name="printer", daemon=True)
            self._thread.start()

    # ---- 상태 ----

    def off(self) -> bool:
        return self.setting.lower() == "off"

    def _port_list(self) -> list | None:
        """지금 꽂힌 시리얼 포트 목록 (1초 캐시). 목록을 못 읽으면 None."""
        if self._ports is not None:
            return self._ports
        now = self._monotonic()
        if self._cache is not None and now - self._cache[0] < self.PORTS_TTL:
            return self._cache[1]
        try:
            if self._lister is not None:
                ports = list(self._lister())
            else:
                from serial.tools import list_ports
                ports = list(list_ports.comports())
        except Exception:
            ports = None
        self._cache = (now, ports)
        return ports

    def port(self) -> str | None:
        """쓸 포트. 직접 적은 포트도 지금 꽂혀 있을 때만 (목록을 못 읽으면 적은 대로 믿는다)."""
        if self.setting.lower() in ("off", "dummy"):
            return None
        ports = self._port_list()
        if ports is None:  # 목록을 못 읽으면 적은 포트는 믿고, 자동은 포기한다
            return find_port(self.setting, []) if self.setting else None
        found = find_port(self.setting, ports)
        if found is not None and self.setting:
            return {str(getattr(p, "device", "")).upper(): p.device for p in ports}.get(found.upper())
        return found

    def available(self) -> bool:
        return self.port() is not None

    def pending(self) -> int:
        """아직 다 나오지 않은 장 수 (지금 보내는 장 포함)."""
        with self._lock:
            return self._pending

    # ---- 요청 ----

    def print(self, image: Image.Image, copies: int, *, token: str = "", url: str | None = None) -> None:
        n = max(1, int(copies))
        self._put(("photo", image.copy(), url, self._clock()), n)

    def print_test(self) -> bool:
        """시험 인쇄 한 장을 큐에 넣는다. 프린터를 못 찾으면 False."""
        port = self.port()
        if port is None:
            return False
        self._put(("test", port, self._clock()), 1)
        return True

    def close(self, timeout: float | None = None) -> None:
        """큐에 남은 것을 다 보내고 스레드를 끝낸다."""
        if self._thread is not None:
            self._q.put(None)
            self._thread.join(timeout)
            self._thread = None

    def _put(self, job, n: int) -> None:
        with self._lock:
            self._pending += n
        self._q.put((job, n))

    # ---- 스레드 ----

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            job, n = item
            try:
                sheet = (receipt_image(job[1], job[2], job[3]) if job[0] == "photo"
                         else test_image(job[1], job[2]))
            except Exception as exc:  # 이미지를 못 만들면 그 작업만 버린다
                log.warning("[printer] 영수증 이미지를 만들지 못했습니다: %s", type(exc).__name__)
                sheet = None
            for _ in range(n):
                if sheet is not None:
                    self._send(sheet)
                with self._lock:
                    self._pending -= 1

    def _send(self, sheet: Image.Image) -> None:
        import time

        port = self.port()
        if port is None:
            log.warning("[printer] 프린터를 찾지 못해 인쇄하지 못했습니다 (PRINTER_PORT=%r)", self.setting)
            return
        try:
            s = None
            for attempt in range(3):  # 포트가 가끔 첫 시도에 안 열린다
                try:
                    s = self._opener(port)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(self._retry_wait)
            try:
                for chunk in escpos_chunks(sheet):
                    s.write(chunk)
                    s.flush()
                    if self._pause:
                        time.sleep(self._pause)
            finally:
                s.close()
            log.info("[printer] 한 장 인쇄 (%s)", port)
        except Exception as exc:
            log.warning("[printer] 인쇄하지 못했습니다 (%s): %s %s", port, type(exc).__name__, exc)


def _serial_open(port: str):
    import serial

    return serial.Serial(port, BAUD, timeout=2, write_timeout=10)


def make_printer(cfg, spool: Path):
    """cfg.printer_port 로 프린터를 고른다: dummy → 파일로 쌓기, 그 밖 → 영수증 프린터 (off 면 늘 사용 불가)."""
    setting = (getattr(cfg, "printer_port", "dummy") or "").strip()
    if setting.lower() == "dummy":
        return DummyPrinter(spool)
    return ReceiptPrinter(setting)
