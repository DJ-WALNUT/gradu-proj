"""장면 공통 — Scene."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame
from PIL import Image

from .. import ui
from ..touch import Gesture, HitMap

if TYPE_CHECKING:
    from ..app import App


class Scene:
    layout_name: str | None = None  # 공용 표기가 따를 배치 토큰 이름 (credit_x · credit_bottom)
    idle = False  # True 인 장면에서만 새 번들로 바꾼다 (촬영 도중 교체 금지)

    def __init__(self, app: "App"):
        self.app = app
        self.t = 0.0
        self.hits = HitMap()  # 그릴 때마다 draw 가 다시 등록한다 (App._draw 가 그리기 전에 비운다)

    def hit(self, rect, action) -> None:
        """탭을 받을 영역을 등록한다. 탭이 닿으면 poke() 를 먼저 부르고 action 을 실행한다."""
        def run() -> None:
            self.poke()
            action()
        self.hits.add(pygame.Rect(rect), run)

    def poke(self) -> None:
        """입력이 있었음을 알린다 — 무입력 자동 진행 타이머를 되돌린다."""
        if hasattr(self, "idle_t"):
            self.idle_t = 0.0

    def drag(self, g: Gesture) -> None:
        """끌기 · 끌기 끝 (기본은 아무것도 안 한다)."""

    def enter(self) -> None: ...

    def exit(self) -> None: ...

    def handle(self, event: pygame.event.Event) -> None: ...

    def update(self, dt: float) -> None:
        self.t += dt

    def draw(self, surf: pygame.Surface) -> None: ...

    def skip(self) -> None:
        """관리자 '건너뛰기' (F2)."""

    def remote_state(self) -> str:
        """리모컨 OLED 에 보낼 한 줄 (스펙 7.1). '-' 는 '그 밖의 장면'."""
        return "-"


def is_key(event: pygame.event.Event, *keys: int) -> bool:
    return event.type == pygame.KEYDOWN and event.key in keys


def pulse(t: float, speed: float = 3.0) -> float:
    """0~1 사이를 오가는 값 (맥박 연출)."""
    return 0.5 + 0.5 * math.sin(t * speed)


def fit_surface(img, box: tuple[int, int]) -> pygame.Surface:
    """PIL 이미지를 box 안에 비율 그대로 맞춘 Surface."""
    k = min(box[0] / img.width, box[1] / img.height)
    size = (max(1, int(img.width * k)), max(1, int(img.height * k)))
    return ui.pil_to_surface(img.resize(size, Image.Resampling.LANCZOS))
