"""번들 저장소, 원자적 교체, 비상용 zip 가져오기 테스트."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import zipfile
from pathlib import Path

import pytest

from walnut.bundle import Bundle, BundleStore, ZipImportError
from walnut.device import Device

KEY = b"k" * 32


def _slots():
    return [{"id": 1, "shot": 0, "cx": 100, "cy": 100, "w": 160, "h": 240, "rot": 0, "ratio": "2:3"}]


def _own_asset_bundle(make_bundle, version, tag: bytes, shared: bytes | None = None):
    """버전마다 전용 프레임 에셋(+ 선택적으로 공용 에셋)을 가진 번들."""
    own = b"frame-" + tag
    frames = [{"id": 1, "name": "f", "asset": hashlib.sha256(own).hexdigest(),
               "width": 400, "height": 600, "slots": _slots()}]
    assets = {hashlib.sha256(own).hexdigest(): own}
    if shared is not None:
        frames.append({"id": 2, "name": "g", "asset": hashlib.sha256(shared).hexdigest(),
                       "width": 400, "height": 600, "slots": _slots()})
        assets[hashlib.sha256(shared).hexdigest()] = shared
    raw, _ = make_bundle(version=version, frames=frames)
    return raw, assets


def _install(st: BundleStore, raw: bytes, assets: dict) -> int:
    v = st.stage(raw, assets.__getitem__)
    st.activate(v)
    return v


def _device(event_id: int = 1) -> Device:
    return Device("http://x", "tok", KEY, event_id, "테스트 행사")


# ---- 저장소 ----

def test_stage_activate_current(tmp_path, make_bundle):
    raw, assets = make_bundle(version=3)
    st = BundleStore(tmp_path)
    assert st.current() is None
    assert st.stage(raw, assets.__getitem__) == 3
    b = st.activate(3)
    assert b.version == 3 and b.raw == raw
    assert BundleStore(tmp_path).current().version == 3 and all(st.has_asset(s) for s in assets)
    assert (tmp_path / "bundles" / "current").read_text().strip() == "3"


def test_failed_download_leaves_no_trace(tmp_path, make_bundle):
    raw, assets = _own_asset_bundle(make_bundle, 3, b"a", shared=b"b")
    shas = sorted(assets)
    calls = []

    def fetch(sha):
        calls.append(sha)
        if len(calls) == 2:
            raise ConnectionError("끊김")
        return assets[sha]

    st = BundleStore(tmp_path)
    with pytest.raises(ConnectionError):
        st.stage(raw, fetch)
    assert len(calls) == 2 and sorted(calls) == shas
    assert [p.name for p in (tmp_path / "bundles").iterdir()] == []
    assert st.current() is None


def test_sha_mismatch_rejected(tmp_path, make_bundle):
    raw, assets = make_bundle(version=2)
    st = BundleStore(tmp_path)
    with pytest.raises(ValueError, match="sha_mismatch"):
        st.stage(raw, lambda sha: b"tampered")
    assert [p.name for p in (tmp_path / "bundles").iterdir()] == []
    assert not any(st.has_asset(s) for s in assets)


def test_existing_assets_not_refetched(tmp_path, make_bundle):
    raw1, assets1 = make_bundle(version=1)
    raw2, _ = make_bundle(version=2)
    st = BundleStore(tmp_path)
    _install(st, raw1, assets1)
    calls = []
    assert st.stage(raw2, lambda sha: calls.append(sha) or assets1[sha]) == 2
    assert calls == []
    # 이미 있는 버전은 다시 받지 않고 바로 반환
    assert st.stage(raw2, lambda sha: calls.append(sha)) == 2 and calls == []


def test_prune_keeps_two_and_unreferenced_assets_removed(tmp_path, make_bundle):
    st = BundleStore(tmp_path)
    b1 = _own_asset_bundle(make_bundle, 1, b"1", shared=b"s")
    b2 = _own_asset_bundle(make_bundle, 2, b"2")
    b3 = _own_asset_bundle(make_bundle, 3, b"3", shared=b"s")
    for raw, assets in (b1, b2, b3):
        _install(st, raw, assets)
    names = sorted(p.name for p in (tmp_path / "bundles").iterdir() if p.name != "current")
    assert names == ["2", "3"]
    only1 = hashlib.sha256(b"frame-1").hexdigest()
    assert not st.has_asset(only1)
    assert st.has_asset(hashlib.sha256(b"s").hexdigest())  # v3 도 쓰는 공용 에셋
    assert all(st.has_asset(s) for s in b2[1]) and all(st.has_asset(s) for s in b3[1])


def test_prune_keeps_ready_newer_version_and_staging_assets(tmp_path, make_bundle):
    st = BundleStore(tmp_path)
    for v in (3, 4):
        _install(st, *_own_asset_bundle(make_bundle, v, str(v).encode()))
    raw5, a5 = _own_asset_bundle(make_bundle, 5, b"5")
    st.stage(raw5, a5.__getitem__)  # 받아 두었지만 아직 적용 전
    # 받는 중인 v6 (staging) 의 에셋
    raw6, a6 = _own_asset_bundle(make_bundle, 6, b"6")
    stg = tmp_path / "bundles" / ".staging-6"
    stg.mkdir()
    (stg / "bundle.json").write_bytes(raw6)
    sha6 = next(iter(a6))
    (tmp_path / "assets" / sha6).write_bytes(a6[sha6])
    st.activate(4)
    names = sorted(p.name for p in (tmp_path / "bundles").iterdir() if p.name != "current")
    assert names == [".staging-6", "3", "4", "5"]
    assert all(st.has_asset(s) for s in a5) and st.has_asset(sha6)


def test_leftover_staging_removed_on_open(tmp_path):
    stg = tmp_path / "bundles" / ".staging-7"
    stg.mkdir(parents=True)
    (stg / "bundle.json").write_bytes(b"{half")
    BundleStore(tmp_path)
    assert not stg.exists()


def test_corrupt_current_falls_back_to_newest_valid(tmp_path, make_bundle):
    raw4, _ = make_bundle(version=4)
    bundles = tmp_path / "bundles"
    (bundles / "4").mkdir(parents=True)
    (bundles / "4" / "bundle.json").write_bytes(raw4)
    (bundles / "5").mkdir()
    (bundles / "5" / "bundle.json").write_bytes(b'{"version": 5, "ev')
    (bundles / "current").write_text("abc")
    st = BundleStore(tmp_path)
    assert st.current().version == 4
    assert (bundles / "current").read_text().strip() == "4"


def test_current_pointer_to_missing_dir_falls_back(tmp_path, make_bundle):
    st = BundleStore(tmp_path)
    _install(st, *make_bundle(version=2))
    (tmp_path / "bundles" / "current").write_text("9")
    assert st.current().version == 2


def test_parse_drops_frames_without_slots(make_bundle):
    png_sha = "a" * 64
    frames = [
        {"id": 1, "name": "a", "asset": png_sha, "width": 400, "height": 600, "slots": _slots()},
        {"id": 2, "name": "b", "asset": png_sha, "width": 400, "height": 600, "slots": []},
        {"id": 3, "name": "c", "asset": png_sha, "width": 400, "height": 600,
         "slots": [{"id": 1, "shot": None, "cx": 1, "cy": 1, "w": 1, "h": 1, "rot": 0}]},
        {"id": 4, "name": "d", "asset": png_sha, "width": 400, "height": 600},
    ]
    raw, _ = make_bundle(version=1, frames=frames, settings_patch={"capture": {"countdown_sec": 999}})
    b = Bundle.parse(raw)
    assert [f["id"] for f in b.frames] == [1]
    assert b.settings["capture"]["countdown_sec"] == 30  # clamp
    assert b.event_id == 1 and b.event_name == "테스트 행사"


@pytest.mark.parametrize("raw", [b"not json", b"[]", b'{"version": 1}',
                                 json.dumps({"version": "x", "event": {"id": 1, "name": "a"},
                                             "settings": {}, "frames": [], "assets": []}).encode()])
def test_parse_rejects_bad(raw):
    with pytest.raises(ValueError):
        Bundle.parse(raw)


# ---- 비상용 zip ----

def zip_of(tmp_path: Path, raw: bytes, assets: dict, key: bytes = KEY, sig: str | None = None,
           extra: dict | None = None) -> Path:
    """서버 bundle_zip 과 같은 모양의 zip."""
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bundle.json", raw)
        for sha, data in assets.items():
            z.writestr(f"assets/{sha}", data)
        z.writestr("signature", sig if sig is not None else hmac.new(key, raw, "sha256").hexdigest())
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def test_zip_import_ok(tmp_path, make_bundle):
    st = BundleStore(tmp_path / "data")
    _install(st, *make_bundle(version=3))
    raw, assets = _own_asset_bundle(make_bundle, 4, b"z")
    assert st.import_zip(zip_of(tmp_path, raw, assets), _device()) == 4
    assert st.current().version == 4 and all(st.has_asset(s) for s in assets)
    # 같은 버전도 받아들인다
    assert st.import_zip(zip_of(tmp_path, raw, assets), _device()) == 4


def test_zip_import_without_current(tmp_path, make_bundle):
    st = BundleStore(tmp_path / "data")
    raw, assets = make_bundle(version=1)
    assert st.import_zip(zip_of(tmp_path, raw, assets), _device()) == 1


def _reason(st, path, device=None) -> str:
    with pytest.raises(ZipImportError) as e:
        st.import_zip(path, device or _device())
    return e.value.reason


def test_zip_tampered_bundle_rejected(tmp_path, make_bundle):
    raw, assets = make_bundle(version=1)
    sig = hmac.new(KEY, raw, "sha256").hexdigest()
    bad = raw.replace(b"\xed\x85\x8c\xec\x8a\xa4\xed\x8a\xb8", b"\xed\x85\x8c\xec\x8a\xa4\xed\x8a\xb9", 1)
    assert bad != raw
    st = BundleStore(tmp_path / "data")
    assert _reason(st, zip_of(tmp_path, bad, assets, sig=sig)) == "bad_signature"
    assert _reason(st, zip_of(tmp_path, raw, assets, key=b"x" * 32)) == "bad_signature"
    assert _reason(st, zip_of(tmp_path, raw, assets, sig="서명")) == "bad_signature"
    assert st.current() is None


def test_zip_other_event_rejected(tmp_path, make_bundle):
    raw, assets = make_bundle(version=1, event_id=2)
    assert _reason(BundleStore(tmp_path / "data"), zip_of(tmp_path, raw, assets)) == "other_event"


def test_zip_older_version_rejected(tmp_path, make_bundle):
    st = BundleStore(tmp_path / "data")
    _install(st, *make_bundle(version=5))
    raw, assets = make_bundle(version=4)
    assert _reason(st, zip_of(tmp_path, raw, assets)) == "older_version"
    assert st.current().version == 5


def test_zip_path_traversal_rejected(tmp_path, make_bundle):
    raw, assets = make_bundle(version=1)
    st = BundleStore(tmp_path / "data")
    assert _reason(st, zip_of(tmp_path, raw, assets, extra={"../evil": b"x"})) == "bad_zip"
    assert _reason(st, zip_of(tmp_path, raw, assets, extra={"assets/../../evil": b"x"})) == "bad_zip"
    assert not (tmp_path / "evil").exists()


def test_zip_asset_sha_mismatch_rejected(tmp_path, make_bundle):
    raw, assets = make_bundle(version=1)
    bad = {s: b"tampered" for s in assets}
    st = BundleStore(tmp_path / "data")
    assert _reason(st, zip_of(tmp_path, raw, bad)) == "sha_mismatch"
    assert st.current() is None and not any(st.has_asset(s) for s in assets)


def test_zip_not_a_zip_or_missing_parts(tmp_path, make_bundle):
    st = BundleStore(tmp_path / "data")
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"PK not really")
    assert _reason(st, junk) == "bad_zip"
    raw, _ = make_bundle(version=1)
    assert _reason(st, zip_of(tmp_path, raw, {})) == "bad_zip"  # 에셋 빠짐
    notjson = b"{oops"
    assert _reason(st, zip_of(tmp_path, notjson, {})) == "bad_zip"


# ---- 동시성: 내려받는 동안 잠금을 쥐지 않는다 ----

def _blocking_stage(st, raw, assets, release: threading.Event, started: threading.Event):
    """첫 fetch 에서 release 를 기다리는 stage 를 다른 스레드로 돌린다."""
    out: dict = {}

    def fetch(sha):
        started.set()
        release.wait(5)
        return assets[sha]

    def run():
        try:
            out["v"] = st.stage(raw, fetch)
        except BaseException as e:  # noqa: BLE001
            out["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert started.wait(5)
    return t, out


def test_current_not_blocked_by_download(tmp_path, make_bundle):
    st = BundleStore(tmp_path)
    _install(st, *make_bundle(version=1))
    release, started = threading.Event(), threading.Event()
    t, out = _blocking_stage(st, *_own_asset_bundle(make_bundle, 2, b"2"), release, started)
    got: dict = {}
    reader = threading.Thread(target=lambda: got.setdefault("b", st.current()), daemon=True)
    reader.start()
    reader.join(1)
    alive = reader.is_alive()
    release.set()
    t.join(5)
    assert not alive and got["b"].version == 1
    assert out == {"v": 2}


def test_prune_mid_stage_keeps_inflight_assets(tmp_path, make_bundle):
    st = BundleStore(tmp_path)
    for v in (1, 2):
        _install(st, *make_bundle(version=v))
    raw3, a3 = _own_asset_bundle(make_bundle, 3, b"3", shared=b"s")
    shas = sorted(a3)
    # 첫 에셋은 받고, 두 번째에서 멈춘 사이에 prune
    release, reached = threading.Event(), threading.Event()
    out: dict = {}

    def fetch(sha):
        if sha == shas[1]:
            reached.set()
            release.wait(5)
        return a3[sha]

    t = threading.Thread(target=lambda: out.setdefault("v", st.stage(raw3, fetch)), daemon=True)
    t.start()
    assert reached.wait(5)
    pruner = threading.Thread(target=st.prune, daemon=True)
    pruner.start()
    pruner.join(1)
    assert not pruner.is_alive()  # 내려받는 동안에도 바로 끝난다
    assert st.has_asset(shas[0])
    release.set()
    t.join(5)
    assert out == {"v": 3} and all(st.has_asset(s) for s in a3)
    st.activate(3)
    assert st.current().version == 3


def test_same_version_staged_concurrently(tmp_path, make_bundle):
    st = BundleStore(tmp_path)
    raw, assets = _own_asset_bundle(make_bundle, 4, b"4")
    release, started = threading.Event(), threading.Event()
    t, out = _blocking_stage(st, raw, assets, release, started)
    assert st.stage(raw, assets.__getitem__) == 4  # 다른 호출이 먼저 완성
    release.set()
    t.join(5)
    assert out == {"v": 4}
    names = sorted(p.name for p in (tmp_path / "bundles").iterdir())
    assert names == ["4"]
    assert st.activate(4).version == 4


# ---- 정리 실패 · 재페어링 경합 ----

def test_prune_unlink_failure_does_not_fail_activate(tmp_path, make_bundle, monkeypatch):
    """윈도에서 열린 파일은 지울 수 없다 (WinError 32). 포인터를 옮긴 뒤의 정리 실패로 적용이 실패하면 안 된다."""
    st = BundleStore(tmp_path)
    for v in (1, 2):
        _install(st, *_own_asset_bundle(make_bundle, v, str(v).encode()))
    raw3, a3 = _own_asset_bundle(make_bundle, 3, b"3")
    st.stage(raw3, a3.__getitem__)
    only1 = hashlib.sha256(b"frame-1").hexdigest()
    real_unlink = Path.unlink

    def locked(self, *a, **kw):
        if self.name == only1:
            raise PermissionError(32, "다른 프로세스가 파일을 사용 중")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", locked)
    b = st.activate(3)
    assert b.version == 3 and st.current().version == 3
    assert st.has_asset(only1)  # 못 지운 것은 남는다
    monkeypatch.setattr(Path, "unlink", real_unlink)
    st.prune()  # 다음 정리가 다시 시도한다
    assert not st.has_asset(only1)


def test_zip_import_succeeds_when_prune_cannot_delete(tmp_path, make_bundle, monkeypatch):
    st = BundleStore(tmp_path)
    for v in (1, 2):
        _install(st, *_own_asset_bundle(make_bundle, v, str(v).encode()))
    raw, assets = make_bundle(version=3)
    path = zip_of(tmp_path, raw, assets)
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **kw: (_ for _ in ()).throw(PermissionError(32, "사용 중")))
    assert st.import_zip(path, _device()) == 3
    assert st.current().version == 3


def test_stage_after_clear_is_discarded(tmp_path, make_bundle):
    """옛 동기화 스레드가 clear() 뒤에 끝낸 받기는 새 행사의 번들로 남지 않는다."""
    st = BundleStore(tmp_path)
    epoch = st.epoch
    raw, assets = make_bundle(version=1, event_id=7)
    st.clear()  # 재페어링
    with pytest.raises(ValueError):
        st.stage(raw, assets.__getitem__, epoch=epoch)
    assert [p.name for p in (tmp_path / "bundles").iterdir()] == []
    assert st.current() is None


def test_clear_during_download_discards_staging(tmp_path, make_bundle):
    st = BundleStore(tmp_path)
    raw, assets = _own_asset_bundle(make_bundle, 1, b"x")

    def fetch(sha):
        st.clear()  # 받는 도중 재페어링
        (tmp_path / "bundles" / ".staging-1-zzzz").mkdir()  # clear 뒤 새 디렉터리가 있어도 상관없다
        return assets[sha]

    with pytest.raises(ValueError):
        st.stage(raw, fetch)
    assert not (tmp_path / "bundles" / "1").exists()


def test_discard_removes_version_and_pointer(tmp_path, make_bundle):
    st = BundleStore(tmp_path)
    for v in (1, 2):
        _install(st, *_own_asset_bundle(make_bundle, v, str(v).encode()))
    st.discard(2)
    assert not (tmp_path / "bundles" / "2").exists()
    assert st.current().version == 1  # 남은 것 중 가장 새 버전으로
    assert st.peek(1).version == 1 and st.peek(2) is None
