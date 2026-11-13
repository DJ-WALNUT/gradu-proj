"""다시 찍을 컷 고르기 (extra_shots == 0, allow_retake).

컷마다 남기기/다시 찍기 토글 (기본 전부 남기기), 아래에 [다시 찍기] [취소]. 컷이 한 화면보다 많으면 줄이 여럿이고
제목 · 컷 줄 · 버튼 줄이 한 지도로 함께 밀린다 (끌거나, 커서가 줄을 옮기면 그 줄이 창 가운데로).
다시 찍을 컷이 없으면 [다시 찍기] 는 눌리지 않는다. 다시 찍기 → 고르지 않은 컷만 그 자리에 재촬영 → 확인.
터치: 컷을 누르면 남기기/다시 찍기, 버튼을 누른다.
review_auto_sec 동안 입력이 없으면 지금 합성본으로 완료한다.
리모컨 P|비트열|커서|줄|버튼 — 비트 1 남기기 · 0 다시 찍기, 줄 0 컷 · 1 버튼, 버튼 0 다시 찍기 · 1 취소.
배치는 토큰 layout.retake (시안 screens/retake.js, 웹 Retake.tsx 와 같다).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame
from PIL import Image

from .. import ui
from ..remote import fmt_line
from ..stage import Stage
from ..touch import Gesture
from .base import Scene, is_key
from .capture import CaptureScene, Shoot, cut_thumb, paper_size
from .rows import RowScroll

HINT_CUTS = "좌우로 컷을 고르고 버튼으로 남기기/다시 찍기, 아래로 내려가 시작"
HINT_BUTTONS = "좌우로 고르고 버튼, 위로 올라가 컷 고르기"
HINT_TOUCH = "다시 찍을 컷을 누르고 아래 버튼을 눌러 주세요"  # 웹 부스 Retake.tsx 와 같은 문구


@dataclass(frozen=True)
class RetakeLayout:
    cols: int
    cuts: list[pygame.Rect]       # 컷마다 인화지 (밀기 전 캔버스 좌표)
    cells: list[pygame.Rect]      # 컷마다 누르는 칸 (인화지 + 아래 표시)
    row_h: int
    start: pygame.Rect            # [다시 찍기]
    cancel: pygame.Rect           # [취소]
    spans: list[tuple[int, int]]  # 줄마다 (윗변, 높이) — 컷 줄들 + 버튼 줄
    view_h: int                   # 지도를 보는 창 높이 (안내 줄 위까지)
    scroll_over: int              # 지도가 창보다 긴 만큼


def retake_layout(ratios: list[float], stage: Stage) -> RetakeLayout:
    """컷 비율마다 인화지를 thumb_box 안에 맞추고, 칸 폭 · 줄 높이는 가장 큰 인화지로 한다."""
    L, tk = stage.layout("retake"), stage.tokens
    n = len(ratios)
    cols = max(1, min(n, L["cols"]))
    sizes = [paper_size(r, tuple(L["thumb_box"]), tk) for r in ratios]
    pw, ph = max(z[0] for z in sizes), max(z[1] for z in sizes)
    row_h = ph + L["label_dy"] * 2
    gap = L["col_gap"]
    pitch = row_h + gap
    cut_rows = max(1, math.ceil(n / cols))
    cuts: list[pygame.Rect] = []
    cells: list[pygame.Rect] = []
    for i, (w, h) in enumerate(sizes):
        row, col = divmod(i, cols)
        in_row = min(cols, n - row * cols)
        rx = (stage.base_w - (in_row * pw + (in_row - 1) * gap)) // 2
        cell = pygame.Rect(stage.x(rx + col * (pw + gap), "center"), stage.y(L["rows_top"] + row * pitch, "center"), pw, row_h)
        cells.append(cell)
        cuts.append(pygame.Rect(cell.x + (pw - w) // 2, cell.y, w, h))

    (w0, h0), (w1, h1) = L["button_sizes"]
    last_bottom = L["rows_top"] + (cut_rows - 1) * pitch + row_h
    if stage.orientation == "portrait":
        follow = last_bottom + gap > L["buttons_y"] - h0 / 2  # 컷 줄 뒤를 따라가면 컷 줄과 같은 핀, 아니면 엄지가 닿는 아래
        top = stage.y(last_bottom + gap, "center") if follow else stage.y(L["buttons_y"] - h0 / 2, "bottom")
        start = pygame.Rect(0, top, w0, h0)
        cancel = pygame.Rect(0, top + h0 + L.get("button_gap", 0), w1, h1)
        btn_h = cancel.bottom - top
    else:
        top = stage.y(max(L["buttons_y"], last_bottom + gap + h0 / 2) - h0 / 2, "center")
        start = pygame.Rect(0, top, w0, h0)
        cancel = pygame.Rect(0, top, w1, h1)
        btn_h = h0
    start.centerx = stage.x(L["button_centers_x"][0], "center")
    cancel.centerx = stage.x(L["button_centers_x"][1], "center")
    spans = [(cells[r * cols].top, row_h) for r in range(cut_rows)] + [(top, btn_h)]
    view_h = stage.h - L["map_bottom"]
    return RetakeLayout(cols, cuts, cells, row_h, start, cancel, spans, view_h,
                        max(0, max(t + h for t, h in spans) - view_h))


class RetakeScene(Scene):
    layout_name = "retake"

    def __init__(self, app, shoot: Shoot, collage: Image.Image):
        super().__init__(app)
        self.shoot = shoot
        self.collage = collage
        s = shoot.session
        self.keep = [True] * s.n
        self.cursor = 0
        self.row = 0   # 0 컷 · 1 버튼
        self.btn = 0   # 0 다시 찍기 · 1 취소
        self.auto = float(s.capture["review_auto_sec"])
        self.idle_t = 0.0
        st = app.stage
        self.lay = retake_layout([s.ratio_for_shot(i) for i in range(s.n)], st)
        self.scroll = RowScroll(st.tokens["touch"]["flick_project_ms"] / 1000)
        self.scroll.set_rows(self.lay.spans, self.lay.view_h)
        b, bb = st.tokens["print"]["border"], st.tokens["print"]["border_bottom"]
        self.thumbs = [cut_thumb(img, s.ratio_for_shot(i), (r.w - 2 * b, r.h - b - bb))
                       for i, (img, r) in enumerate(zip(s.shots, self.lay.cuts))]

    def can_retake(self) -> bool:
        return not all(self.keep)

    def _sync_row(self) -> None:
        """지금 있는 줄 (커서의 컷 줄 또는 버튼 줄) 로 민다."""
        self.scroll.go(len(self.lay.spans) - 1 if self.row == 1 else self.cursor // self.lay.cols)

    # ---- 입력 ----
    def handle(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        self.idle_t = 0.0
        dx = {pygame.K_LEFT: -1, pygame.K_RIGHT: 1}.get(event.key, 0)
        ok = is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)
        if self.row == 0:
            if dx:
                self.cursor = max(0, min(len(self.keep) - 1, self.cursor + dx))
            elif event.key == pygame.K_DOWN:
                self.row = 1
            elif ok:
                self.keep[self.cursor] = not self.keep[self.cursor]
        else:
            if dx:
                self.btn = max(0, min(1, self.btn + dx))
            elif event.key == pygame.K_UP:
                self.row = 0
            elif ok and self.btn == 1:
                self._back()
            elif ok and self.can_retake():
                self._retake()
        self._sync_row()

    def tap_cut(self, i: int) -> None:
        """컷을 눌렀다 — 남기기 ↔ 다시 찍기, 커서도 그 컷으로."""
        self.row, self.cursor = 0, i
        self.keep[i] = not self.keep[i]
        self._sync_row()

    def tap_retake(self) -> None:
        """[다시 찍기] 를 눌렀다 — 다시 찍을 컷이 있을 때만."""
        if not self.can_retake():
            return
        self.row, self.btn = 1, 0
        self._sync_row()
        self._retake()

    def tap_back(self) -> None:
        """[취소] 를 눌렀다."""
        self.row, self.btn = 1, 1
        self._sync_row()
        self._back()

    def drag(self, g: Gesture) -> None:
        """지도가 창보다 길 때 끌어서 줄을 옮긴다 — 놓으면 가장 가까운 줄로 맞추고 커서도 그 줄로."""
        r = self.scroll.drag(g)
        if r is None:
            return
        if r >= len(self.lay.spans) - 1:
            self.row, self.btn = 1, 0
        else:
            self.row = 0
            self.cursor = min(len(self.keep) - 1, r * self.lay.cols + self.cursor % self.lay.cols)

    def _retake(self) -> None:
        self.shoot.session.begin_retake(self.keep)
        self.app.go(CaptureScene(self.app, self.shoot))

    def _back(self) -> None:
        from .review import ReviewScene

        self.app.go(ReviewScene(self.app, self.shoot, self.collage))

    def skip(self) -> None:
        """F2 — 지금 합성본으로 완료."""
        from .share import finish

        finish(self.app, self.collage)

    def update(self, dt: float) -> None:
        super().update(dt)
        self.idle_t += dt
        if self.idle_t >= self.auto:
            self.skip()
            return
        self.scroll.update(dt)

    def remote_state(self) -> str:
        bits = "".join("1" if k else "0" for k in self.keep)
        return fmt_line("P", bits, self.cursor, self.row, self.btn)

    # ---- 그리기 ----
    def _hint(self) -> str:
        if self.app.input_kind != "key":
            return HINT_TOUCH
        return HINT_CUTS if self.row == 0 else HINT_BUTTONS

    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles, tk = app.stage, app.theme.roles, app.stage.tokens
        L = st.layout("retake")
        lay = self.lay
        key = app.input_kind == "key"
        ring, step = tk["touch"]["focus_ring_px"], tk["space"]["step"]
        gap = step[0]
        off = round(self.scroll.pos)
        view = pygame.Rect(0, 0, st.w, lay.view_h)
        fx = tk["color"]["fixed"]

        # 지도 — 제목 · 컷 줄 · 버튼 줄이 함께 밀린다 (안내 줄 위까지만 보인다)
        clip = surf.get_clip()
        surf.set_clip(view)
        tx, ty = L["title_pos"]
        size = st.size("title")
        lines = ui.wrap_lines("다시 찍을 컷을 골라 주세요", size, st.w - st.x(tx) - step[4], "title")
        step_y = round(size * 1.15)
        y0 = st.y(ty) - off - (len(lines) - 1) * step_y // 2
        for k, line in enumerate(lines):
            ui.text(surf, line, size, roles["title"], (st.x(tx), y0 + k * step_y), anchor="midleft", face="title")

        for i, (th, r) in enumerate(zip(self.thumbs, lay.cuts)):
            cell, paper_r = lay.cells[i].move(0, -off), r.move(0, -off)
            if not cell.colliderect(view):
                continue
            paper = ui.print_card(surf, th, paper_r.center, tk, roles)
            keep = self.keep[i]
            if not keep:
                b, bb = tk["print"]["border"], tk["print"]["border_bottom"]
                photo = pygame.Rect(paper.x + b, paper.y + b, paper.w - 2 * b, paper.h - b - bb)
                dim = pygame.Surface(photo.size, pygame.SRCALPHA)
                dim.fill((*ui.hex_rgb(fx["dark_ink"]), int(255 * tk["color"]["alpha"]["dim"] + 0.5)))
                surf.blit(dim, photo)
                ui.text(surf, "다시 찍기", st.size("body"), ui.hex_rgb(fx["light_ink"]), photo.center, face="title",
                        max_width=photo.w - 2 * step[1])
            if key and self.row == 0 and i == self.cursor:
                out = paper.inflate(2 * (gap + ring), 2 * (gap + ring))
                ui.rrect(surf, roles["line"], out, tk["space"]["radius"]["card"] + gap + ring, ring)
            ui.number_badge(surf, (paper.x + L["badge_at"], paper.y + L["badge_at"]), L["badge_r"], i + 1, roles,
                            kind="cut", size=st.size("label"))
            label = "남기기" if keep else "다시 찍기"
            tag_c = (paper.centerx, paper.top + (r.h + L["label_dy"]))
            img = ui.font(st.size("body"), "title", label).render(label, True, roles["on_action"] if not keep else roles["title"])
            if not keep:
                pill = img.get_rect().inflate(2 * step[2], step[0])
                pill.center = tag_c
                ui.rrect(surf, roles["action"], pill, pill.height // 2)
            surf.blit(img, img.get_rect(center=tag_c))
            self.hit(cell.clip(view), lambda i=i: self.tap_cut(i))

        k = self.keep.count(False)
        for j, (rect, label) in enumerate(((lay.start, f"{k}컷 다시 찍기" if k else "컷을 골라 주세요"), (lay.cancel, "취소"))):
            rect = rect.move(0, -off)
            ui.action_button(surf, rect, label, roles, kind="action" if j == 0 and k else "line",
                             focused=key and self.row == 1 and self.btn == j, enabled=j == 1 or self.can_retake(),
                             ring=ring, size=st.size("button"))
            self.hit(rect.clip(view), self.tap_retake if j == 0 else self.tap_back)
        surf.set_clip(clip)

        size = st.size("label")
        cap = st.h - tk["credit"]["bottom"] - st.size("credit") - step[1] - size // 2  # 표기 위로만
        y = min(st.y(st.base_h - L["hint_bottom"], "bottom"), cap)
        ui.text(surf, self._hint(), size, roles["hint"], (st.w / 2, y), face="label", max_width=st.w - 2 * step[4])
