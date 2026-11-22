"""기기 저장, 부스 API 클라이언트 테스트."""

from __future__ import annotations

import base64
import hashlib
import json
import socket

import pytest

from walnut.api import BoothApi, NotPublished, Rejected, Revoked, Unreachable, pair
from walnut.device import Device, DeviceStore


def _device(url: str) -> Device:
    return Device(url, "tok", b"k" * 32, 7, "축제")


def test_pair_saves_device(fake_server, tmp_path):
    fake_server.route("POST", "/api/booth/pair", lambda r: (200, {}, {
        "device_token": "t" * 43,
        "bundle_key": base64.urlsafe_b64encode(b"k" * 32).decode(),
        "event": {"id": 7, "name": "축제"}}))
    d = pair(fake_server.url, "12345678", "0.1.0")
    assert d.bundle_key == b"k" * 32 and d.event_id == 7 and d.token == "t" * 43
    assert json.loads(fake_server.requests[0].body) == {"code": "12345678", "app_version": "0.1.0"}
    store = DeviceStore(tmp_path / "device.json")
    store.save(d)
    assert store.load() == d
    store.clear()
    assert store.load() is None


def test_pair_unpadded_key(fake_server):
    key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    fake_server.route("POST", "/api/booth/pair", lambda r: (200, {}, {
        "device_token": "t", "bundle_key": key, "event": {"id": 1, "name": "x"}}))
    assert pair(fake_server.url, "1", "0.1.0").bundle_key == b"k" * 32


def test_pair_bad_code(fake_server):
    fake_server.route("POST", "/api/booth/pair", lambda r: (400, {}, {"error": "invalid_code"}))
    with pytest.raises(Rejected) as e:
        pair(fake_server.url, "0", "0.1.0")
    assert e.value.status == 400 and e.value.code == "invalid_code"


def test_pair_rate_limited_is_unreachable(fake_server):
    fake_server.route("POST", "/api/booth/pair", lambda r: (429, {}, {"error": "rate_limited"}))
    with pytest.raises(Unreachable):
        pair(fake_server.url, "0", "0.1.0")


def test_device_store_corrupt_returns_none(tmp_path):
    p = tmp_path / "device.json"
    p.write_text("{", encoding="utf-8")
    assert DeviceStore(p).load() is None
    p.write_text("{}", encoding="utf-8")
    assert DeviceStore(p).load() is None
    assert DeviceStore(tmp_path / "none.json").load() is None


def test_device_store_atomic_no_tmp_left(tmp_path):
    store = DeviceStore(tmp_path / "device.json")
    store.save(_device("http://x"))
    assert [p.name for p in tmp_path.iterdir()] == ["device.json"]


def test_bundle_304_and_etag_sent(fake_server):
    fake_server.route("GET", "/api/booth/bundle", lambda r: (304, {}, None))
    api = BoothApi(_device(fake_server.url))
    assert api.get_bundle('"v3"') is None
    assert fake_server.requests[0].headers["If-None-Match"] == '"v3"'


def test_bundle_200_returns_raw_bytes_and_etag(fake_server):
    fake_server.route("GET", "/api/booth/bundle", lambda r: (200, {"ETag": '"v4"'}, b'{"version": 4}'))
    api = BoothApi(_device(fake_server.url))
    assert api.get_bundle(None) == (b'{"version": 4}', '"v4"')
    assert "If-None-Match" not in fake_server.requests[0].headers


def test_status_mapping(fake_server):
    api = BoothApi(_device(fake_server.url))
    fake_server.route("GET", "/api/booth/bundle", lambda r: (401, {}, {"error": "device_revoked"}))
    with pytest.raises(Revoked):
        api.get_bundle(None)
    fake_server.route("GET", "/api/booth/bundle", lambda r: (404, {}, {"error": "not_published"}))
    with pytest.raises(NotPublished):
        api.get_bundle(None)
    fake_server.route("GET", "/api/booth/bundle", lambda r: (503, {"Retry-After": "30"}, {"error": "x"}))
    with pytest.raises(Unreachable) as e:
        api.get_bundle(None)
    assert e.value.retry_after == 30.0
    fake_server.route("GET", "/api/booth/bundle", lambda r: (500, {}, b"boom"))
    with pytest.raises(Unreachable) as e:
        api.get_bundle(None)
    assert e.value.retry_after is None
    fake_server.route("GET", "/api/booth/bundle", lambda r: (503, {"Retry-After": "soon"}, b""))
    with pytest.raises(Unreachable) as e:
        api.get_bundle(None)
    assert e.value.retry_after is None
    fake_server.route("GET", "/api/booth/bundle", lambda r: (403, {}, {"error": "forbidden"}))
    with pytest.raises(Rejected) as e:
        api.get_bundle(None)
    assert (e.value.status, e.value.code) == (403, "forbidden")
    fake_server.route("GET", "/api/booth/bundle", lambda r: (400, {}, b"not json"))
    with pytest.raises(Rejected) as e:
        api.get_bundle(None)
    assert (e.value.status, e.value.code) == (400, "")


def test_heartbeat_401_is_revoked(fake_server):
    fake_server.route("POST", "/api/booth/heartbeat", lambda r: (401, {}, {"error": "device_revoked"}))
    with pytest.raises(Revoked):
        BoothApi(_device(fake_server.url)).heartbeat({"outbox": 0})


def test_heartbeat_sends_json(fake_server):
    fake_server.route("POST", "/api/booth/heartbeat", lambda r: (204, {}, None))
    BoothApi(_device(fake_server.url)).heartbeat({"outbox": 2})
    assert json.loads(fake_server.requests[0].body) == {"outbox": 2}


def test_connection_refused_is_unreachable():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(Unreachable):
        BoothApi(_device(f"http://127.0.0.1:{port}")).heartbeat({})


def test_asset_ok_and_sha_mismatch(fake_server):
    data = b"png-bytes"
    sha = hashlib.sha256(data).hexdigest()
    fake_server.route("GET", f"/api/booth/assets/{sha}", lambda r: (200, {}, data))
    api = BoothApi(_device(fake_server.url))
    assert api.get_asset(sha) == data
    bad = "0" * 64
    fake_server.route("GET", f"/api/booth/assets/{bad}", lambda r: (200, {}, data))
    with pytest.raises(Rejected) as e:
        api.get_asset(bad)
    assert (e.value.status, e.value.code) == (0, "sha_mismatch")


def test_upload_multipart(fake_server):
    fake_server.route("POST", "/api/booth/photos", lambda r: (201, {}, {"ok": True}))
    tok = "a" * 16
    BoothApi(_device(fake_server.url)).upload_photo(tok, b"\xff\xd8jpeg")
    req = fake_server.requests[0]
    assert req.headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="token"' in req.body and tok.encode() in req.body
    assert b'name="file"' in req.body and f'filename="{tok}.jpg"'.encode() in req.body
    assert b"image/jpeg" in req.body and b"\xff\xd8jpeg" in req.body


def test_upload_409_is_success_507_retry(fake_server):
    api = BoothApi(_device(fake_server.url))
    fake_server.route("POST", "/api/booth/photos", lambda r: (409, {}, {"error": "exists"}))
    api.upload_photo("a" * 16, b"x")
    fake_server.route("POST", "/api/booth/photos", lambda r: (507, {}, {"error": "quota_exceeded"}))
    with pytest.raises(Unreachable) as e:
        api.upload_photo("a" * 16, b"x")
    assert e.value.retry_after is None
    fake_server.route("POST", "/api/booth/photos", lambda r: (503, {"Retry-After": "30"}, {"error": "retry_later"}))
    with pytest.raises(Unreachable) as e:
        api.upload_photo("a" * 16, b"x")
    assert e.value.retry_after == 30.0
    fake_server.route("POST", "/api/booth/photos", lambda r: (413, {}, {"error": "too_large"}))
    with pytest.raises(Rejected) as e:
        api.upload_photo("a" * 16, b"x")
    assert (e.value.status, e.value.code) == (413, "too_large")


def test_bearer_header_on_every_call(fake_server):
    sha = hashlib.sha256(b"a").hexdigest()
    fake_server.route("GET", "/api/booth/bundle", lambda r: (304, {}, None))
    fake_server.route("GET", f"/api/booth/assets/{sha}", lambda r: (200, {}, b"a"))
    fake_server.route("POST", "/api/booth/heartbeat", lambda r: (204, {}, None))
    fake_server.route("POST", "/api/booth/photos", lambda r: (201, {}, {}))
    api = BoothApi(_device(fake_server.url))
    api.get_bundle(None)
    api.get_asset(sha)
    api.heartbeat({})
    api.upload_photo("a" * 16, b"x")
    assert len(fake_server.requests) == 4
    assert all(r.headers["Authorization"] == "Bearer tok" for r in fake_server.requests)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf"])
def test_retry_after_only_finite_non_negative(fake_server, value):
    api = BoothApi(_device(fake_server.url))
    fake_server.route("GET", "/api/booth/bundle", lambda r: (503, {"Retry-After": value}, b""))
    with pytest.raises(Unreachable) as e:
        api.get_bundle(None)
    assert e.value.retry_after == (0.0 if value == "0" else None)


def test_device_store_fsyncs_before_replace(tmp_path, monkeypatch):
    import os

    calls = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(os, "replace", lambda a, b: (calls.append("replace"), real_replace(a, b))[1])
    DeviceStore(tmp_path / "device.json").save(_device("http://x"))
    assert calls == ["fsync", "replace"]
