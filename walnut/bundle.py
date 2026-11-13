"""번들 저장소: 받아 두기(stage) → 적용(activate) → 정리(prune), 비상용 zip 가져오기.

디스크 구조 (root = booth/data):
  bundles/<v>/bundle.json   받은 번들 원문 바이트
  bundles/.staging-<v>/     받는 중 (전원 차단 등으로 남으면 다음 실행 때 지운다)
  bundles/current           적용 중인 버전 숫자
  assets/<sha256>           에셋 캐시 (번들끼리 공유)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from walnut.device import Device
from walnut.settings import clamp_settings

log = logging.getLogger(__name__)

_SHA = re.compile(r"[0-9a-f]{64}")
_ZIP_ASSET = re.compile(r"assets/([0-9a-f]{64})")
MAX_ZIP_ENTRY = 64 * 1024 * 1024  # zip 항목당 압축 해제 크기 상한
STAGING = ".staging-"


class ZipImportError(Exception):
    """비상용 zip 거절. reason ∈ bad_zip, bad_signature, other_event, older_version, sha_mismatch."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _valid_slot(s: object) -> bool:
    """shot 이 0 이상 정수이고 위치·크기가 숫자인 슬롯만 쓴다."""
    return (isinstance(s, dict) and _is_int(s.get("shot")) and s["shot"] >= 0
            and all(_is_num(s.get(k)) for k in ("cx", "cy", "w", "h"))
            and s["w"] > 0 and s["h"] > 0)


def _clean_frame(f: object) -> dict | None:
    """슬롯이 없거나 쓸 슬롯이 하나도 없는 프레임은 None (버린다)."""
    if not isinstance(f, dict) or not isinstance(f.get("asset"), str):
        return None
    slots = f.get("slots")
    if not isinstance(slots, list):
        return None
    good = [s for s in slots if _valid_slot(s)]
    if not good:
        return None
    return {**f, "slots": good}


@dataclass
class Bundle:
    version: int
    event_id: int
    event_name: str
    settings: dict  # clamp 된 값
    frames: list[dict]
    assets: list[dict]
    raw: bytes = field(repr=False)

    @classmethod
    def parse(cls, raw: bytes) -> "Bundle":
        """JSON 이 아니거나 필수 키가 없으면 ValueError."""
        try:
            d = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("bad_json") from e
        if not isinstance(d, dict):
            raise ValueError("bad_json")
        ev, frames, assets = d.get("event"), d.get("frames"), d.get("assets")
        if not _is_int(d.get("version")) or not isinstance(ev, dict) or not _is_int(ev.get("id")):
            raise ValueError("missing_keys")
        if not isinstance(frames, list) or not isinstance(assets, list):
            raise ValueError("missing_keys")
        return cls(
            version=d["version"],
            event_id=ev["id"],
            event_name=str(ev.get("name") or ""),
            settings=clamp_settings(d.get("settings")),
            frames=[f for f in map(_clean_frame, frames) if f is not None],
            # 경로로 쓰이므로 sha 형식이 아닌 항목은 버린다
            assets=[a for a in assets if isinstance(a, dict) and isinstance(a.get("sha256"), str)
                    and _SHA.fullmatch(a["sha256"])],
            raw=raw,
        )

    def asset_shas(self) -> list[str]:
        return list(dict.fromkeys(a["sha256"] for a in self.assets))


def _write_atomic(path: Path, data: bytes) -> None:
    """임시 파일에 쓰고 fsync 뒤 교체 (전원 차단에도 반쯤 쓴 파일이 남지 않게)."""
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _rmtree(path: Path) -> None:
    """지울 수 있는 것만 지운다 (윈도에서 열린 파일은 못 지움 → 다음 정리 때 다시)."""
    def onerror(_fn, p, exc_info) -> None:
        log.warning("지우지 못함 (다음 정리 때 다시): %s (%s)", p, exc_info[1])

    shutil.rmtree(path, onerror=onerror)


class BundleStore:
    """동기화 스레드(stage)와 메인 스레드(activate·prune·import_zip·current)가 함께 쓴다."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.bundles = self.root / "bundles"
        self.assets = self.root / "assets"
        self._lock = threading.RLock()
        # clear() 마다 늘어난다. 시작할 때의 값과 다르면 받던 번들은 옛 행사 것이므로 버린다
        self.epoch = 0
        self.bundles.mkdir(parents=True, exist_ok=True)
        self.assets.mkdir(parents=True, exist_ok=True)
        # 지난 실행이 받다 만 흔적 정리
        for p in self.bundles.iterdir():
            if p.name.startswith(STAGING):
                shutil.rmtree(p, ignore_errors=True)
        for p in self.assets.iterdir():
            if ".tmp-" in p.name:
                p.unlink(missing_ok=True)

    # ---- 조회 ----

    def asset_path(self, sha: str) -> Path:
        if not _SHA.fullmatch(sha):
            raise ValueError("bad_sha")
        return self.assets / sha

    def has_asset(self, sha: str) -> bool:
        return self.asset_path(sha).is_file()

    def _versions(self) -> list[int]:
        """완료된 번들 버전들 (작은 것부터)."""
        return sorted(int(p.name) for p in self.bundles.iterdir() if p.is_dir() and p.name.isdigit())

    def _load(self, version: int) -> Bundle | None:
        try:
            return Bundle.parse((self.bundles / str(version) / "bundle.json").read_bytes())
        except (OSError, ValueError):
            return None

    def peek(self, version: int) -> Bundle | None:
        """받아 둔 번들을 적용하지 않고 읽는다. 없거나 깨졌으면 None."""
        with self._lock:
            b = self._load(version)
            return b if b is not None and b.version == version else None

    def _pointer(self) -> int | None:
        try:
            return int((self.bundles / "current").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _set_pointer(self, version: int) -> None:
        _write_atomic(self.bundles / "current", str(version).encode())

    def current(self) -> Bundle | None:
        """포인터가 없거나 깨졌으면 온전한 가장 큰 버전으로 대신하고 포인터를 고친다."""
        with self._lock:
            v = self._pointer()
            if v is not None:
                b = self._load(v)
                if b is not None and b.version == v:
                    return b
            for cand in reversed(self._versions()):
                b = self._load(cand)
                if b is not None and b.version == cand:
                    self._set_pointer(cand)
                    return b
            return None

    # ---- 받기 · 적용 ----

    def stage(self, raw: bytes, fetch: Callable[[str], bytes], epoch: int | None = None) -> int:
        """번들과 없는 에셋을 받아 bundles/<v> 로 완성, 버전 반환. 도중 실패면 staging 을 지우고 다시 던진다.
        내려받는 동안은 잠금을 풀어 메인 스레드(current·activate)가 멈추지 않게 한다.
        epoch: 호출자가 번들을 요청하기 전에 읽어 둔 self.epoch (없으면 지금 값). 그 뒤 clear() 가 있었으면
        옛 행사의 번들이므로 남기지 않고 ValueError("stale_epoch")."""
        b = Bundle.parse(raw)
        final = self.bundles / str(b.version)
        # 같은 버전을 두 곳에서 동시에 받아도 서로 덮어쓰지 않게 staging 이름을 호출마다 다르게
        staging = self.bundles / f"{STAGING}{b.version}-{uuid.uuid4().hex[:8]}"
        with self._lock:
            if epoch is None:
                epoch = self.epoch
            if epoch != self.epoch:
                raise ValueError("stale_epoch")
            if final.is_dir():
                return b.version
            staging.mkdir(parents=True)
            try:
                # bundle.json 을 먼저 써 두어야 받는 도중의 prune 이 이 번들의 에셋을 지우지 않는다
                _write_atomic(staging / "bundle.json", raw)
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        try:
            for sha in b.asset_shas():
                if self.has_asset(sha):
                    continue
                data = fetch(sha)  # 네트워크: 잠금 밖
                if hashlib.sha256(data).hexdigest() != sha:
                    raise ValueError("sha_mismatch")
                with self._lock:
                    _write_atomic(self.asset_path(sha), data)
            with self._lock:
                if epoch != self.epoch:  # 받는 도중 재페어링 (clear) 했다
                    shutil.rmtree(staging, ignore_errors=True)
                    raise ValueError("stale_epoch")
                if final.is_dir():  # 다른 호출이 먼저 완성했다
                    shutil.rmtree(staging, ignore_errors=True)
                else:
                    os.replace(staging, final)  # 도중 clear() 로 staging 이 없어졌으면 여기서 예외
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return b.version

    def activate(self, version: int) -> Bundle:
        """current 포인터를 원자적으로 바꾸고 정리한다. 포인터를 옮긴 뒤의 정리 실패는 로그만 남긴다."""
        with self._lock:
            b = self._load(version)
            if b is None:
                raise ValueError(f"번들 {version} 없음")
            self._set_pointer(version)
            try:
                self.prune()
            except Exception:
                log.exception("번들 정리 실패 (적용은 됨, 다음 정리 때 다시)")
            return b

    def discard(self, version: int) -> None:
        """받아 둔 번들 하나를 버린다 (다른 행사 것일 때). 다음 동기화가 새로 받는다."""
        with self._lock:
            _rmtree(self.bundles / str(version))

    def prune(self) -> None:
        """현재 + 바로 아래 1개, 그리고 받아 두고 아직 적용 전인 더 새 버전만 남긴다.
        남은 번들·받는 중인 staging 이 참조하지 않는 에셋은 지운다."""
        with self._lock:
            cur = self._pointer()
            if cur is None or not (self.bundles / str(cur)).is_dir():
                return
            versions = self._versions()
            older = [v for v in versions if v < cur]
            keep = {cur, *older[-1:], *(v for v in versions if v > cur)}
            for v in versions:
                if v not in keep:
                    _rmtree(self.bundles / str(v))
            used: set[str] = set()
            dirs = [self.bundles / str(v) for v in keep]
            dirs += [p for p in self.bundles.iterdir() if p.name.startswith(STAGING)]
            for d in dirs:
                try:
                    used.update(Bundle.parse((d / "bundle.json").read_bytes()).asset_shas())
                except (OSError, ValueError):
                    pass
            for p in self.assets.iterdir():
                if p.name not in used:
                    try:
                        p.unlink(missing_ok=True)
                    except OSError as e:  # 윈도에서 열려 있는 글꼴 등. 다음 정리 때 다시
                        log.warning("에셋을 지우지 못함 (다음 정리 때 다시): %s (%s)", p.name, e)

    def clear(self) -> None:
        """재페어링: 번들을 모두 비운다 (에셋 캐시는 두고 다음 prune 이 정리)."""
        with self._lock:
            self.epoch += 1
            shutil.rmtree(self.bundles, ignore_errors=True)
            self.bundles.mkdir(parents=True, exist_ok=True)

    # ---- 비상용 zip ----

    def import_zip(self, path: Path, device: Device) -> int:
        """서버 bundle_zip 이 만든 zip 을 검증해 적용하고 버전을 반환. 실패는 ZipImportError."""
        with self._lock:
            try:
                z = zipfile.ZipFile(path)
            except (zipfile.BadZipFile, OSError) as e:
                raise ZipImportError("bad_zip") from e
            with z:
                infos = {}
                for info in z.infolist():
                    name = info.filename
                    # 정해진 이름만 허용 (경로 탈출 차단)
                    if name not in ("bundle.json", "signature") and not _ZIP_ASSET.fullmatch(name):
                        raise ZipImportError("bad_zip")
                    if info.file_size > MAX_ZIP_ENTRY or name in infos:
                        raise ZipImportError("bad_zip")
                    infos[name] = info
                if "bundle.json" not in infos or "signature" not in infos:
                    raise ZipImportError("bad_zip")

                def read(name: str) -> bytes:
                    try:
                        return z.read(infos[name])
                    except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as e:
                        raise ZipImportError("bad_zip") from e

                raw = read("bundle.json")
                sig = read("signature").strip()  # bytes 로 비교 (비ASCII 가 섞여도 예외 없이 불일치)
                expected = hmac.new(device.bundle_key, raw, "sha256").hexdigest().encode()
                if not hmac.compare_digest(expected, sig):
                    raise ZipImportError("bad_signature")
                try:
                    b = Bundle.parse(raw)
                except ValueError as e:
                    raise ZipImportError("bad_zip") from e
                if b.event_id != device.event_id:
                    raise ZipImportError("other_event")
                cur = self.current()
                if cur is not None and b.version < cur.version:
                    raise ZipImportError("older_version")

                def fetch(sha: str) -> bytes:
                    name = f"assets/{sha}"
                    if name not in infos:
                        raise ZipImportError("bad_zip")
                    return read(name)

                try:
                    v = self.stage(raw, fetch)
                except ValueError as e:
                    if str(e) == "sha_mismatch":
                        raise ZipImportError("sha_mismatch") from e
                    raise ZipImportError("bad_zip") from e
            self.activate(v)
            return v
