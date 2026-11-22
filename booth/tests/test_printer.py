from datetime import datetime
from types import SimpleNamespace

from PIL import Image

from walnut.printer import DummyPrinter, escpos_bytes, find_port, receipt_image, test_image as make_test_image


def test_dummy_printer_spools(tmp_path):
    p = DummyPrinter(tmp_path / "print_spool", clock=lambda: datetime(2026, 10, 15, 14, 22, 33))
    assert p.available()
    p.print(Image.new("RGB", (20, 30), "red"), 2, token="tok")
    f = tmp_path / "print_spool" / "20261015-142233_tok_x2.png"
    assert f.exists()
    assert Image.open(f).size == (20, 30)
    assert [x.name for x in (tmp_path / "print_spool").iterdir()] == [f.name]


# ---- 영수증 프린터 (CPP-3000) ----

PORTS = [SimpleNamespace(device="COM3", vid=0x2E8A, pid=0x000A),   # 리모컨 (RP2040)
         SimpleNamespace(device="COM18", vid=0x1CBE, pid=0x0002)]  # 영수증 프린터


def test_choose_port_rules():
    assert find_port("", PORTS) == "COM18"
    assert find_port(" com5 ", PORTS) == "COM5"
    assert find_port("OFF", PORTS) is None
    assert find_port("dummy", PORTS) is None
    assert find_port("", PORTS[:1]) is None          # 리모컨만 있으면 프린터로 착각하지 않는다


def test_receipt_image_width_and_ratio():
    for size in [(600, 1800), (1800, 1200)]:
        im = receipt_image(Image.new("RGB", size, "gray"), "https://x/p/abc", datetime(2026, 11, 21, 13, 5))
        assert im.mode == "1" and im.width == 576
        assert im.height > 576 * size[1] / size[0]   # 사진 아래 칸이 더 붙는다


def test_receipt_without_url_has_no_qr_block():
    photo = Image.new("RGB", (600, 900), "white")
    with_qr = receipt_image(photo, "https://x/p/abc", datetime(2026, 11, 21))
    no_qr = receipt_image(photo, None, datetime(2026, 11, 21))
    assert no_qr.mode == "1" and no_qr.width == 576
    assert no_qr.height < with_qr.height


def test_test_image_shape():
    im = make_test_image("COM18", datetime(2026, 11, 20, 21, 0))
    assert im.mode == "1" and im.width == 576 and im.height > 100


def test_escpos_bytes_layout():
    sheet = Image.new("1", (576, 130), 1)            # 흰 종이
    b = escpos_bytes(sheet)
    assert b.startswith(b"\x1b@")
    assert b.count(b"\x1dv0\x00") == 3                # 64 + 64 + 2 줄
    assert b"\x1dv0\x00" + bytes([72, 0, 64, 0]) in b
    assert b"\x1dv0\x00" + bytes([72, 0, 2, 0]) in b
    assert b.endswith(b"\x1bd\x04\x1dVB\x00")
    assert len(b) == 2 + 3 * 8 + 130 * 72 + 3 + 4
    assert set(b[10:10 + 64 * 72]) == {0}            # 흰 점은 0, 검은 점이 1


def test_escpos_black_dot_is_one():
    sheet = Image.new("1", (576, 1), 1)
    sheet.putpixel((0, 0), 0)                        # 맨 왼쪽 점 하나만 검정
    b = escpos_bytes(sheet)
    raster = b[2 + 8:2 + 8 + 72]
    assert raster[0] == 0x80 and set(raster[1:]) == {0}


# ---- ReceiptPrinter (인쇄 스레드) ----

import logging  # noqa: E402

from walnut.config import load  # noqa: E402
from walnut.printer import ReceiptPrinter, make_printer  # noqa: E402


COM9 = [SimpleNamespace(device="COM9", vid=0x1234, pid=0x0001)]  # 직접 적은 포트도 꽂혀 있어야 쓴다


class FakeSerial:
    """opener 대신 쓰는 가짜 포트. 받은 바이트와 연 포트 이름을 모은다."""

    def __init__(self):
        self.data = b""
        self.opened = []

    def open(self, port):
        self.opened.append(port)
        return self

    def write(self, b):
        self.data += b

    def flush(self):
        pass

    def close(self):
        pass


def test_jobs_print_in_order():
    fake = FakeSerial()
    p = ReceiptPrinter("COM9", ports=COM9, opener=fake.open, pause=0)
    p.print(Image.new("RGB", (600, 900)), 2, url="https://x/p/a")
    p.print(Image.new("RGB", (600, 900)), 1)
    p.close()                                       # 큐를 다 비우고 스레드를 끝낸다
    assert fake.data.count(b"\x1dVB\x00") == 3
    assert fake.opened == ["COM9"] * 3


def test_print_returns_immediately_and_counts_pending():
    import threading
    gate = threading.Event()

    def slow_open(port):
        gate.wait(2)
        return FakeSerial()

    p = ReceiptPrinter("COM9", ports=COM9, opener=slow_open, pause=0)
    p.print(Image.new("RGB", (100, 100)), 3)        # 막히지 않고 돌아온다
    assert p.pending() >= 1
    gate.set()
    p.close()
    assert p.pending() == 0


def test_send_failure_is_logged_not_raised(caplog):
    def boom(port):
        raise OSError("포트를 열 수 없음")

    p = ReceiptPrinter("COM9", ports=COM9, opener=boom, pause=0, retry_wait=0)
    with caplog.at_level(logging.WARNING):
        p.print(Image.new("RGB", (100, 100)), 1, token="secret", url="https://x/p/secret")
        p.close()
    assert "인쇄하지 못했" in caplog.text
    assert "secret" not in caplog.text


def test_open_retries_three_times():
    tries = []
    fake = FakeSerial()

    def flaky(port):
        tries.append(port)
        if len(tries) < 3:
            raise OSError("처음엔 안 열림")
        return fake

    p = ReceiptPrinter("COM9", ports=COM9, opener=flaky, pause=0, retry_wait=0)
    p.print(Image.new("RGB", (100, 100)), 1)
    p.close()
    assert len(tries) == 3 and fake.data.endswith(b"\x1dVB\x00")


def test_off_and_missing_port_unavailable():
    assert not ReceiptPrinter("off", start=False).available()
    assert not ReceiptPrinter("", ports=[], start=False).available()
    p = ReceiptPrinter("", ports=PORTS, start=False)
    assert p.available() and p.port() == "COM18"


def test_print_test_without_port_returns_false():
    assert ReceiptPrinter("", ports=[], start=False).print_test() is False


def test_make_printer_kinds(tmp_path):
    cfg = load({"PRINTER_PORT": "dummy"}, root=tmp_path)
    assert isinstance(make_printer(cfg, tmp_path / "spool"), DummyPrinter)
    cfg = load({"PRINTER_PORT": "off"}, root=tmp_path)
    p = make_printer(cfg, tmp_path / "spool")
    assert isinstance(p, ReceiptPrinter) and not p.available()
    p.close()


def test_load_printer_port(tmp_path):
    assert load({"PRINTER_PORT": " COM5 "}, root=tmp_path).printer_port == "COM5"
    assert load({}, root=tmp_path).printer_port == ""


def test_typed_port_must_exist_to_be_available():
    assert not ReceiptPrinter("COM5", ports=PORTS, start=False).available()   # 꽂혀 있지 않다
    p = ReceiptPrinter("com18", ports=PORTS, start=False)
    assert p.available() and p.port() == "COM18"


def test_port_list_is_cached_for_a_second():
    calls = []
    now = [100.0]

    def lister():
        calls.append(1)
        return PORTS

    p = ReceiptPrinter("", lister=lister, monotonic=lambda: now[0], start=False)
    assert p.port() == "COM18" and p.port() == "COM18"
    assert len(calls) == 1                      # 패널이 매 프레임 불러도 목록은 한 번
    now[0] += 1.5
    p.port()
    assert len(calls) == 2


def test_photo_tone_settings_lighten_midtones():
    from walnut.printer import photo_dots
    gray = Image.new("RGB", (576, 200), (110, 110, 110))         # 중간보다 어두운 회색
    white = lambda im: im.convert("L").histogram()[255] / (im.width * im.height)  # noqa: E731
    flat = photo_dots(gray, gamma=1.0, brightness=1.0, contrast=1.0)
    light = photo_dots(gray, gamma=0.6, brightness=1.15, contrast=1.0)
    assert white(light) > white(flat) + 0.15


def test_tune_sheet_has_one_band_per_setting():
    from tools.print_tune import BAND_H, tune_sheet
    settings = [(1.0, 1.0, 1.0), (0.7, 1.1, 1.0), (0.5, 1.2, 1.1)]
    im = tune_sheet(Image.new("RGB", (1200, 1800), "gray"), settings)
    assert im.mode == "1" and im.width == 576
    assert im.height >= len(settings) * BAND_H
