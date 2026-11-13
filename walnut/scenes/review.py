"""완성 확인 — 합성본 인화지, [QR 받기] (+ 다시 찍을 수 있으면 [다시 찍기]).

review_auto_sec 동안 입력이 없으면 QR 받기로 넘어간다 (키 · 탭 · 끌기마다 처음부터 다시 센다).
키(Enter)와 탭은 같은 press() 를 부른다 — 탭은 바로 실행한다.
배치는 토큰 layout.review (시안 screens/review.js, 웹 Review.tsx 와 같다).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import pygame
from PIL import Image

from .. import ui
from ..compose import compose
from ..remote import fmt_line
from ..stage import Stage
from .base import Scene, fit_surface, is_key
from .capture import Shoot, paper_size

LABELS = {"qr": "QR 받기", "retake": "다시 찍기"}
HINT_KEY = "고르고 버튼을 눌러 결정"
HINT_TOUCH = "버튼을 눌러 주세요"  # 웹 부스 Review.tsx 와 같은 문구


@dataclass(frozen=True)
class ReviewLayout:
    paper: pygame.Rect            # 완성본 인화지 (바깥 크기)
    buttons: list[pygame.Rect]    # [QR 받기] (+ [다시 찍기])
    auto_pos: tuple[int, int]     # 남은 초 줄 가운데
    hint_pos: tuple[int, int] | None  # 아래 안내 줄 (가로만)


def review_layout(stage: Stage, ratio: float, n_buttons: int) -> ReviewLayout:
    L = stage.layout("review")
    low = "bottom" if stage.orientation == "portrait" else "center"
    pw, ph = paper_size(ratio, tuple(L["preview_box"]), stage.tokens)
    paper = pygame.Rect(0, 0, pw, ph)
    paper.center = (stage.x(L["preview_center"][0], "center"), stage.y(L["preview_center"][1], "center"))
    bw, bh = L["button_size"]
    bx, top = stage.x(L["buttons_x"], "center"), stage.y(L["buttons_top"], low)
    buttons = [pygame.Rect(bx, top + i * L["button_step"], bw, bh) for i in range(n_buttons)]
    auto = (bx + bw // 2, stage.y(L["hint_y"], low))
    hint = None
    if L.get("hint_bottom"):
        cap = stage.h - stage.tokens["credit"]["bottom"] - stage.size("credit") - stage.tokens["space"]["step"][1] \
            - stage.size("body") // 2  # 표기 위로만
        hint = (bx + bw // 2, min(stage.y(stage.base_h - L["hint_bottom"], "bottom"), cap))
    return ReviewLayout(paper, buttons, auto, hint)


class ReviewScene(Scene):
    layout_name = "review"

    def __init__(self, app, shoot: Shoot, collage: Image.Image | None = None):
        super().__init__(app)
        self.shoot = shoot
        s = shoot.session
        if collage is not None:
            self.collage = collage
        else:
            t0 = time.perf_counter()
            cuts = s.cuts()
            self.collage = compose(shoot.frame_png, s.frame["slots"], cuts)
            app.capture_log.write({
                "type": "baseline", "compose_ms": (time.perf_counter() - t0) * 1000,
                "cuts": len(cuts), "collage": [self.collage.width, self.collage.height],
                "display_fps": app.fps, "camera_fps": app.camera.fps,
            })
        self.buttons = ["qr"] + (["retake"] if s.can_retake() else [])
        self.sel = 0
        self.auto = float(s.capture["review_auto_sec"])
        self.idle_t = 0.0
        st = app.stage
        self.lay = review_layout(st, self.collage.width / self.collage.height, len(self.buttons))
        b, bb = st.tokens["print"]["border"], st.tokens["print"]["border_bottom"]
        self.preview = fit_surface(self.collage, (self.lay.paper.w - 2 * b, self.lay.paper.h - b - bb))

    def handle(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        self.idle_t = 0.0
        if is_key(event, pygame.K_LEFT, pygame.K_UP):
            self.sel = (self.sel - 1) % len(self.buttons)
        elif is_key(event, pygame.K_RIGHT, pygame.K_DOWN):
            self.sel = (self.sel + 1) % len(self.buttons)
        elif is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.press(self.buttons[self.sel])

    def press(self, name: str) -> None:
        """버튼 하나를 누른다 (Enter · 탭이 같이 쓴다). 커서도 그 버튼으로."""
        if name not in self.buttons:
            return
        self.sel = self.buttons.index(name)
        if name == "retake":
            from .retake import RetakeScene

            self.app.go(RetakeScene(self.app, self.shoot, self.collage))
        else:
            self.skip()

    def skip(self) -> None:
        """QR 받기 (F2 도 같다)."""
        from .share import finish

        finish(self.app, self.collage)

    def update(self, dt: float) -> None:
        super().update(dt)
        self.idle_t += dt
        if self.idle_t >= self.auto:
            self.skip()

    def left(self) -> int:
        return max(0, math.ceil(self.auto - self.idle_t))

    def remote_state(self) -> str:
        return fmt_line("V", self.sel, self.left(), int(self.auto), len(self.buttons))

    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles, tk = app.stage, app.theme.roles, app.stage.tokens
        L, lay = st.layout("review"), self.lay
        key = app.input_kind == "key"
        self.hit(surf.get_rect(), lambda: None)  # 빈 곳을 눌러도 자동 진행 타이머는 처음부터 (poke 만)

        tx, ty = L["title_pos"]
        ui.text(surf, "이렇게 완성됐어요!", st.size("title"), roles["title"], (st.x(tx), st.y(ty)), anchor="midleft", face="title")
        ui.print_card(surf, self.preview, lay.paper.center, tk, roles)

        for i, (name, rect) in enumerate(zip(self.buttons, lay.buttons)):
            ui.action_button(surf, rect, LABELS[name], roles, kind="action" if i == 0 else "line",
                             focused=key and i == self.sel, ring=tk["touch"]["focus_ring_px"], size=st.size("button"))
            self.hit(rect, lambda name=name: self.press(name))

        ui.text(surf, f"{self.left()}초 뒤 자동으로 QR 을 보여 드려요", st.size("label"), roles["hint"], lay.auto_pos,
                max_width=L["button_size"][0])
        if lay.hint_pos:
            ui.text(surf, HINT_KEY if key else HINT_TOUCH, st.size("body"), roles["hint"], lay.hint_pos, face="label",
                    max_width=L["button_size"][0])
