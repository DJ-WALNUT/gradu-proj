"""대기 화면 — 행사 제목·부제·로고·시작 문구·개인정보 문구. Enter/Space 나 시작 버튼 탭으로 촬영을 시작한다 (버튼 밖 바탕은 시작하지 않는다).

배치 · 크기는 토큰(layout.idle), 시안은 shared/booth-design/mockups/screens/idle.js, 웹 구현은 booth-web/src/screens/Idle.tsx.
"""

from __future__ import annotations

import math

import pygame

from .. import fieldlog, sfx, ui
from ..remote import fmt_line
from .base import Scene, is_key, pulse

TITLE_LINE = 1.1    # 제목 줄 높이 (글자 크기 배)
SUB_LINE = 1.35


class IdleScene(Scene):
    idle = True
    layout_name = "idle"

    def __init__(self, app):
        super().__init__(app)
        self.logo = None
        self._logo_key = None
        self._button: ui.ScaledSprite | None = None
        self._button_key = None

    def _logo_for(self, box: tuple[int, int]) -> pygame.Surface | None:
        """로고를 box 안에 비율 유지로 줄인다 (키우지 않음). 같은 입력이면 다시 만들지 않는다."""
        src = self.app.theme.logo
        if src is None:
            return None
        key = (id(src), box)
        if key != self._logo_key:
            w, h = src.get_size()
            k = min(box[0] / w, box[1] / h, 1.0)
            self.logo = pygame.transform.smoothscale(src, (max(1, int(w * k)), max(1, int(h * k))))
            self._logo_key = key
        return self.logo

    def start_rect(self) -> pygame.Rect:
        """시작 버튼이 가장 커졌을 때의 자리 — 탭 영역. 숨쉬어도 움직이지 않는다."""
        st = self.app.stage
        L = st.layout("idle")
        peak = st.tokens["motion"]["breath"]["scale"]
        bw, bh = L["start_button"]
        pin = "bottom" if st.orientation == "portrait" else "center"
        r = pygame.Rect(0, 0, round(bw * peak), round(bh * peak))
        r.center = (st.x(st.base_w / 2, "center"), st.y(L["start_button_center_y"], pin))
        return r

    def _button_for(self, rect: pygame.Rect) -> ui.ScaledSprite:
        """가장 커졌을 때 크기로 버튼을 한 번 그려 둔다. 같은 입력이면 다시 그리지 않는다."""
        app = self.app
        th, st = app.theme, app.stage
        roles = th.roles
        focused = app.input_kind == "key"
        ring = st.tokens["touch"]["focus_ring_px"]
        size = round(st.size("headline") * st.tokens["motion"]["breath"]["scale"])
        key = (rect.size, th.start_text, roles["action"], roles.get("action_edge"), roles["on_action"], focused, ring, size)
        if key != self._button_key:
            pad = ui.focus_margin(ring) + 1  # 고리 + 축소할 때 가장자리가 섞일 한 칸
            canvas = pygame.Surface((rect.w + 2 * pad, rect.h + 2 * pad), pygame.SRCALPHA)
            ui.action_button(canvas, pygame.Rect(pad, pad, rect.w, rect.h), th.start_text, roles,
                             focused=focused, ring=ring, size=size)
            self._button = ui.ScaledSprite(canvas)
            self._button_key = key
        return self._button

    def start(self) -> None:
        """촬영 시작 — 키와 탭이 같이 쓴다."""
        sfx.play("go")
        self.app.start_shoot()

    def handle(self, event: pygame.event.Event) -> None:
        if is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.start()

    def remote_state(self) -> str:
        return fmt_line("I", self.app.theme.title)

    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        th, st = app.theme, app.stage
        roles, L = th.roles, st.layout("idle")
        cx = st.x(st.base_w / 2, "center")

        pad = st.tokens["space"]["step"]
        note_y = pad[4]
        if app.local:  # 연결 없이 사용 중 — 맨 위에 작게 알린다
            ui.text(surf, app.local_note(), st.size("label"), roles["hint"], (cx, note_y), face="label",
                    max_width=st.w - 2 * pad[5])
            note_y += round(st.size("label") * 1.5)
        if getattr(app, "samples", None) is not None:  # 현장 시험 샘플 모드 — 손님(동의한 지인)에게 알린다
            ui.text(surf, fieldlog.SAMPLE_NOTE, st.size("label"), roles["hint"], (cx, note_y), face="label",
                    max_width=st.w - 2 * pad[5])

        # 로고 — 있으면 제목 덩어리가 로고 아래로 내려간다
        shift = 0
        logo = self._logo_for(tuple(L["logo_box"]))
        if logo is not None:
            surf.blit(logo, logo.get_rect(midtop=(cx, st.y(L["logo_top"], "center"))))
            shift = L["logo_top"] + logo.get_height() + L["logo_gap"] - L["head_top"]

        # 제목 + 부제 — 제목이 두 줄이 되면 부제가 아래로 밀린다. 첫 줄 가운데가 기준 y
        ts = st.size("display")
        tl = ui.wrap_lines(th.title, ts, L["title_max_w"], "title")
        step = int(ts * TITLE_LINE)
        y0 = st.y(L["title_y"] + shift, "center")
        for i, line in enumerate(tl):
            ui.text(surf, line, ts, roles["title"], (cx, y0 + i * step), face="title")
        if th.subtitle:
            ss = st.size("button")
            sy = y0 + (L["subtitle_y"] - L["title_y"]) + (len(tl) - 1) * step
            for i, line in enumerate(ui.wrap_lines(th.subtitle, ss, L["subtitle_max_w"], "body")):
                ui.text(surf, line, ss, roles["title"], (cx, sy + int(i * ss * SUB_LINE)))

        # 시작 버튼: 숨쉬듯 커졌다 작아지는 알약 (웹 g-pulse 와 같은 토큰). 탭은 이 버튼만 받는다
        breath = st.tokens["motion"]["breath"]
        btn = self.start_rect()
        self.hit(btn, self.start)
        k = 1 + (breath["scale"] - 1) * pulse(self.t, math.pi * 1000 / breath["half_ms"])
        self._button_for(btn).blit(surf, btn.center, k / breath["scale"])

        if th.privacy_text and not app.local:  # 연결 없이 쓸 때는 QR · 보관 문구가 사실이 아니다 (위 안내가 대신한다)
            cs = st.size("credit")
            gap = st.tokens["space"]["step"][1]  # 표기와 겹치지 않게 한 칸 띄운다
            cap = surf.get_height() - st.tokens["credit"]["bottom"] - cs - gap - st.size("caption") // 2
            y = min(st.y(st.base_h - L["privacy_bottom"], "bottom"), cap)
            ui.text(surf, th.privacy_text, st.size("caption"), roles["hint"], (cx, y), max_width=st.w - 2 * st.tokens["space"]["step"][5])
