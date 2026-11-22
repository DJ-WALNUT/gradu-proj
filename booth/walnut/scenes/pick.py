"""더 찍고 고르기 (extra_shots > 0) — N + extra 장 중 N 장을 고른다. 고른 순서가 컷 번호.

←→↑↓ 로 커서, Enter 로 고르기/빼기. 다 고르면 커서가 [완료] 로 간다 ([완료] 는 다 골라야 눌린다).
터치: 사진을 누르면 고르기/빼기 (커서도 그 사진으로), [완료] 를 누른다. 격자가 화면보다 길면 끌어서 줄을 옮긴다.
review_auto_sec 동안 입력이 없으면 못 고른 자리를 앞 사진부터 채워 넘어간다 (부스가 멈춰 있지 않게).
리모컨 G|순서목록|커서|필요 수 — 커서 = 사진 수 이면 [완료].
배치는 토큰 layout.pick (시안 screens/pick.js, 웹 Pick.tsx 와 같은 칸 계산).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from .. import ui
from ..remote import fmt_line
from ..stage import Stage
from ..touch import Gesture
from .base import Scene, is_key
from .capture import Shoot, cut_thumb, paper_size, thumb_crop
from .rows import RowScroll


@dataclass(frozen=True)
class PickLayout:
    cols: int
    rows: int
    cells: list[pygame.Rect]      # 사진 칸 (밀기 전 캔버스 좌표)
    paper: tuple[int, int]        # 칸 안에 들어가는 인화지 바깥 크기
    done: pygame.Rect             # [완료] 버튼
    spans: list[tuple[int, int]]  # 줄마다 (윗변, 높이) — 사진 줄들 + [완료] 줄


def pick_layout(total: int, ratio: float, stage: Stage) -> PickLayout:
    """total 장을 격자 영역에 나눠 놓는다. 가로는 cols 열, 세로는 cols ~ cols_max 중 인화지가 가장 커지는 열 수."""
    L, tk = stage.layout("pick"), stage.tokens
    gx, gy, gw, gh = L["grid"]
    gap, inset = L["gap"], L["cell_inset"]

    def grid(c: int):
        cl = max(1, min(c, total))
        rw = max(1, math.ceil(total / cl))
        w = (gw - (cl - 1) * gap) // cl
        h = (gh - (rw - 1) * gap) // rw
        return cl, rw, w, h, paper_size(ratio, (w - inset, h - inset), tk)

    best = grid(L["cols"])
    for c in range(L["cols"] + 1, L.get("cols_max", L["cols"]) + 1):
        g = grid(c)
        if g[4][1] > best[4][1]:
            best = g
    cols, rows, cw, ch, paper = best
    cells: list[pygame.Rect] = []
    for i in range(total):
        row, col = divmod(i, cols)
        in_row = min(cols, total - row * cols)
        x0 = gx + (gw - (in_row * cw + (in_row - 1) * gap)) // 2
        cells.append(pygame.Rect(stage.x(x0 + col * (cw + gap), "center"), stage.y(gy + row * (ch + gap), "center"), cw, ch))
    dw, dh = L["done_button"]
    pin = "bottom" if stage.orientation == "portrait" else "center"
    done = pygame.Rect(0, stage.y(L["done_center_y"] - dh / 2, pin), dw, dh)
    done.centerx = stage.x(stage.base_w / 2, "center")
    spans = [(cells[r * cols].top, ch) for r in range(rows)] + [(done.top, dh)]
    return PickLayout(cols, rows, cells, paper, done, spans)


class PickScene(Scene):
    layout_name = "pick"

    def __init__(self, app, shoot: Shoot):
        super().__init__(app)
        self.shoot = shoot
        self.cursor = 0
        self.auto = float(shoot.session.capture["review_auto_sec"])
        self.idle_t = 0.0
        self.thumbs: list[pygame.Surface] = []
        self.scroll = RowScroll(app.stage.tokens["touch"]["flick_project_ms"] / 1000)
        self.cols = self.rows = 1
        self.lay = pick_layout(max(1, len(shoot.session.shots)), 3 / 4, app.stage)

    def enter(self) -> None:
        """격자 배치와 썸네일을 만든다."""
        st, s = self.app.stage, self.shoot.session
        n = len(s.shots)
        self.lay = pick_layout(n, s.ratio_for_shot(0), st)
        self.cols, self.rows = self.lay.cols, self.lay.rows
        b, bb = st.tokens["print"]["border"], st.tokens["print"]["border_bottom"]
        box = (self.lay.paper[0] - 2 * b, self.lay.paper[1] - b - bb)
        # 사진마다 고른 쪽의 크롭 (찍은 그대로 → 대표 슬롯 기본 구도, AI 추천 → 구도 보정). 꺼짐이면 가운데 1배
        self.thumbs = [cut_thumb(img, s.ratio_for_shot(i), box, thumb_crop(self.app, self.shoot, i, img))
                       for i, img in enumerate(s.shots)]
        self.scroll.set_rows(self.lay.spans, st.h)
        self._sync_row()

    @property
    def done_index(self) -> int:
        return len(self.shoot.session.shots)

    def _sync_row(self) -> None:
        """커서가 있는 줄로 민다 ([완료] 는 맨 아래 줄)."""
        self.scroll.go(self.rows if self.cursor >= self.done_index else self.cursor // self.cols)

    # ---- 입력 ----
    def handle(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        self.idle_t = 0.0
        s = self.shoot.session
        n = self.done_index
        k = event.key
        if self.cursor == n:  # [완료] 에서
            if k == pygame.K_UP:
                self.cursor = n - 1
            elif is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and s.picks_complete():
                self._done()
            self._sync_row()
            return
        if k == pygame.K_LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif k == pygame.K_RIGHT:
            self.cursor = min(n - 1, self.cursor + 1)
        elif k == pygame.K_UP and self.cursor >= self.cols:
            self.cursor -= self.cols
        elif k == pygame.K_DOWN:
            self.cursor = self.cursor + self.cols if self.cursor + self.cols < n else n
        elif is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self._toggle(self.cursor)
        self._sync_row()

    def _toggle(self, i: int) -> None:
        """i 번 사진을 고르거나 뺀다. 다 고르면 커서가 [완료] 로 간다."""
        s = self.shoot.session
        self.cursor = i
        s.toggle_pick(i)
        if s.picks_complete():
            self.cursor = self.done_index

    def tap_photo(self, i: int) -> None:
        """사진을 눌렀다 — 고르기/빼기, 커서도 그 사진으로."""
        self._toggle(i)
        self._sync_row()

    def tap_done(self) -> None:
        """[완료] 를 눌렀다 — 다 골랐을 때만."""
        if self.shoot.session.picks_complete():
            self._done()

    def drag(self, g: Gesture) -> None:
        """격자가 화면보다 길 때 끌어서 줄을 옮긴다 — 놓으면 가장 가까운 줄로 맞추고 커서도 그 줄로."""
        r = self.scroll.drag(g)
        if r is not None:
            self.cursor = self.done_index if r >= self.rows else min(self.done_index - 1, r * self.cols)

    def _done(self) -> None:
        from .review import ReviewScene

        self.app.go(ReviewScene(self.app, self.shoot))

    def skip(self) -> None:
        """F2 · 시간 초과 — 못 고른 자리를 앞 사진부터 채우고 넘어간다."""
        s = self.shoot.session
        for i, order in enumerate(s.pick_order()):
            if s.picks_complete():
                break
            if order is None:
                s.toggle_pick(i)
        self._done()

    def update(self, dt: float) -> None:
        super().update(dt)
        self.idle_t += dt
        if self.idle_t >= self.auto:
            self.skip()
            return
        self.scroll.update(dt)

    def remote_state(self) -> str:
        s = self.shoot.session
        order = ",".join("-" if o is None else str(o) for o in s.pick_order())
        return fmt_line("G", order, self.cursor, s.n)

    # ---- 그리기 ----
    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles, tk = app.stage, app.theme.roles, app.stage.tokens
        L = st.layout("pick")
        s = self.shoot.session
        lay = self.lay
        key = app.input_kind == "key"
        ring = tk["touch"]["focus_ring_px"]
        gap = tk["space"]["step"][0]
        order = s.pick_order()
        picked = sum(o is not None for o in order)

        # 제목 · 고른 수는 제자리, 격자와 [완료] 줄만 밀린다
        tx, ty = L["title_pos"]
        size = st.size("headline")
        lines = ui.wrap_lines(f"넣을 사진 {s.n}장을 순서대로 골라 주세요", size, L["title_max_w"], "title")
        step_y = round(size * 1.15)
        y0 = st.y(ty) - (len(lines) - 1) * step_y // 2
        for k, line in enumerate(lines):
            ui.text(surf, line, size, roles["title"], (st.x(tx), y0 + k * step_y), anchor="midleft", face="title")
        cx, cy = L["count_pos"]
        ui.text(surf, f"{picked} / {s.n}", size, roles["title"], (st.x(cx, "right"), st.y(cy)), anchor="midright",
                face="number")

        off = round(self.scroll.pos)
        view = st.rect()
        for i, (th, o) in enumerate(zip(self.thumbs, order)):
            cell = lay.cells[i].move(0, -off)
            if not cell.colliderect(view):
                continue
            paper = ui.print_card(surf, th, cell.center, tk, roles)
            if o is not None:
                pygame.draw.rect(surf, roles["action"], paper.inflate(2 * ring, 2 * ring), ring)
            if key and i == self.cursor:
                out = paper.inflate(2 * (gap + ring), 2 * (gap + ring))
                ui.rrect(surf, roles["line"], out, tk["space"]["radius"]["card"] + gap + ring, ring)
            if o is not None:
                ui.number_badge(surf, (paper.right - L["badge_at"], paper.y + L["badge_at"]), L["badge_r"], o + 1, roles,
                                kind="order", size=st.size("body"))
            self.hit(cell.clip(view), lambda i=i: self.tap_photo(i))
        done = lay.done.move(0, -off)
        complete = s.picks_complete()
        ui.action_button(surf, done, "완료", roles, kind="action" if complete else "line",
                         focused=key and self.cursor == self.done_index, enabled=complete, ring=ring, size=st.size("button"))
        self.hit(done.clip(view), self.tap_done)
