"""업로드 outbox 테스트."""

from __future__ import annotations

import re
import threading
import time

import pytest

from walnut.api import BoothApi
from walnut.device import Device
from walnut.uploader import Uploader, new_token

TOKEN = "abcdefghijklmnop"


def _api(url: str) -> BoothApi:
    return BoothApi(Device(url, "tok", b"k" * 32, 1, "행사"))


def _jpg(tmp_path, name="src.jpg"):
    p = tmp_path / name
    p.write_bytes(b"\xff\xd8jpegdata\xff\xd9")
    return p


@pytest.fixture
def up(tmp_path, fake_server):
    made = []

    def make(api="default", on_revoked=lambda: None, **kw):
        a = _api(fake_server.url) if api == "default" else api
        u = Uploader(tmp_path / "outbox", a, on_revoked, backoff_base=0.05, backoff_max=0.2, **kw)
        made.append(u)
        return u

    yield make
    for u in made:
        u.stop()


def test_token_format():
    assert re.fullmatch(r"[A-Za-z0-9_-]{16}", new_token())


def test_upload_success_removes_file(tmp_path, fake_server, up):
    fake_server.route("POST", "/api/booth/photos", lambda r: (201, {}, None))
    u = up()
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    assert u.wait_idle(5)
    assert u.state(TOKEN) == 1
    assert not (tmp_path / "outbox" / f"{TOKEN}.jpg").exists()
    req = fake_server.requests[0]
    assert req.headers["Authorization"] == "Bearer tok"
    assert TOKEN.encode() in req.body


def test_409_counts_as_done(tmp_path, fake_server, up):
    fake_server.route("POST", "/api/booth/photos", lambda r: (409, {}, {"error": "exists"}))
    u = up()
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    assert u.wait_idle(5)
    assert u.state(TOKEN) == 1
    assert u.pending() == 0


def test_server_down_keeps_file_and_retries(tmp_path, fake_server, up):
    n = {"c": 0}

    def h(r):
        n["c"] += 1
        return (503, {"Retry-After": "0"}, {"error": "retry_later"}) if n["c"] <= 2 else (201, {}, None)

    fake_server.route("POST", "/api/booth/photos", h)
    u = up()
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    seen = set()
    end = time.monotonic() + 5
    while time.monotonic() < end and u.state(TOKEN) != 1:
        seen.add(u.state(TOKEN))
        time.sleep(0.005)
    assert u.wait_idle(5)
    assert 2 in seen
    assert u.state(TOKEN) == 1
    assert n["c"] == 3


def test_rejected_moves_to_failed(tmp_path, fake_server, up):
    fake_server.route("POST", "/api/booth/photos", lambda r: (400, {}, {"error": "validation"}))
    u = up()
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    assert u.wait_idle(5)
    assert (tmp_path / "outbox" / "failed" / f"{TOKEN}.jpg").exists()
    assert not (tmp_path / "outbox" / f"{TOKEN}.jpg").exists()
    assert u.pending() == 0
    assert u.last_error


def test_existing_outbox_uploaded_on_start(tmp_path, fake_server, up):
    fake_server.route("POST", "/api/booth/photos", lambda r: (201, {}, None))
    box = tmp_path / "outbox"
    box.mkdir()
    (box / f"{TOKEN}.jpg").write_bytes(b"x")
    u = up()
    assert u.state(TOKEN) == 0
    assert u.pending() == 1
    u.start()
    assert u.wait_idle(5)
    assert u.state(TOKEN) == 1
    assert len(fake_server.requests) == 1


def test_revoked_stops_and_orphan_all_moves(tmp_path, fake_server, up):
    fake_server.route("POST", "/api/booth/photos", lambda r: (401, {}, {"error": "device_revoked"}))
    calls = []
    u = up(on_revoked=lambda: calls.append(1))
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    end = time.monotonic() + 5
    while not calls and time.monotonic() < end:
        time.sleep(0.01)
    time.sleep(0.3)
    assert calls == [1]
    assert len(fake_server.requests) == 1  # 멈췄다
    assert (tmp_path / "outbox" / f"{TOKEN}.jpg").exists()
    assert u.orphan_all() == 1
    assert (tmp_path / "outbox" / "orphaned" / f"{TOKEN}.jpg").exists()
    assert u.pending() == 0


def test_set_api_after_revoke_resumes(tmp_path, fake_server, up):
    mode = {"revoked": True}
    fake_server.route("POST", "/api/booth/photos",
                      lambda r: (401, {}, {"error": "device_revoked"}) if mode["revoked"] else (201, {}, None))
    calls = []
    u = up(on_revoked=lambda: calls.append(1))
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    end = time.monotonic() + 5
    while not calls and time.monotonic() < end:
        time.sleep(0.01)
    mode["revoked"] = False
    u.set_api(_api(fake_server.url))
    assert u.wait_idle(5)
    assert u.state(TOKEN) == 1


def test_no_server_state_3(tmp_path):
    u = Uploader(tmp_path / "outbox", None, lambda: None)
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    assert u.state(TOKEN) == 3
    assert u.state("nope") == 3
    assert u.pending() == 0
    u.stop()


def test_unknown_token_state_3(tmp_path, fake_server, up):
    assert up().state("never") == 3


def test_oldest_first(tmp_path, fake_server, up):
    import os
    fake_server.route("POST", "/api/booth/photos", lambda r: (201, {}, None))
    box = tmp_path / "outbox"
    box.mkdir()
    for i, name in enumerate(["bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa", "cccccccccccccccc"]):
        p = box / f"{name}.jpg"
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
    u = up()
    u.start()
    assert u.wait_idle(5)
    order = [re.search(rb'name="token"\r\n\r\n(\w+)', r.body).group(1).decode() for r in fake_server.requests]
    assert order == ["bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa", "cccccccccccccccc"]


def test_unexpected_exception_does_not_kill_thread(tmp_path, fake_server, up):
    fake_server.route("POST", "/api/booth/photos", lambda r: (201, {}, None))
    api = _api(fake_server.url)
    real = api.upload_photo
    n = {"c": 0}

    def flaky(token, data):
        n["c"] += 1
        if n["c"] == 1:
            raise PermissionError("잠김")
        return real(token, data)

    api.upload_photo = flaky
    u = up(api=api)
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    assert u.wait_idle(5)
    assert u.state(TOKEN) == 1
    assert n["c"] == 2


def test_raising_on_revoked_does_not_kill_thread(tmp_path, fake_server, up):
    mode = {"revoked": True}
    fake_server.route("POST", "/api/booth/photos",
                      lambda r: (401, {}, {"error": "device_revoked"}) if mode["revoked"] else (201, {}, None))

    def boom():
        raise RuntimeError("콜백 오류")

    u = up(on_revoked=boom)
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    end = time.monotonic() + 5
    while not fake_server.requests and time.monotonic() < end:
        time.sleep(0.01)
    time.sleep(0.2)
    mode["revoked"] = False
    u.set_api(_api(fake_server.url))
    assert u.wait_idle(5)
    assert u.state(TOKEN) == 1


def test_enqueue_sets_state_before_file_appears(tmp_path, fake_server, up, monkeypatch):
    u = up()
    seen = []
    import walnut.uploader as m
    real = m.os.replace

    def spy(a, b):
        seen.append(u._state.get(TOKEN))
        return real(a, b)

    monkeypatch.setattr(m.os, "replace", spy)
    u.enqueue(TOKEN, _jpg(tmp_path))
    assert seen == [0]


def test_stale_api_revoked_after_set_api_is_ignored(tmp_path, fake_server, up):
    from walnut.api import Revoked
    fake_server.route("POST", "/api/booth/photos", lambda r: (201, {}, None))
    old = _api(fake_server.url)
    inside, release = threading.Event(), threading.Event()
    u_holder = {}

    def stale(token, data):
        inside.set()
        release.wait(5)
        raise Revoked()

    old.upload_photo = stale
    calls = []
    u = up(api=old, on_revoked=lambda: calls.append(1))
    u.start()
    u.enqueue(TOKEN, _jpg(tmp_path))
    assert inside.wait(5)
    u.set_api(_api(fake_server.url))
    release.set()
    assert u.wait_idle(5)
    assert calls == []
    assert u.state(TOKEN) == 1
