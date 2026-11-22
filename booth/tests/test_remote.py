from walnut.remote import Remote, fmt_line


def test_fmt_line_strips_and_truncates():
    assert fmt_line("L", "R", 0, 3, "기본|4컷\n") == "L|R|0|3|기본4컷"
    long = "가" * 30  # 90바이트
    assert fmt_line("I", long) == "I|" + "가" * 15  # 45바이트 (16자는 48 > 47)
    assert fmt_line("I", "a" * 46 + "가") == "I|" + "a" * 46
    assert fmt_line("I", "a" * 47) == "I|" + "a" * 47
    assert fmt_line("W") == "W"
    assert fmt_line("a\r\nb") == "ab"


def test_worst_case_pick_line_fits():
    # n=12, extra=6 → 18장, 고른 순서 0..11 + 안 고른 6장
    order = ",".join([str(i) for i in range(12)] + ["-"] * 6)
    line = fmt_line("G", order, 18, 12)
    assert line.split("|")[1] == order  # 47바이트 자르기에 걸리지 않는다
    assert len(order.encode()) <= 47


def test_remote_off_does_nothing():
    r = Remote("off")
    r.set_title("제목")
    r.set("I|x")
    assert r.connected is False
    r.stop()


class FakeSerial:
    def __init__(self):
        self.written: list[bytes] = []
        self.closed = False
        self.fail = False
        self.drained = 0

    def write(self, data: bytes):
        if self.fail:
            raise OSError("끊김")
        self.written.append(data)

    def close(self):
        self.closed = True

    def reset_input_buffer(self):
        self.drained += 1

    def lines(self):
        return [w.decode("utf-8") for w in self.written]


def make(port="COM9"):
    t = [0.0]
    sers: list[FakeSerial] = []

    def factory(name):
        s = FakeSerial()
        sers.append(s)
        return s

    r = Remote(port, clock=lambda: t[0], serial_factory=factory, start=False)
    return r, t, sers


def test_hello_every_10s():
    r, t, sers = make()
    r.set_title("가을 행사")
    r.set("I|가을 행사")
    r._tick()
    assert r.connected
    assert sers[0].lines() == ["H|1|가을 행사\n", "I|가을 행사\n"]
    for sec in range(1, 10):
        t[0] = float(sec)
        r._tick()
    hello = [x for x in sers[0].lines() if x.startswith("H|")]
    assert len(hello) == 1
    t[0] = 10.0
    r._tick()
    assert sers[0].lines()[-2:] == ["H|1|가을 행사\n", "I|가을 행사\n"]


def test_set_sends_on_change_and_resends_every_second():
    r, t, sers = make()
    r.set("I|a")
    r._tick()
    n = len(sers[0].written)
    t[0] = 0.5
    r._tick()
    assert len(sers[0].written) == n  # 그대로, 1초 안
    t[0] = 1.0
    r._tick()
    assert sers[0].lines()[-1] == "I|a\n" and len(sers[0].written) == n + 1
    t[0] = 1.1
    r.set("V|0|9|10")
    r._tick()
    assert sers[0].lines()[-1] == "V|0|9|10\n"


def test_reconnects_after_serial_error():
    r, t, sers = make()
    r.set("I|a")
    r._tick()
    sers[0].fail = True
    t[0] = 1.0
    r._tick()
    assert not r.connected and sers[0].closed
    t[0] = 3.5
    r._tick()
    assert r.connected and len(sers) == 2
    assert sers[1].lines()[0].startswith("H|1|")  # 재연결 직후 인사부터


def test_open_failure_keeps_disconnected():
    def bad(name):
        raise OSError("없음")

    r = Remote("COM9", clock=lambda: 0.0, serial_factory=bad, start=False)
    r._tick()
    assert not r.connected


def test_tick_drains_remote_key_log():
    # 리모컨은 키마다 시리얼 로그를 찍는다. 비우지 않으면 PC 쪽 수신 버퍼가 차서 리모컨 쓰기가 막힐 수 있다
    r, t, sers = make()
    r._tick()
    t[0] += 1.0
    r._tick()
    assert sers[0].drained == 2
