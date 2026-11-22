"""기기 등록 정보(서버 주소, 토큰, 번들 키)를 device.json 에 저장한다."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Device:
    server_url: str
    token: str
    bundle_key: bytes
    event_id: int
    event_name: str


def decode_key(s: str) -> bytes:
    """urlsafe base64 (패딩 없어도 허용) 를 바이트로."""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class DeviceStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> Device | None:
        """없거나 깨졌으면 None."""
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return Device(
                server_url=str(d["server_url"]),
                token=str(d["token"]),
                bundle_key=decode_key(d["bundle_key"]),
                event_id=int(d["event_id"]),
                event_name=str(d["event_name"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, d: Device) -> None:
        """임시 파일에 쓰고 fsync 뒤 교체 (전원 차단에도 반쯤 쓴 파일이 남지 않게)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "server_url": d.server_url,
            "token": d.token,
            "bundle_key": base64.urlsafe_b64encode(d.bundle_key).decode("ascii"),
            "event_id": d.event_id,
            "event_name": d.event_name,
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
