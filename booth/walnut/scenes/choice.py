"""컷마다 '찍은 그대로' · 'AI 추천' 고르기 — 지능형 촬영(버스트 · 구도 보정)이 켜져 있을 때 셔터 뒤에 뜬다.

찍은 그대로 = 셔터 순간 프레임 + 미리보기에서 본 구도 (기본 구도). 일부러 구석에서 찍은 연출이 그대로 남는다.
AI 추천 = 버스트가 고른 프레임 + 구도 보정 크롭 (고르기 전 결과 그대로). 두 장 모두 그 컷의 첫 슬롯 비율 · 크롭으로 보인다.

CHOICE_SEC 동안 입력이 없으면 AI 추천으로 넘어간다 (키 · 탭마다 처음부터 다시 센다).
←→ (↑↓) 로 고르고 Enter 로 확정. 터치: 사진이나 이름표를 누르면 바로 확정. F2 는 AI 추천 (시간 초과와 같게 센다).
리모컨에는 A|커서|남은 0.1초|전체 0.1초 줄을 보낸다 (커서 0 찍은 그대로 · 1 AI 추천, 남은 시간은 C 줄처럼 0.1초 단위 올림).
고른 결과는 세션(shot_choice)과 현장 기록 cut 줄(choice · choice_ms)에 남는다.
배치는 따로 토큰을 두지 않고 고르기 화면(layout.pick)의 제목 · 격자 · 버튼 자리를 빌린다. 사진 비율에 따라 나란히 · 위아래 중
사진이 더 커지는 쪽으로 놓고, 두 장은 한 덩어리로 모은다 (가로 화면은 가운데, 세로 화면은 제목 바로 아래).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import pygame
from PIL import Image

from .. import ui
from ..remote import fmt_line
from ..session import AS_SHOT
from ..stage import Stage
from .base import Scene, is_key
from .capture import Shoot, cut_thumb, paper_size

CHOICE_SEC = 10.0
TITLE = "어떤 사진으로 할까요?"
LABELS = ("찍은 그대로", "AI 추천")  # 커서 0 · 1 (화면 왼쪽 · 위가 0)
HINT_KEY = "좌우로 고르고 버튼을 눌러 주세요"
HINT_TOUCH = "마음에 드는 사진을 눌러 주세요"


@dataclass
class ChoiceData:
    """한 컷의 두 후보. 이미지는 process_cut 을 거친 컷 원본 (고른 쪽이 그대로 컷이 된다)."""
    cut: int
    ratio: float
    ai_img: Image.Image
    ai_crop: tuple[int, int, int, int]
    as_img: Image.Image
    as_crop: tuple[int, int, int, int]


@dataclass(frozen=True)
class ChoiceLayout:
    cards: list[pygame.Rect]    # 인화지 (찍은 그대로, AI 추천)
    labels: list[pygame.Rect]   # 사진 아래 이름표 알약
    title: tuple[int, int]      # 제목 왼쪽 가운데
    count: tuple[int, int]      # '컷 k' 오른쪽 가운데
    hint: tuple[int, int]       # 남은 초 · 안내 줄 가운데


def choice_layout(stage: Stage, ratio: float) -> ChoiceLayout:
    """두 장을 고르기 격자 자리에 나란히 또는 위아래로 놓는다 — 인화지가 더 커지는 쪽."""
    L, tk = stage.layout("pick"), stage.tokens
    step = tk["space"]["step"]
    gx, gy, gw, gh = L["grid"]
    area = pygame.Rect(stage.x(gx, "center"), stage.y(gy, "center"), gw, gh)
    pin = "bottom" if stage.orientation == "portrait" else "center"
    # 안내 줄은 [완료] 버튼 자리 — 제작 표기 위로만
    cap = stage.h - tk["credit"]["bottom"] - stage.size("credit") - step[1] - stage.size("label") // 2
    hint_y = min(stage.y(L["done_center_y"], pin), cap)
    # 세로 화면은 격자 아래가 비어 있으면 안내 줄 바로 위까지 늘린다
    bottom = hint_y - stage.size("label") - step[2]
    if bottom > area.bottom:
        area.height = bottom - area.top
    label_h = L["done_button"][1] * 3 // 4
    label_w = min(L["done_button"][0], area.width // 2 - step[3])
    gap = step[5]  # 두 장 사이

    def paper_for(side: bool) -> tuple[int, int]:
        """side=True 나란히, False 위아래일 때 칸 하나에 들어가는 인화지 크기."""
        cw, ch = ((area.width - gap) // 2, area.height) if side else (area.width, (area.height - gap) // 2)
        return paper_size(ratio, (cw, max(1, ch - label_h - step[1])), tk)

    ps, pt = paper_for(True), paper_for(False)
    side = ps[0] * ps[1] >= pt[0] * pt[1]
    paper = ps if side else pt
    block_h = paper[1] + step[1] + label_h  # 인화지 + 이름표
    # 두 장을 한 덩어리로 모은다 — 가로 화면은 영역 가운데, 세로 화면은 제목 바로 아래부터
    total_h = block_h if side else 2 * block_h + gap
    top = area.y if stage.orientation == "portrait" else area.y + (area.height - total_h) // 2
    if side:
        x0 = area.centerx - (2 * paper[0] + gap) // 2
        spots = [(x0 + paper[0] // 2 + k * (paper[0] + gap), top) for k in range(2)]
        room = paper[0] + gap - step[1]  # 이름표끼리 겹치지 않는 폭
    else:
        spots = [(area.centerx, top + k * (block_h + gap)) for k in range(2)]
        room = area.width
    lw = min(label_w, max(paper[0], label_w * 2 // 3), room)
    cards, labels = [], []
    for cx_, y in spots:
        card = pygame.Rect(0, 0, *paper)
        card.midtop = (cx_, y)
        lab = pygame.Rect(0, 0, lw, label_h)
        lab.midtop = (cx_, card.bottom + step[1])
        cards.append(card)
        labels.append(lab)
    tx, ty = L["title_pos"]
    cx, cy = L["count_pos"]
    return ChoiceLayout(cards, labels, (stage.x(tx), stage.y(ty)), (stage.x(cx, "right"), stage.y(cy)),
                        (stage.w // 2, hint_y))


class ChoiceScene(Scene):
    layout_name = "pick"

    def __init__(self, app, shoot: Shoot, data: ChoiceData, rec: dict | None, on_done: Callable[[], None]):
        """rec 은 아직 쓰지 않은 cut 줄 (현장 기록이 꺼져 있으면 None). 고른 뒤 choice · choice_ms 를 붙여 쓴다."""
        super().__init__(app)
        self.shoot = shoot
        self.data = data
        self.rec = rec
        self._on_done = on_done
        self._finished = False
        self.sel = 1  # 기본은 AI 추천 — 시간이 다 되면 고르는 쪽
        self.idle_t = 0.0
        st = app.stage
        self.lay = choice_layout(st, data.ratio)
        b, bb = st.tokens["print"]["border"], st.tokens["print"]["border_bottom"]
        card = self.lay.cards[0]
        box = (card.w - 2 * b, card.h - b - bb)
        self.thumbs = [cut_thumb(data.as_img, data.ratio, box, data.as_crop),
                       cut_thumb(data.ai_img, data.ratio, box, data.ai_crop)]

    # ---- 진행 ----
    def choose(self, i: int, how: str | None = None) -> None:
        """i 쪽으로 확정한다 (0 찍은 그대로 · 1 AI 추천). how 는 기록 값 (기본: 손님이 고름)."""
        if self._finished:
            return
        self._finished = True
        self.sel = i
        s = self.shoot.session
        if i == 0:
            s.use_as_shot(self.data.cut, self.data.as_img)
        self._write(how or (AS_SHOT if i == 0 else "ai"))
        self._on_done()

    def _write(self, choice: str) -> None:
        rec, self.rec = self.rec, None
        if rec is None:
            return
        rec.update(choice=choice, choice_ms=int(round(self.t * 1000)))
        self.app.capture_log.write(rec)

    def exit(self) -> None:
        """다 고르기 전에 떠난다 (처음 화면으로 등) — cut 줄은 고르기 없음으로 남기고, 촬영은 잇지 않는다."""
        if not self._finished:
            self._finished = True
            self._write("skipped")

    def handle(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        self.idle_t = 0.0
        if is_key(event, pygame.K_LEFT, pygame.K_UP):
            self.sel = 0
        elif is_key(event, pygame.K_RIGHT, pygame.K_DOWN):
            self.sel = 1
        elif is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.choose(self.sel)

    def skip(self) -> None:
        """F2 — AI 추천 (손님이 고른 것이 아니므로 시간 초과와 같게 센다)."""
        self.choose(1, "timeout_ai")

    def update(self, dt: float) -> None:
        super().update(dt)
        if self._finished:
            return
        self.idle_t += dt
        if self.idle_t >= CHOICE_SEC:
            self.choose(1, "timeout_ai")

    def left(self) -> int:
        return max(0, math.ceil(CHOICE_SEC - self.idle_t - 1e-9))

    def remote_state(self) -> str:
        """A|커서|남은 0.1초|전체 0.1초 — 리모컨 OLED 의 고르기 화면 (더 찍고 고르기 모드의 고르기도 같은 줄)."""
        left = max(0, math.ceil((CHOICE_SEC - self.idle_t) * 10 - 1e-6))
        return fmt_line("A", self.sel, left, round(CHOICE_SEC * 10))

    # ---- 그리기 ----
    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles, tk = app.stage, app.theme.roles, app.stage.tokens
        lay = self.lay
        key = app.input_kind == "key"
        ring = tk["touch"]["focus_ring_px"]
        self.hit(surf.get_rect(), lambda: None)  # 빈 곳을 눌러도 타이머만 처음부터 (poke)

        size = st.size("headline")
        count = f"컷 {self.data.cut + 1}"
        cw = ui.font(size, "number", count).size(count)[0]
        ui.text(surf, TITLE, size, roles["title"], lay.title, anchor="midleft", face="title",
                max_width=max(10, lay.count[0] - cw - lay.title[0] - tk["space"]["step"][3]))
        ui.text(surf, count, size, roles["title"], lay.count, anchor="midright", face="number")

        for i, (th, card, lab) in enumerate(zip(self.thumbs, lay.cards, lay.labels)):
            paper = ui.print_card(surf, th, card.center, tk, roles)
            on = i == self.sel
            # 커서가 곧 고른 쪽이라 강조색 테두리 하나로 충분하다 — 포커스 고리까지 겹치면 이중 테두리가 되고 이름표에 닿는다
            if on:
                pygame.draw.rect(surf, roles["action"], paper.inflate(2 * ring, 2 * ring), ring)
            ui.action_button(surf, lab, LABELS[i], roles, kind="action" if on else "line", ring=ring,
                             size=st.size("button"))
            self.hit(card, lambda i=i: self.choose(i))
            self.hit(lab, lambda i=i: self.choose(i))

        hint = f"{self.left()}초 뒤 AI 추천으로 넘어가요  ·  {HINT_KEY if key else HINT_TOUCH}"
        ui.text(surf, hint, st.size("label"), roles["hint"], lay.hint, face="label",
                max_width=st.w - 2 * tk["space"]["step"][4])
