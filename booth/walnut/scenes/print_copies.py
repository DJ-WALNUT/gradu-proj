"""인쇄 매수 — 1~copies_max 를 고르고 [(n)장 인쇄] 로 인쇄한 뒤 대기 화면. 30초 입력이 없으면 인쇄 없이 대기 화면.

키: ↑→ 한 장 더, ↓← 한 장 덜, Enter 인쇄. 터치: 동그라미 양옆 ◀ ▶ 로 매수를, 아래 버튼으로 인쇄.
가운데 동그라미는 매수 표시일 뿐 버튼이 아니다. 배치는 토큰 layout.print_copies (시안 screens/print_copies.js).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pygame
from PIL import Image

from .. import ui
from ..remote import fmt_line
from ..stage import Stage
from .base import Scene, is_key

log = logging.getLogger(__name__)

IDLE_TIMEOUT = 30.0
HINT_KEY = "최대 {max}장  ·  위아래로 고르고 버튼을 눌러 인쇄"
HINT_TOUCH = "최대 {max}장  ·  ◀ ▶ 를 눌러 고르고 아래 버튼을 눌러 인쇄"


@dataclass(frozen=True)
class PrintLayout:
    center: tuple[int, int]
    r: int
    less: pygame.Rect      # ◀ 누르는 칸
    more: pygame.Rect      # ▶ 누르는 칸
    confirm: pygame.Rect   # [(n)장 인쇄]


def print_layout(stage: Stage) -> PrintLayout:
    L = stage.layout("print_copies")
    low = "bottom" if stage.orientation == "portrait" else "center"
    cx, cy = stage.x(stage.base_w / 2, "center"), stage.y(L["center"][1], "center")
    hit = L["arrow_hit"]

    def box(dx: int) -> pygame.Rect:
        r = pygame.Rect(0, 0, hit, hit)
        r.center = (cx + dx, cy)
        return r

    bw, bh = L["print_button"]
    confirm = pygame.Rect(0, 0, bw, bh)
    confirm.center = (cx, stage.y(L["print_button_y"], low))
    return PrintLayout((cx, cy), L["circle_r"], box(-L["arrow_offset"]), box(L["arrow_offset"]), confirm)


class PrintCopiesScene(Scene):
    layout_name = "print_copies"

    def __init__(self, app, collage: Image.Image, token: str, url: str | None = None):
        super().__init__(app)
        self.collage = collage
        self.token = token
        self.url = url  # 공유 화면의 QR 주소 — 영수증 아래에 QR 로 찍는다 (없으면 사진 + 이름 · 날짜만)
        self.max = int(app.bundle.settings["print"]["copies_max"])
        self.copies = 1
        self.idle_t = 0.0
        self.lay = print_layout(app.stage)

    def set_copies(self, n: int) -> None:
        """매수를 1~max 안으로 맞춰 바꾼다 (키 · 탭이 같이 쓴다)."""
        self.copies = max(1, min(self.max, int(n)))

    def confirm(self) -> None:
        """지금 매수로 인쇄하고 대기 화면으로."""
        self.app.printer.print(self.collage, self.copies, token=self.token, url=self.url)
        self.app.home()

    def handle(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        self.idle_t = 0.0
        if is_key(event, pygame.K_UP, pygame.K_RIGHT):
            self.set_copies(self.copies + 1)
        elif is_key(event, pygame.K_DOWN, pygame.K_LEFT):
            self.set_copies(self.copies - 1)
        elif is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.confirm()

    def skip(self) -> None:
        """F2 — 인쇄 없이 대기 화면."""
        self.app.home()

    def update(self, dt: float) -> None:
        super().update(dt)
        self.idle_t += dt
        if self.idle_t >= IDLE_TIMEOUT:
            log.info("인쇄 매수 입력이 없어 인쇄하지 않고 돌아갑니다")
            self.app.home()

    def remote_state(self) -> str:
        return fmt_line("Q", self.copies, self.max)

    def _arrow(self, surf: pygame.Surface, rect: pygame.Rect, direction: str, on: bool) -> None:
        st, roles = self.app.stage, self.app.theme.roles
        size = st.layout("print_copies")["arrow_size"]
        if on:
            ui.arrow(surf, rect.center, size, direction, roles["line"])
            return
        box = pygame.Rect(0, 0, size + 2, size + 2)  # 화살표가 들어가는 작은 층만 (화면 크기 면을 프레임마다 만들지 않는다)
        box.center = rect.center
        layer = pygame.Surface(box.size, pygame.SRCALPHA)
        ui.arrow(layer, (box.w / 2, box.h / 2), size, direction, (*roles["hint"], 255))
        layer.fill((255, 255, 255, int(255 * st.tokens["color"]["alpha"]["muted"] + 0.5)), special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(layer, box)

    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles, tk = app.stage, app.theme.roles, app.stage.tokens
        L, lay = st.layout("print_copies"), self.lay
        key = app.input_kind == "key"
        low = "bottom" if st.orientation == "portrait" else "center"
        cx = lay.center[0]
        self.hit(surf.get_rect(), lambda: None)  # 빈 곳을 눌러도 30초 타이머는 처음부터 (poke 만)

        ui.text(surf, "몇 장 인쇄할까요?", st.size("question"), roles["title"], (cx, st.y(L["title_y"], "top")), face="title",
                max_width=L["text_max_w"])
        # 매수 표시 — 강조색이 아니라 테두리형 (지금 누를 것은 아래 버튼 하나)
        ui.circle(surf, roles["line"], lay.center, lay.r, tk["touch"]["focus_ring_px"])
        ui.text(surf, str(self.copies), round(lay.r * L["digit_ratio"]), roles["title"], lay.center, face="number", ink=True)
        self._arrow(surf, lay.less, "left", self.copies > 1)
        self._arrow(surf, lay.more, "right", self.copies < self.max)
        self.hit(lay.less, lambda: self.set_copies(self.copies - 1))
        self.hit(lay.more, lambda: self.set_copies(self.copies + 1))

        hint = (HINT_KEY if key else HINT_TOUCH).format(max=self.max)
        ui.text(surf, hint, st.size("body"), roles["hint"], (cx, st.y(L["help_y"], "center")), face="label", max_width=L["text_max_w"])

        ui.action_button(surf, lay.confirm, f"{self.copies}장 인쇄", roles, focused=key, ring=tk["touch"]["focus_ring_px"],
                         size=st.size("button"))
        self.hit(lay.confirm, self.confirm)

        left = max(0, math.ceil(IDLE_TIMEOUT - self.idle_t))
        ui.text(surf, f"{left}초 동안 누르지 않으면 인쇄하지 않고 처음 화면으로", st.size("caption"), roles["hint"],
                (cx, st.y(L["timeout_y"], low)), max_width=L["text_max_w"])
