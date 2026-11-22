"""AR 스티커 — 불러오기, 얼굴 위 배치, 그리기.

배치는 관리자 미리보기(StickerPreview.tsx)와 같은 뜻이다: 기준점에서 얼굴 폭·높이 비율만큼 offset,
너비는 scale × 얼굴 폭. 미리보기와 달리 얼굴이 기울면 스티커와 offset 도 함께 기운다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .ar import FaceGeom, geometry

log = logging.getLogger(__name__)

MAX_FACES = 4
MIN_FACE_PX = 20  # 이보다 작은 얼굴은 건너뛴다


@dataclass
class Sticker:
    id: str
    name: str
    image: Image.Image  # RGBA
    anchor: str         # forehead | eyes | nose | cheeks | chin
    scale: float        # 얼굴 폭 대비 스티커 너비
    offset: tuple[float, float]  # (얼굴 폭, 얼굴 높이) 대비, 얼굴 축 기준 (+x 얼굴 오른쪽, +y 아래)


def load_stickers(settings: dict, asset_path: Callable[[str], Path]) -> list[Sticker]:
    """clamp 된 설정에서 스티커를 읽는다. 꺼져 있으면 빈 목록, 열 수 없는 에셋은 건너뛴다."""
    st = settings.get("stickers") or {}
    if not st.get("enabled"):
        return []
    out: list[Sticker] = []
    for it in st.get("items", []):
        try:
            with Image.open(asset_path(it["asset"])) as im:
                img = im.convert("RGBA")
            out.append(Sticker(it["id"], it["name"], img, it["anchor"], float(it["scale"]),
                               (float(it["offset"][0]), float(it["offset"][1]))))
        except Exception as exc:
            log.warning("스티커 %s 에셋을 열 수 없어 건너뜁니다: %s", it.get("id"), exc)
    return out


def _anchor_point(g: FaceGeom, anchor: str) -> np.ndarray:
    return {"forehead": g.forehead, "eyes": g.eyes, "nose": g.nose,
            "cheeks": (g.cheek_l + g.cheek_r) / 2, "chin": g.chin}.get(anchor, g.forehead)


def place(g: FaceGeom, st: Sticker) -> tuple[tuple[float, float], float, float]:
    """(중심 px, 너비 px, roll_deg).

    roll_deg 는 geometry().roll_deg 와 같은 규칙이다: PIL Image.rotate 에 그대로 넣으면 되는
    반시계 양수 (눈 벡터가 화면에서 반시계로 30° 기울어졌으면 30).
    offset 은 얼굴 축을 따른다: +x = 눈 벡터 방향(right), +y = 턱 방향(down = -up).
    """
    down = -g.up
    c = (_anchor_point(g, st.anchor).astype(np.float64)
         + st.offset[0] * g.width * g.right + st.offset[1] * g.height * down)
    return (float(c[0]), float(c[1])), st.scale * g.width, g.roll_deg


def _paste(frame: np.ndarray, sprite: Image.Image, center: tuple[float, float]) -> None:
    """RGBA 스프라이트를 중심 맞춰 알파 합성한다 (프레임 밖은 잘라낸다)."""
    sw, sh = sprite.size
    x0 = int(np.floor(center[0] - sw / 2 + 0.5))
    y0 = int(np.floor(center[1] - sh / 2 + 0.5))
    H, W = frame.shape[:2]
    fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(W, x0 + sw), min(H, y0 + sh)
    if fx0 >= fx1 or fy0 >= fy1:
        return
    sp = np.asarray(sprite)[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
    a = sp[..., 3:4].astype(np.float32) / 255.0
    region = frame[fy0:fy1, fx0:fx1].astype(np.float32)
    frame[fy0:fy1, fx0:fx1] = (sp[..., :3] * a + region * (1 - a)).astype(np.uint8)


def draw_stickers(rgb: np.ndarray, faces: list, st: Sticker) -> np.ndarray:
    """새 배열에 스티커를 얹어 돌려준다. 큰 얼굴부터 최대 MAX_FACES 개."""
    out = rgb.copy()
    h, w = out.shape[:2]
    geoms = sorted((geometry(f, w, h) for f in faces), key=lambda g: -g.width)[:MAX_FACES]
    for g in geoms:
        if g.width < MIN_FACE_PX:
            continue
        center, width, roll = place(g, st)
        sw = max(2, int(width))
        sh = max(2, int(width * st.image.height / st.image.width))
        sprite = st.image.resize((sw, sh), Image.Resampling.BILINEAR).rotate(
            roll, expand=True, resample=Image.Resampling.BILINEAR)
        _paste(out, sprite, center)
    return out
