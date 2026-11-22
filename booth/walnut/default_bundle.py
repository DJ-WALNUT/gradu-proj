"""기본 번들 — 페어링 없이 쓸 때의 설정과 프레임.

설정은 settings.DEFAULTS. 프레임은 시험용 프레임 폴더(booth/assets/frame) 의 PNG 전부이고,
폴더가 없거나 쓸 프레임이 없으면 default_frame/ 의 기본 프레임 하나다 (원본은 shared/booth-design/default-frame).
폴더의 PNG 는 투명 구멍을 슬롯으로 찾는다 (위 줄 왼쪽부터 shot 0, 1, ...). 같은 이름의 .json 에
{"slots": [...]} 가 있으면 그것을 쓴다.
다른 코드가 에셋을 BundleStore.asset_path(sha) 로만 읽으므로, 쓰기 전에 install() 로 PNG 를 그 자리에 놓는다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .bundle import Bundle, BundleStore, _write_atomic
from .settings import DEFAULTS

LOCAL_EVENT_ID = 0
LOCAL_EVENT_NAME = "연결 없이 사용"

_DIR = Path(__file__).resolve().parent / "default_frame"
DEFAULT_FRAME_DIR = Path(__file__).resolve().parents[1] / "assets" / "frame"
FRAME_DIR = DEFAULT_FRAME_DIR  # 시험에서 바꿔 끼운다

HOLE_ALPHA = 128       # 이보다 투명하면 구멍
MIN_HOLE_AREA = 0.01   # 그림 넓이 대비 이보다 작은 구멍은 잔티로 본다

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def frame_png() -> bytes:
    return (_DIR / "frame.png").read_bytes()


def detect_slots(img: Image.Image) -> list[dict]:
    """투명 구멍의 경계 상자를 슬롯으로. 장식이 구멍 안으로 들어와도 상자는 구멍 전체를 덮는다."""
    alpha = np.asarray(img.convert("RGBA"))[:, :, 3]
    holes = (alpha < HOLE_ALPHA).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(holes, connectivity=8)
    boxes = [tuple(int(v) for v in stats[i][:4]) for i in range(1, n)
             if stats[i][4] >= MIN_HOLE_AREA * alpha.size]
    if not boxes:
        return []
    # 읽는 순서: 위쪽이 가장 작은 상자 높이의 절반 안에 들면 같은 줄, 줄 안에서는 왼쪽부터
    tol = min(h for _, _, _, h in boxes) / 2
    boxes.sort(key=lambda b: b[1])
    rows: list[list[tuple]] = []
    for b in boxes:
        if rows and b[1] - rows[-1][0][1] <= tol:
            rows[-1].append(b)
        else:
            rows.append([b])
    ordered = [b for row in rows for b in sorted(row, key=lambda b: b[0])]
    return [{"id": f"s{i + 1}", "shot": i, "cx": x + w / 2, "cy": y + h / 2, "w": w, "h": h,
             "rot": 0, "ratio": "free"} for i, (x, y, w, h) in enumerate(ordered)]


def _folder_frames(frame_dir: Path) -> list[dict]:
    """폴더의 PNG 를 이름순으로 읽는다. 읽지 못하거나 슬롯이 없는 PNG 는 건너뛴다."""
    out: list[dict] = []
    if not frame_dir.is_dir():
        return out
    for path in sorted(frame_dir.glob("*.png")):
        try:
            png = path.read_bytes()
            img = Image.open(path)
            img.load()
            side = path.with_suffix(".json")
            if side.is_file():
                slots = json.loads(side.read_text(encoding="utf-8"))["slots"]
            else:
                slots = detect_slots(img)
        except Exception:
            log.warning("시험용 프레임을 읽지 못함: %s", path.name, exc_info=True)
            continue
        if not slots:
            log.warning("시험용 프레임에 투명 구멍(슬롯)이 없어 건너뜀: %s", path.name)
            continue
        out.append({"name": path.stem, "png": png, "width": img.width, "height": img.height, "slots": slots})
    return out


def _frames(frame_dir: Path | None) -> list[dict]:
    """쓸 프레임 목록. 폴더에 쓸 프레임이 없으면 기본 프레임 하나."""
    found = _folder_frames(FRAME_DIR if frame_dir is None else Path(frame_dir))
    if found:
        return found
    meta = json.loads((_DIR / "frame.json").read_text(encoding="utf-8"))
    return [{"name": meta["name"], "png": frame_png(), "width": meta["width"],
             "height": meta["height"], "slots": meta["slots"]}]


def _merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def build(settings_patch: dict | None = None, frame_dir: Path | None = None) -> Bundle:
    """기본 번들. settings_patch 는 기본 설정 위에 깊게 덮어쓴다 (값 보정은 Bundle.parse 가 한다).
    frame_dir 가 None 이면 FRAME_DIR (booth/assets/frame)."""
    frames, assets = [], []
    for i, f in enumerate(_frames(frame_dir), start=1):
        sha = hashlib.sha256(f["png"]).hexdigest()
        frames.append({"id": i, "name": f["name"], "asset": sha, "width": f["width"],
                       "height": f["height"], "slots": f["slots"]})
        if all(a["sha256"] != sha for a in assets):
            assets.append({"sha256": sha, "kind": "frame", "size": len(f["png"])})
    settings = _merge(copy.deepcopy(DEFAULTS), settings_patch or {})
    raw = json.dumps({
        "version": 0,
        "event": {"id": LOCAL_EVENT_ID, "name": LOCAL_EVENT_NAME},
        "settings": settings,
        "frames": frames,
        "assets": assets,
    }, ensure_ascii=False, sort_keys=True).encode()
    return Bundle.parse(raw)


def install(store: BundleStore, frame_dir: Path | None = None) -> None:
    """쓸 프레임 PNG 를 에셋 캐시에 놓는다 (이미 있으면 그대로). 번들 폴더 · 포인터는 건드리지 않는다."""
    for f in _frames(frame_dir):
        path = store.asset_path(hashlib.sha256(f["png"]).hexdigest())
        if not path.is_file():
            _write_atomic(path, f["png"])
