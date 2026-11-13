"""고르기 — 필터(F) · 스티커(K) · 프레임(R). ←→ 로 고르고 Enter, 또는 눌러서 고르고 가운데 항목을 한 번 더 누른다.

필터는 실시간 카메라에 그 필터를 입힌 미리보기, 스티커는 얼굴 추적 미리보기(앞에서 고른 필터 포함),
프레임은 프레임 PNG 축소판과 'N컷'. 선택지가 하나뿐인 단계는 App.start_shoot 이 건너뛴다.
"""

from __future__ import annotations

import logging
import math

import pygame
from PIL import Image

from .. import ui
from ..remote import fmt_line
from ..settings import cut_count
from ..touch import Gesture
from .base import Scene, is_key
from .capture import LiveView, draw_live

log = logging.getLogger(__name__)

FILTER_LABELS = {"original": "원본", "mono": "흑백", "bright": "화사하게", "warm": "따뜻하게",
                 "cool": "시원하게", "vintage": "빈티지"}
TITLES = {"F": "필터를 골라 주세요", "K": "스티커를 골라 주세요", "R": "프레임을 골라 주세요"}
LIVE_RATIO = 3 / 4
THUMB_SRC_H = 760    # 프레임 축소판 원본 높이 — 배치 토큰의 thumb_h 로 다시 줄여 쓴다
CHOOSE_IDLE_SEC = 120  # 입력이 이만큼 없으면 대기로 돌아간다 (웹 부스 CHOOSE_IDLE_SEC 와 같다)
HINT_KEY = "좌우로 고르고 버튼을 눌러 결정"
HINT_TOUCH = "눌러서 고르고, 가운데 항목을 한 번 더 누르면 결정"  # 웹 부스 Choose.tsx 와 같은 문구
EASE_RATE = 14.0     # 목록이 고른 항목으로 미끄러지는 빠르기 (클수록 빠름)

Option = tuple[object, str]  # (값, 화면 이름)


def shoot_options(app) -> dict[str, list[Option]]:
    """단계별 선택지. 스티커는 행사에서 켰고 항목이 있고 얼굴 인식을 쓸 수 있을 때만 ('없음' + 항목)."""
    s = app.bundle.settings
    opts: dict[str, list[Option]] = {
        "F": [(f, FILTER_LABELS.get(f, f)) for f in s["filters"]["enabled"]],
        "K": [],
        "R": [(i, str(fr.get("name") or f"프레임 {i + 1}")) for i, fr in enumerate(app.bundle.frames)],
    }
    if app.stickers and app.detector.available:
        opts["K"] = [(None, "없음")] + [(st, st.name) for st in app.stickers]
    return opts


def _frame_thumb(app, frame: dict) -> pygame.Surface | None:
    try:
        with Image.open(app.store.asset_path(frame["asset"])) as im:
            png = im.convert("RGBA")
    except Exception as exc:
        log.warning("프레임 %s 축소판을 만들 수 없음: %s", frame.get("id"), exc)
        return None
    base = Image.new("RGBA", png.size, (205, 214, 228, 255))  # 구멍(투명)이 보이게 회색 바탕
    base.alpha_composite(png)
    w = max(1, int(png.width * THUMB_SRC_H / png.height))
    return ui.pil_to_surface(base.resize((w, THUMB_SRC_H), Image.Resampling.LANCZOS))


class ChooseScene(Scene):
    layout_name = "choose"

    def __init__(self, app, kind: str, options: list[Option]):
        super().__init__(app)
        self.kind = kind
        self.options = options
        self.sel = 0
        self.pos = 0.0          # 목록이 보이는 위치 (항목 번호, 실수) — sel 로 미끄러지고 끄는 동안은 손가락을 따른다
        self.idle_t = 0.0       # 입력이 없었던 시간 (poke 가 되돌린다)
        self._drag_base: int | None = None
        self._d = 0.0           # 끄는 동안 손가락이 움직인 거리 (목록 방향)
        self._step = 1.0        # 항목 한 칸의 화면 길이 (끌기 → 항목 번호 환산)
        self.live = LiveView(app)
        self._thumbs: list[pygame.Surface | None] = []
        self._thumb_cache: dict = {}
        if kind == "R":
            self._thumbs = [_frame_thumb(app, app.bundle.frames[v]) for v, _ in options]
        self._update_step()

    # ---- 입력 ----
    def handle(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            self.idle_t = 0.0
        if is_key(event, pygame.K_LEFT, pygame.K_UP):
            self.sel = (self.sel - 1) % len(self.options)
        elif is_key(event, pygame.K_RIGHT, pygame.K_DOWN):
            self.sel = (self.sel + 1) % len(self.options)
        elif is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.skip()

    def tap_item(self, i: int) -> None:
        """항목을 눌렀다: 다른 항목이면 그쪽으로, 고른 항목이면 결정."""
        if i == self.sel:
            self.skip()
        else:
            self.sel = i

    def drag(self, g: Gesture) -> None:
        """끌면 목록이 손가락을 따르고, 놓으면 (휙 넘긴 만큼 더 가서) 가장 가까운 항목이 고른 항목이 된다. 끝에서 돌지 않는다."""
        n = len(self.options)
        d = g.dx if self.kind == "R" else g.dy
        if g.kind == "drag":
            if self._drag_base is None:
                self._drag_base = self.sel
            self._d = d
            self.pos = min(max(self._drag_base - d / self._step, 0.0), n - 1.0)
        elif g.kind == "drag_end":
            base = self._drag_base if self._drag_base is not None else self.sel
            v = g.vx if self.kind == "R" else g.vy
            flick = self.app.stage.tokens["touch"]["flick_project_ms"] / 1000
            proj = d + v * flick
            self.sel = min(max(math.floor(base - proj / self._step + 0.5), 0), n - 1)
            self._drag_base = None
            self._d = 0.0

    def skip(self) -> None:
        self.app.chose(self.kind, self.options[self.sel][0])

    def remote_state(self) -> str:
        return fmt_line("L", self.kind, self.sel, len(self.options), self.options[self.sel][1])

    def update(self, dt: float) -> None:
        super().update(dt)
        self.idle_t += dt
        if self.idle_t >= CHOOSE_IDLE_SEC:  # 설치한 사람이 패널을 열어 둔 시간도 센다 (웹 부스와 같다)
            self.app.home()
            return
        if self._drag_base is None:
            k = 1 - math.exp(-dt * EASE_RATE)
            self.pos += (self.sel - self.pos) * k
            if abs(self.sel - self.pos) < 0.002:
                self.pos = float(self.sel)

    # ---- 배치 ----
    def _update_step(self) -> None:
        st = self.app.stage
        L = st.layout("choose")
        if self.kind == "R":
            self._step = (st.base_w - 2 * L["side_margin"]) / L["frames_visible"]
        else:
            self._step = float(L["list_row_h"])

    def _hint(self) -> str:
        return HINT_KEY if self.app.input_kind == "key" else HINT_TOUCH

    def _first(self, visible: int) -> float:
        """창에 보이는 첫 칸의 항목 번호(실수). 고른 항목을 가운데에 두되 양끝에서는 목록이 창을 벗어나지 않고,
        항목이 창보다 적으면 가운데로 모은다 (시안 motion.carousel)."""
        n = len(self.options)
        if n <= visible:
            return -(visible - n) / 2
        return min(max(self.pos - (visible - 1) / 2, 0.0), n - visible)

    # ---- 그리기 ----
    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles = app.stage, app.theme.roles
        L = st.layout("choose")
        self._update_step()
        tx, ty = L["title_pos"]
        ui.text(surf, TITLES[self.kind], st.size("title"), roles["title"], (st.x(tx), st.y(ty)),
                anchor="midleft", face="title")
        if self.kind == "R":
            self._draw_frames(surf, st, roles, L)
        else:
            self._draw_live_list(surf, st, roles, L)
        size = st.size("body")
        tk = st.tokens
        cap = st.h - tk["credit"]["bottom"] - st.size("credit") - tk["space"]["step"][1] - size // 2  # 표기 위로만
        y = min(st.y(st.base_h - L["hint_bottom"], "bottom"), cap)
        ui.text(surf, self._hint(), size, roles["hint"], (st.w / 2, y), face="label",
                max_width=st.w - 2 * tk["space"]["step"][4])

    def _draw_live_list(self, surf, st, roles, L) -> None:
        app = self.app
        mirror = bool(app.bundle.settings["capture"]["mirror"])
        box = tuple(L["live_box"])
        value = self.options[self.sel][0]
        if self.kind == "F":
            live = self.live.render(LIVE_RATIO, box, value, None, mirror)
        else:
            live = self.live.render(LIVE_RATIO, box, app.chosen_filter(), value, mirror)
        draw_live(surf, live, (st.x(L["live_center"][0]), st.y(L["live_center"][1])), box, roles["line"])

        sp = st.tokens["space"]["step"]
        ring = st.tokens["touch"]["focus_ring_px"]
        pad = ring + sp[0]
        pin = "bottom" if st.orientation == "portrait" else "center"
        row_h, item_h, item_w = L["list_row_h"], L["list_item_h"], L["list_item_w"]
        view = pygame.Rect(st.x(L["list_x"]) - pad, st.y(L["list_top"], pin), item_w + 2 * pad, row_h * L["list_visible"])
        first = self._first(L["list_visible"])
        key = app.input_kind == "key"
        clip = surf.get_clip()
        # 포커스 테두리는 항목 밖으로 pad 만큼 나간다. 줄 사이 여백(row_h - item_h)의 절반보다 크면 창 맨 위 · 맨 아래
        # 칸에서 테두리가 잘리므로, 모자라는 만큼만 가림 영역을 위아래로 넓힌다 (옆은 view 가 이미 pad 만큼 넓다)
        over = max(0, pad - (row_h - item_h) // 2)
        surf.set_clip(view.inflate(0, 2 * over))
        for i, (_, label) in enumerate(self.options):
            cy = view.top + (i - first + 0.5) * row_h
            if cy + item_h / 2 < view.top or cy - item_h / 2 > view.bottom:
                continue
            r = pygame.Rect(0, 0, item_w, item_h)
            r.center = (st.x(L["list_x"]) + item_w // 2, round(cy))
            on = i == self.sel
            ui.action_button(surf, r, label, roles, kind="action" if on else "line", focused=on and key,
                             ring=ring, size=st.size("button"))
            self.hit(r.clip(view), lambda i=i: self.tap_item(i))
        surf.set_clip(clip)

    def _draw_frames(self, surf, st, roles, L) -> None:
        app = self.app
        sp = st.tokens["space"]["step"]
        ring = st.tokens["touch"]["focus_ring_px"]
        pad_ring = ring + sp[0]
        pad, thumb_h = L["frame_pad"], L["thumb_h"]
        cell_w = self._step
        view = pygame.Rect(st.x(L["side_margin"]), st.y(L["frame_top"]) - pad - pad_ring,
                           st.w - 2 * L["side_margin"], 0)
        view.height = pad + thumb_h + L["frame_count_dy"] + sp[4] + pad_ring
        first = self._first(L["frames_visible"])
        radius = st.tokens["space"]["radius"]["card"] * 2
        key = app.input_kind == "key"
        clip = surf.get_clip()
        surf.set_clip(view.inflate(2 * pad_ring, 0))  # 고른 축소판의 포커스 테두리가 옆에서 잘리지 않게
        for i, (value, label) in enumerate(self.options):
            cx = round(view.left + (i - first + 0.5) * cell_w)
            if cx + cell_w / 2 < view.left or cx - cell_w / 2 > view.right:
                continue
            on = i == self.sel
            src = self._thumbs[i]
            ratio = src.get_width() / src.get_height() if src else 0.5
            tw, th = fit_ratio(ratio, (int(cell_w - L["frame_cell_inset"]), thumb_h))
            box = pygame.Rect(0, 0, tw, th)
            box.center = (cx, st.y(L["frame_top"]) + thumb_h // 2)
            if on:
                bed = box.inflate(2 * pad, 2 * pad)
                ui.rrect(surf, roles["action"], bed, radius)
                if roles.get("action_edge"):
                    ui.rrect(surf, roles["action_edge"], bed, radius, st.tokens["touch"]["line_px"])
                if key:
                    ui.rrect(surf, roles["line"], bed.inflate(2 * pad_ring, 2 * pad_ring), radius + pad_ring, ring)
            if src is not None:
                key_ = (i, tw, th)
                img = self._thumb_cache.get(key_)
                if img is None:
                    img = self._thumb_cache[key_] = pygame.transform.smoothscale(src, (tw, th))
                surf.blit(img, box)
            else:
                ui.rrect(surf, (215, 222, 235), box, 16)
            frame = app.bundle.frames[value]
            name_size, room = st.size("body"), int(cell_w - 2 * sp[1])
            name_y = st.y(L["frame_top"]) + thumb_h + L["frame_name_dy"]
            if ui.fit_size(label, name_size, room, "label") < round(name_size * ui.LABEL_WRAP_SCALE):
                # 긴 이름은 한 줄로 줄이지 않고 두 줄로 (넘치면 …) — 숫자 줄을 침범하지 않게 위로 반 줄 올린다
                name_size = round(name_size * ui.LABEL_WRAP_SCALE)
                for k, line in enumerate(ui.wrap_lines(label, name_size, room, "label")):
                    ui.text(surf, line, name_size, roles["title"], (cx, name_y - name_size // 2 + k * round(name_size * ui.LABEL_LINE)),
                            face="label", max_width=room)
            else:
                ui.text(surf, label, name_size, roles["title"], (cx, name_y), face="label", max_width=room)
            ui.text(surf, f"{cut_count(frame['slots'])}컷", st.size("body"), roles["hint"],
                    (cx, st.y(L["frame_top"]) + thumb_h + L["frame_count_dy"]), face="number")
            item = pygame.Rect(0, 0, int(cell_w), view.height)
            item.midtop = (cx, view.top)
            self.hit(item.clip(view), lambda i=i: self.tap_item(i))
        surf.set_clip(clip)


def fit_ratio(ratio: float, box: tuple[int, int]) -> tuple[int, int]:
    """비율 ratio(가로/세로)를 지키며 box 안에 들어가는 가장 큰 크기."""
    bw, bh = box
    if bw / bh > ratio:
        return max(1, round(bh * ratio)), bh
    return bw, max(1, round(bw / ratio))
