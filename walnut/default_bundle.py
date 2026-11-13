"""기본 번들 — 페어링 없이 쓸 때의 설정과 프레임.

설정은 settings.DEFAULTS, 프레임은 default_frame/ 의 기본 프레임 하나다 (원본은 shared/booth-design/default-frame).
다른 코드가 에셋을 BundleStore.asset_path(sha) 로만 읽으므로, 쓰기 전에 install() 로 PNG 를 그 자리에 놓는다.
"""

from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from .bundle import Bundle, BundleStore, _write_atomic
from .settings import DEFAULTS

LOCAL_EVENT_ID = 0
LOCAL_EVENT_NAME = "연결 없이 사용"

_DIR = Path(__file__).resolve().parent / "default_frame"


@lru_cache(maxsize=1)
def frame_png() -> bytes:
    return (_DIR / "frame.png").read_bytes()


def _merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def build(settings_patch: dict | None = None) -> Bundle:
    """기본 번들. settings_patch 는 기본 설정 위에 깊게 덮어쓴다 (값 보정은 Bundle.parse 가 한다)."""
    png = frame_png()
    sha = hashlib.sha256(png).hexdigest()
    frame = json.loads((_DIR / "frame.json").read_text(encoding="utf-8"))
    settings = _merge(copy.deepcopy(DEFAULTS), settings_patch or {})
    raw = json.dumps({
        "version": 0,
        "event": {"id": LOCAL_EVENT_ID, "name": LOCAL_EVENT_NAME},
        "settings": settings,
        "frames": [{"id": 1, "name": frame["name"], "asset": sha, "width": frame["width"],
                    "height": frame["height"], "slots": frame["slots"]}],
        "assets": [{"sha256": sha, "kind": "frame", "size": len(png)}],
    }, ensure_ascii=False, sort_keys=True).encode()
    return Bundle.parse(raw)


def install(store: BundleStore) -> None:
    """기본 프레임 PNG 를 에셋 캐시에 놓는다 (이미 있으면 그대로). 번들 폴더 · 포인터는 건드리지 않는다."""
    png = frame_png()
    path = store.asset_path(hashlib.sha256(png).hexdigest())
    if not path.is_file():
        _write_atomic(path, png)
