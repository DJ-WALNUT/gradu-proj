"""동기화 워커: 실제 FakeServer + BoothApi + BundleStore 로 한 주기씩 돌린다."""

from __future__ import annotations

import hashlib
import json
import time

import pytest

from walnut.api import BoothApi
from walnut.bundle import BundleStore
from walnut.device import Device
from walnut.sync import SyncWorker


class Srv:
    """가짜 서버에 번들·에셋·하트비트 경로를 얹은 도우미."""

    def __init__(self, fake, make_bundle) -> None:
        self.fake = fake
        self.make_bundle = make_bundle
        self.bundle_status = None  # None 이면 정상(200/304), 아니면 (status, headers, body)
        self.asset_status = None
        self.heartbeat_status = (204, {}, None)
        self.raw = b""
        self.version = 0
        self.assets: dict[str, bytes] = {}
        fake.route("GET", "/api/booth/bundle", self._bundle)
        fake.route("POST", "/api/booth/heartbeat", lambda req: self.heartbeat_status)

    def publish(self, version: int, fresh: bool = False, **kw) -> None:
        """fresh=True 면 기기에 아직 없는 새 프레임 에셋을 쓴다 (받기 경로를 타게)."""
        if fresh:
            data = f"frame-v{version}".encode()
            sha = hashlib.sha256(data).hexdigest()
            slots = json.loads(self.make_bundle()[0])["frames"][0]["slots"]
            frames = [{"id": 1, "name": "새 프레임", "asset": sha, "width": 400, "height": 600, "slots": slots}]
            kw["frames"] = frames
            self.raw, _ = self.make_bundle(version=version, **kw)
            self.assets = {sha: data}
        else:
            self.raw, self.assets = self.make_bundle(version=version, **kw)
        self.version = version
        for sha, data in self.assets.items():
            self.fake.route("GET", f"/api/booth/assets/{sha}", self._asset(data))

    def _asset(self, data: bytes):
        return lambda req: self.asset_status or (200, {}, data)

    def _bundle(self, req):
        if self.bundle_status is not None:
            return self.bundle_status
        etag = f'"v{self.version}"'
        if req.headers.get("If-None-Match") == etag:
            return 304, {"ETag": etag}, None
        return 200, {"ETag": etag}, self.raw

    def heartbeats(self) -> list[dict]:
        return [json.loads(r.body) for r in self.fake.requests if r.path == "/api/booth/heartbeat"]

    def bundle_etags(self) -> list[str | None]:
        return [r.headers.get("If-None-Match") for r in self.fake.requests if r.path == "/api/booth/bundle"]


@pytest.fixture
def srv(fake_server, make_bundle):
    return Srv(fake_server, make_bundle)


@pytest.fixture
def w(srv, tmp_path, make_bundle):
    dev = Device(srv.fake.url, "tok", b"k" * 32, 1, "테스트 행사")
    store = BundleStore(tmp_path)
    raw, assets = make_bundle(version=2)
    store.stage(raw, assets.__getitem__)
    store.activate(2)
    srv.publish(2)
    srv.fake.requests.clear()
    revoked: list[int] = []
    w = SyncWorker(BoothApi(dev), store, lambda: {"outbox": 0, "camera_ok": True, "fps": 30.0, "remote_ok": False},
                   None, lambda: revoked.append(1))
    w.revoked_calls = revoked
    w.store = store
    return w


def test_304_no_change(w, srv):
    assert w.run_once() == 30
    assert w.ready_version is None
    assert srv.bundle_etags() == ['"v2"']
    assert w.online and w.last_ok_at is not None and w.last_error == ""


def test_200_stages_and_marks_ready(w, srv):
    srv.publish(3, fresh=True)
    assert w.run_once() == 30
    assert w.ready_version == 3
    assert w.store.current().version == 2
    assert w.store.has_asset(next(iter(srv.assets)))


def test_staged_version_not_redownloaded(w, srv):
    srv.publish(3, fresh=True)
    w.run_once()
    srv.fake.requests.clear()
    w.run_once()
    assert srv.bundle_etags() == ['"v3"']
    assert w.ready_version == 3


def test_ready_cleared_after_activate(w, srv):
    srv.publish(3, fresh=True)
    w.run_once()
    w.store.activate(3)
    w.run_once()
    assert w.ready_version is None


def test_midway_failure_backs_off_then_recovers(w, srv):
    srv.publish(3, fresh=True)
    srv.asset_status = (503, {}, {"error": "retry_later"})
    assert [w.run_once() for _ in range(4)] == [60, 120, 240, 300]
    assert w.run_once() == 300
    assert w.ready_version is None
    assert w.last_error
    srv.asset_status = None
    assert w.run_once() == 30
    assert w.ready_version == 3
    assert w.last_error == ""


def test_sha_mismatch_is_failure(w, srv):
    srv.publish(3, fresh=True)
    sha = next(iter(srv.assets))
    srv.fake.route("GET", f"/api/booth/assets/{sha}", lambda req: (200, {}, b"wrong"))
    assert w.run_once() == 60
    assert w.ready_version is None and w.last_error


def test_bad_bundle_is_failure(w, srv):
    srv.raw = b"not json"
    srv.version = 9
    assert w.run_once() == 60
    assert w.ready_version is None and w.last_error


def test_rejected_is_failure(w, srv):
    srv.bundle_status = (400, {}, {"error": "validation"})
    assert w.run_once() == 60


def test_retry_after_honored(w, srv):
    srv.bundle_status = (503, {"Retry-After": "45"}, {"error": "retry_later"})
    assert w.run_once() == 45
    assert not w.online
    srv.bundle_status = (503, {"Retry-After": "9999"}, None)
    assert w.run_once() == 300


def test_revoked_calls_callback(w, srv):
    srv.bundle_status = (401, {}, {"error": "device_revoked"})
    w.run_once()
    assert w.revoked_calls == [1]
    n = len(srv.fake.requests)
    w.run_once()
    assert w.revoked_calls == [1]
    assert len(srv.fake.requests) == n


def test_revoked_from_heartbeat(w, srv):
    srv.heartbeat_status = (401, {}, {"error": "device_revoked"})
    w.run_once()
    assert w.revoked_calls == [1]
    w.run_once()
    assert w.revoked_calls == [1]


def test_not_published_flag(w, srv):
    srv.bundle_status = (404, {}, {"error": "not_published"})
    assert w.run_once() == 30
    assert w.not_published and w.online
    srv.bundle_status = None
    w.run_once()
    assert not w.not_published


def test_heartbeat_payload(w, srv):
    w.run_once()
    assert srv.heartbeats() == [
        {"app_version": "0.1.0", "bundle_version": 2, "outbox": 0, "camera_ok": True, "fps": 30.0, "remote_ok": False}]


def test_heartbeat_failure_only_logged(w, srv):
    srv.heartbeat_status = (503, {}, None)
    assert w.run_once() == 30
    assert w.online and w.last_error == ""


def test_heartbeat_omits_bundle_version_without_bundle(srv, tmp_path):
    dev = Device(srv.fake.url, "tok", b"k" * 32, 1, "x")
    srv.bundle_status = (404, {}, {"error": "not_published"})
    w2 = SyncWorker(BoothApi(dev), BundleStore(tmp_path), lambda: {"outbox": 1}, None, lambda: None)
    assert w2.run_once() == 30
    assert srv.heartbeats() == [{"app_version": "0.1.0", "outbox": 1}]
    assert srv.bundle_etags() == [None]


def test_interval_override_and_bundle_interval(srv, tmp_path, make_bundle):
    dev = Device(srv.fake.url, "tok", b"k" * 32, 1, "x")
    store = BundleStore(tmp_path)
    raw, assets = make_bundle(version=2, settings_patch={"sync": {"interval_sec": 60}})
    store.stage(raw, assets.__getitem__)
    store.activate(2)
    srv.publish(2, settings_patch={"sync": {"interval_sec": 60}})
    api = BoothApi(dev)
    assert SyncWorker(api, store, dict, None, lambda: None).run_once() == 60
    assert SyncWorker(api, store, dict, 15, lambda: None).run_once() == 15


def test_thread_start_sync_now_stop(w, srv):
    w.start()
    try:
        for _ in range(100):
            if len(srv.bundle_etags()) >= 1:
                break
            time.sleep(0.05)
        n = len(srv.bundle_etags())
        assert n >= 1
        w.sync_now()
        for _ in range(100):
            if len(srv.bundle_etags()) > n:
                break
            time.sleep(0.05)
        assert len(srv.bundle_etags()) > n
    finally:
        w.stop()
    assert not w._thread.is_alive()


def test_retry_after_zero_or_negative_does_not_busy_loop(w, srv):
    for v in ("0", "-5", "nan", "inf"):
        srv.bundle_status = (503, {"Retry-After": v}, None)
        assert w.run_once() >= 1


def test_worker_started_before_clear_does_not_stage(w, srv):
    """재페어링(clear) 전에 만든 옛 워커가 받은 번들은 새 행사의 저장소에 남지 않는다."""
    srv.publish(3, fresh=True)
    w.store.clear()
    w.run_once()
    assert w.ready_version is None
    assert not (w.store.bundles / "3").exists()
