"""화면 기반 무대 — 모니터 크기에서 방향 · 논리 캔버스 크기를 정한다.

계산은 웹 부스 booth-web/src/ui/Stage.tsx 의 stageGeometry 와 같다 (공용 픽스처 shared/booth-design/stage_fixtures.json).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pygame

# 배치 토큰의 기준 크기 (tokens.json layout 의 설계 단위)
BASE = {"landscape": (1920, 1080), "portrait": (1080, 1920)}
_ADD = {"left": 0.0, "top": 0.0, "center": 0.5, "right": 1.0, "bottom": 1.0}


def _round(v: float) -> int:
    """JS Math.round 와 같이 .5 는 올린다 (파이썬 round 는 짝수로)."""
    return math.floor(v + 0.5)


@dataclass(frozen=True)
class Stage:
    orientation: str
    w: int       # 논리 캔버스 (set_mode 크기)
    h: int
    base_w: int  # 배치 토큰 기준 크기
    base_h: int
    tokens: dict = field(repr=False, compare=False)

    def layout(self, screen: str) -> dict:
        """tokens.layout[screen][지금 방향]."""
        return self.tokens["layout"][screen][self.orientation]

    def x(self, v: float, pin: str = "left") -> int:
        """기준 x → 캔버스 x (남는 폭을 left 0 · center 절반 · right 전부 더한다)."""
        return _round(v + (self.w - self.base_w) * _ADD[pin])

    def y(self, v: float, pin: str = "top") -> int:
        """기준 y → 캔버스 y (남는 높이를 top 0 · center 절반 · bottom 전부 더한다)."""
        return _round(v + (self.h - self.base_h) * _ADD[pin])

    def size(self, name: str) -> int:
        """글자 크기 토큰 (세로면 portrait_scale 배)."""
        px = self.tokens["type"]["size"][name]
        if self.orientation == "portrait":
            px = px * self.tokens["type"]["portrait_scale"]
        return _round(px)

    def rect(self) -> pygame.Rect:
        return pygame.Rect(0, 0, self.w, self.h)


def geometry(win_w: int, win_h: int, tokens: dict, force: str = "auto") -> Stage:
    """창(모니터) 크기 → 무대. force 가 landscape · portrait 이면 그 방향의 기준 크기를 그대로 쓴다."""
    w, h = max(1, win_w), max(1, win_h)
    if force in BASE:
        orientation = force
        bw, bh = BASE[orientation]
        return Stage(orientation, bw, bh, bw, bh, tokens)
    threshold = tokens["layout"]["ratio_switch"]["landscape_if_ratio_at_least"]
    orientation = "landscape" if w / h >= threshold else "portrait"
    bw, bh = BASE[orientation]
    sw, sh = float(bw), bw * h / w
    k = min(sw / bw, sh / bh)
    return Stage(orientation, _round(sw / k), _round(sh / k), bw, bh, tokens)
