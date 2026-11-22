"""자유 슬롯 합성. 수식은 shared/README.md 가 최종본이다."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Callable

from PIL import Image

log = logging.getLogger(__name__)

CropFor = Callable[[dict, Image.Image], "tuple[int, int, int, int] | None"]


def round_half_up(v: float) -> int:
    """파이썬 round() 는 은행원 반올림이라 쓰지 않는다."""
    return math.floor(v + 0.5)


def slot_corners(slot: dict) -> list[tuple[float, float]]:
    """좌상 → 우상 → 우하 → 좌하. rot 은 시계 방향 도 (y 아래)."""
    w, h, cx, cy = slot["w"], slot["h"], slot["cx"], slot["cy"]
    th = slot.get("rot", 0) * math.pi / 180
    c, s = math.cos(th), math.sin(th)
    local = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in local]


def cover_crop(pw: int, ph: int, w: float, h: float) -> tuple[int, int, int, int]:
    """슬롯 비율을 채우도록 사진을 가운데에서 자를 영역 (x, y, w, h)."""
    ar = w / h
    if pw / ph > ar:
        cw = max(1, round_half_up(ph * ar))
        return (pw - cw) // 2, 0, cw, ph
    ch = max(1, round_half_up(pw / ar))
    return 0, (ph - ch) // 2, pw, ch


def _slot_crop(crop_for: CropFor | None, slot: dict, cut: Image.Image) -> tuple[int, int, int, int]:
    """crop_for 가 준 크롭. 없거나 실패하거나 사진 밖이면 가운데 크롭 (분석 실패가 촬영을 멈추면 안 된다)."""
    center = cover_crop(cut.width, cut.height, slot["w"], slot["h"])
    if crop_for is None:
        return center
    try:
        box = crop_for(slot, cut)
        if box is None:
            return center
        x, y, cw, ch = (int(v) for v in box)
        if cw < 1 or ch < 1 or x < 0 or y < 0 or x + cw > cut.width or y + ch > cut.height:
            raise ValueError(f"사진 밖 크롭 {box}")
        return x, y, cw, ch
    except Exception as e:
        log.warning("스마트 크롭을 쓰지 못해 가운데 크롭으로 합성합니다: %s", e)
        return center


def compose(frame_png: Image.Image, slots: list[dict], cuts: list[Image.Image],
            crop_for: CropFor | None = None) -> Image.Image:
    """흰 바탕 → 슬롯별 사진 → 프레임 PNG 순으로 쌓은 RGB 이미지 (프레임 크기).

    crop_for(slot, cut) 는 슬롯마다 컷에서 자를 영역 (x, y, w, h) 을 준다. None 이면 가운데 크롭.
    """
    frame = frame_png.convert("RGBA")
    canvas = Image.new("RGBA", frame.size, (255, 255, 255, 255))
    for slot in slots:
        cut = cuts[slot["shot"]].convert("RGB")
        x, y, cw, ch = _slot_crop(crop_for, slot, cut)
        piece = cut.crop((x, y, x + cw, y + ch))
        piece = piece.resize((max(1, round_half_up(slot["w"])), max(1, round_half_up(slot["h"]))), Image.BICUBIC)
        piece = piece.convert("RGBA").rotate(-slot.get("rot", 0), Image.BICUBIC, expand=True)
        left = math.floor(slot["cx"] - piece.width / 2 + 0.5)
        top = math.floor(slot["cy"] - piece.height / 2 + 0.5)
        # 회전 모서리는 투명이라 알파 합성해야 한다.
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.paste(piece, (left, top))
        canvas = Image.alpha_composite(canvas, layer)
    return Image.alpha_composite(canvas, frame).convert("RGB")


def save_jpeg(img: Image.Image, path: Path) -> None:
    """임시 파일에 쓴 뒤 os.replace (전원 차단에도 반쯤 쓴 파일이 남지 않게)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    img.convert("RGB").save(tmp, format="JPEG", quality=92)
    os.replace(tmp, path)
