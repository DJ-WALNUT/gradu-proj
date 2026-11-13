"""베스트 컷 분석 화면 — 개발자 모드(--dev-mode-all)에서 컷마다 버스트샷이 어떻게 골랐는지 보여 준다.

위: 셔터 앞뒤(-0.7초 ~ +0.3초) 후보를 시간순으로 한 줄. 탈락은 흐리게 + 사유 딱지.
가운데: '카운트다운 순간' (원래 찍혔을 컷) 과 '베스트 컷' (고른 컷) 을 크게 나란히, 수치와 함께.
아래: 고른 이유 한 줄.

Enter · Space · 탭 · F2 로 넘기고, 입력이 없으면 AUTO_SEC 뒤 자동으로 넘어간다.
개발자용 화면이라 배치는 디자인 토큰이 아니라 화면 크기 비율로 잡는다. 썸네일은 거울 · 컷 비율만 적용한 원본이다
(필터 · 스티커 없음 — 비교가 목적).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np
import pygame

from .. import ui
from ..burst import TimedFrame
from .base import Scene, is_key

AUTO_SEC = 20.0    # 입력이 없으면 이 뒤에 다음 컷으로
REVEAL_SEC = 1.5   # 연출 전체 길이 (아래 두 구간 + 베스트 강조)
APPEAR_SEC = 0.6   # 후보가 시간순으로 나타난다
DIM_SEC = 1.1      # 여기까지 탈락 후보가 흐려지고, 그 뒤 베스트 강조
DIM_ALPHA = 80     # 탈락 후보 썸네일의 불투명도 (0~255)

REJECT_LABEL = {"blur": "흔들림", "eye": "눈 감음", "faces": "얼굴 수 부족"}
FALLBACK_REASONS = ("timeout", "error", "no_candidates")
BEFORE, AFTER = "-0.7초", "+0.3초"
TAG_SHUTTER, TAG_BEST = "카운트다운 순간", "베스트 컷"


@dataclass
class ShowData:
    """한 컷의 분석 결과를 화면에 보이기 위한 것. frames 는 화면 표시용으로만 쥔다 (디스크에 쓰지 않는다)."""
    frames: list[TimedFrame]   # 후보 (시간순). 분석을 맡기지 못했으면 빈 목록
    shutter_t: float           # 셔터 시각 (time.monotonic)
    info: dict | None          # BurstResult.info. 분석 실패 · 시간 초과면 None
    reason: str                # best · single · no_face · all_rejected · timeout · error · no_candidates
    ratio: float               # 이 컷의 비율 (w/h)
    mirror: bool
    cut: int                   # 컷 번호 (0부터)


def shutter_index(ts: list[float], shutter_t: float) -> int:
    """셔터에 가장 가까운 후보 (같으면 이른 쪽). 후보가 없으면 -1."""
    if not ts:
        return -1
    return min(range(len(ts)), key=lambda i: (abs(ts[i] - shutter_t), ts[i], i))


def _at(seq, i: int):
    return seq[i] if seq is not None and 0 <= i < len(seq) else None


def reason_text(info: dict | None, reason: str, shutter_i: int, shutter_t: float | None = None) -> str:
    """고른 이유 한 줄. 시간은 셔터 시각(shutter_t) 기준, 없으면 셔터 컷 기준 (초)."""
    if info is None or reason in FALLBACK_REASONS:
        return "분석을 끝내지 못해 카운트다운 순간의 컷을 그대로 썼어요"
    if reason == "single":
        return "후보가 한 장뿐이라 그대로 썼어요"
    if reason == "no_face":
        return "얼굴을 찾지 못해 가장 선명한 컷을 골랐어요"
    if reason == "all_rejected":
        return "모든 후보가 탈락해 셔터에 가장 가까운 컷을 썼어요"
    best = int(info.get("index", shutter_i))
    if best == shutter_i:
        return "카운트다운 순간의 컷이 가장 좋았어요"
    cands = info.get("candidates") or []
    a, b = _at(cands, best), _at(cands, shutter_i)
    base = shutter_t if shutter_t is not None else (b["t"] if b else None)
    dt = (a["t"] - base) if a and base is not None else 0.0
    why = REJECT_LABEL.get(_at(info.get("rejects"), shutter_i) or "")
    if why:
        return f"카운트다운 순간은 {why}으로 탈락 → {dt:+.2f}초 컷이 가장 좋아요"
    sa, sb = _at(info.get("scores"), best), _at(info.get("scores"), shutter_i)
    if sa is None or sb is None:
        return f"{dt:+.2f}초 컷이 가장 좋아요"
    return f"{dt:+.2f}초 컷의 점수가 더 높아요 ({sa:.2f} > {sb:.2f})"


def reject_note(reject: str, cand: dict | None) -> str:
    """탈락 딱지 — 걸린 값이 있으면 함께 적는다 (눈 뜸 수치 · 얼굴 수)."""
    label = REJECT_LABEL.get(reject, "탈락")
    if cand is None:
        return label
    if reject == "eye" and cand.get("eye") is not None:
        return f"{label} {cand['eye']:.2f}"
    if reject == "faces" and cand.get("faces") is not None:
        return f"얼굴 {cand['faces']}명"
    return label


def _num(v, fmt: str) -> str:
    return "—" if v is None else format(v, fmt)


def metrics_text(cand: dict | None, score) -> str:
    if cand is None:
        return "분석 수치 없음"
    return (f"선명도 {_num(cand.get('sharpness'), '.0f')}  ·  눈 뜸 {_num(cand.get('eye'), '.2f')}  ·  "
            f"정면 {_num(cand.get('frontality'), '.2f')}  ·  점수 {_num(score, '.2f')}")


class BurstShowScene(Scene):
    def __init__(self, app, data: ShowData, on_done: Callable[[], None]):
        super().__init__(app)
        self.data = data
        self._on_done = on_done
        self._finished = False
        self.n = len(data.frames)
        self.ts = [f.t for f in data.frames]
        self.shutter_i = shutter_index(self.ts, data.shutter_t)
        info = data.info if data.reason not in FALLBACK_REASONS else None
        best = int(info["index"]) if info and "index" in info else self.shutter_i
        self.best_i = best if 0 <= best < self.n else self.shutter_i
        self.cands = [_at(info.get("candidates"), i) if info else None for i in range(self.n)]
        self.scores = [_at(info.get("scores"), i) if info else None for i in range(self.n)]
        self.rejects = [_at(info.get("rejects"), i) if info else None for i in range(self.n)]
        self.reason = reason_text(data.info, data.reason, self.shutter_i, data.shutter_t)
        self._thumbs: dict[tuple[int, tuple[int, int]], pygame.Surface] = {}

    # ---- 진행 ----
    def done(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._on_done()

    def handle(self, event: pygame.event.Event) -> None:
        if is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.done()

    def skip(self) -> None:
        self.done()

    def update(self, dt: float) -> None:
        super().update(dt)
        if self.t >= AUTO_SEC:
            self.done()

    def phase(self) -> str:
        """appear (후보가 나타남) → dim (탈락이 흐려짐) → best (베스트 강조 · 이유). 연출을 끄면 처음부터 best."""
        if not self.app.cfg.motion or self.t >= DIM_SEC:
            return "best"
        return "appear" if self.t < APPEAR_SEC else "dim"

    def left(self) -> int:
        return max(0, math.ceil(AUTO_SEC - self.t))

    # ---- 그리기 ----
    def _thumb(self, i: int, size: tuple[int, int]) -> pygame.Surface:
        """후보 i 를 거울 · 컷 비율로 잘라 size 로 줄인 것. 같은 크기는 다시 만들지 않는다."""
        key = (i, size)
        hit = self._thumbs.get(key)
        if hit is None:
            from .capture import crop_to_ratio, mirrored

            rgb = crop_to_ratio(mirrored(self.data.frames[i].rgb, self.data.mirror), self.data.ratio)
            small = cv2.resize(np.ascontiguousarray(rgb), size, interpolation=cv2.INTER_AREA)
            hit = self._thumbs[key] = ui.np_to_surface(small)
        return hit

    def draw(self, surf: pygame.Surface) -> None:
        from .capture import fit

        st, roles = self.app.stage, self.app.theme.roles
        W, H = st.w, st.h
        self.hit(pygame.Rect(0, 0, W, H), self.done)  # 화면 아무 데나 탭 = 다음
        m = round(W * 0.03)
        small, mid, big = max(14, round(H * 0.022)), max(18, round(H * 0.03)), max(24, round(H * 0.045))
        phase = self.phase()
        wide = W - 2 * m

        ui.text(surf, f"컷 {self.data.cut + 1} — 베스트 컷 분석", big, roles["title"], (W // 2, round(H * 0.06)),
                face="title", max_width=wide)

        if self.n == 0:  # 후보를 모으지 못했다 — 이유만 보여 준다
            ui.text(surf, "후보 프레임을 모으지 못했어요", mid, roles["hint"], (W // 2, round(H * 0.4)), max_width=wide)
        else:
            self._draw_strip(surf, pygame.Rect(m, round(H * 0.12), wide, round(H * 0.27)), small, phase, fit)
            if phase == "best":
                self._draw_pair(surf, pygame.Rect(m, round(H * 0.43), wide, round(H * 0.41)), small, mid, fit)
        if phase == "best":
            ui.text(surf, self.reason, mid, roles["title"], (W // 2, round(H * 0.875)), face="title", max_width=wide)
        ui.text(surf, f"Enter 다음 컷  ·  {self.left()}초 뒤 자동으로 넘어가요", small, roles["hint"],
                (W // 2, round(H * 0.925)), face="label", max_width=wide)  # 맨 아래는 제작 표기 자리

    def _draw_strip(self, surf, area: pygame.Rect, small: int, phase: str, fit) -> None:
        """후보 한 줄: 시간축 글자 → 썸네일 → 시간 · 점수 → 표시(카운트다운 순간 · 베스트 · 탈락 사유)."""
        roles = self.app.theme.roles
        n = self.n
        gap = max(4, round(area.width * 0.006))
        line = round(small * 1.4)
        cell_w = max(8, (area.width - gap * (n - 1)) // n)
        tw, th = fit(self.data.ratio, (cell_w, max(8, area.height - 4 * line)))
        total = n * cell_w + (n - 1) * gap
        x0 = area.x + (area.width - total) // 2
        top = area.y + line

        # 시간축: 왼쪽 끝 · 셔터 · 오른쪽 끝
        ui.text(surf, BEFORE, small, roles["hint"], (x0, area.y), anchor="topleft", face="label")
        ui.text(surf, AFTER, small, roles["hint"], (x0 + total, area.y), anchor="topright", face="label")

        visible = n
        if phase == "appear":
            visible = min(n, math.ceil(n * self.t / APPEAR_SEC))
        show_marks = phase == "best"
        for i in range(visible):
            cx = x0 + i * (cell_w + gap) + cell_w // 2
            r = pygame.Rect(0, 0, tw, th)
            r.midtop = (cx, top)
            img = self._thumb(i, (tw, th))
            rejected = self.rejects[i] is not None
            if rejected and phase != "appear":
                img = img.copy()
                img.set_alpha(DIM_ALPHA)
            surf.blit(img, r)
            if show_marks and i == self.best_i:
                pygame.draw.rect(surf, roles["action"], r.inflate(8, 8), 4, border_radius=6)
            elif show_marks and i == self.shutter_i:
                pygame.draw.rect(surf, roles["title"], r.inflate(8, 8), 2, border_radius=6)
            dt = self.ts[i] - self.data.shutter_t
            ui.text(surf, f"{dt:+.2f}초", small, roles["hint"], (cx, r.bottom + line // 2 + 2), face="number",
                    max_width=cell_w)
            if phase == "appear":
                continue
            if rejected:
                note, color = reject_note(self.rejects[i], self.cands[i]), roles["hint"]
            else:
                note, color = _num(self.scores[i], ".2f"), roles["title"]
            ui.text(surf, note, small, color, (cx, r.bottom + line + line // 2 + 2), face="label", max_width=cell_w)
            if show_marks and i in (self.best_i, self.shutter_i):
                tag = "셔터 · 베스트" if self.best_i == self.shutter_i else "베스트" if i == self.best_i else "셔터"
                ui.text(surf, tag, small, roles["action"] if i == self.best_i else roles["title"],
                        (cx, r.bottom + 2 * line + line // 2 + 2), face="title", max_width=cell_w)

    def _draw_pair(self, surf, area: pygame.Rect, small: int, mid: int, fit) -> None:
        """'카운트다운 순간' 과 '베스트 컷' 을 크게 나란히. 같은 컷이면 한 장만 가운데."""
        roles = self.app.theme.roles
        same = self.best_i == self.shutter_i
        items = [(self.best_i, f"{TAG_SHUTTER} = {TAG_BEST}" if same else TAG_BEST, roles["action"])]
        if not same:
            items.insert(0, (self.shutter_i, TAG_SHUTTER, roles["title"]))
        cols = len(items)
        col_w = area.width // cols
        head = round(mid * 1.5)
        foot = round(small * 1.8)
        size = fit(self.data.ratio, (max(8, round(col_w * 0.8)), max(8, area.height - head - foot)))
        for k, (i, title, color) in enumerate(items):
            cx = area.x + col_w * k + col_w // 2
            ui.text(surf, title, mid, color, (cx, area.y + head // 2), face="title", max_width=col_w)
            r = pygame.Rect(0, 0, *size)
            r.midtop = (cx, area.y + head)
            pygame.draw.rect(surf, color, r.inflate(10, 10), 5 if color == roles["action"] else 2, border_radius=8)
            surf.blit(self._thumb(i, size), r)
            ui.text(surf, metrics_text(self.cands[i], self.scores[i]), small, roles["title"],
                    (cx, r.bottom + foot // 2 + 4), face="label", max_width=col_w - 16)
