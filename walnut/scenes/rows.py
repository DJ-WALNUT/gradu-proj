"""줄 묶음을 세로로 미는 계산 — 웹 부스 ui/motion.ts 의 rowShift · dragScroll(snap row) 과 같다.

장면이 줄마다 (윗변, 높이) 를 넘기면 (밀기 전 캔버스 좌표), 보이는 높이 view_h 보다 길 때만 밀린다.
줄 r 로 가면 그 줄이 창 가운데로 오고 내용 끝을 넘지 않는다. 손가락으로 끌면 따라가고, 놓으면
(휙 넘긴 만큼 더 간 자리에서) 가장 가까운 줄로 맞춘다. 다 들어가면 밀지도 끌리지도 않는다.
"""

from __future__ import annotations

import math

from ..touch import Gesture

EASE_RATE = 14.0  # 고른 줄로 미끄러지는 빠르기 (고르기 목록과 같다)


class RowScroll:
    def __init__(self, flick_sec: float):
        self._flick = flick_sec
        self.spans: list[tuple[int, int]] = []
        self.view_h = 0
        self.overflow = 0   # 내용이 창보다 긴 만큼 (0 이면 안 민다)
        self.row = 0        # 맞춘 줄
        self.pos = 0.0      # 지금 보이는 밀림 (px, 아래 줄을 볼수록 커진다)
        self._base: float | None = None

    def set_rows(self, spans: list[tuple[int, int]], view_h: int) -> None:
        self.spans = list(spans)
        self.view_h = view_h
        self.overflow = max(0, max((t + h for t, h in spans), default=0) - view_h)
        self.row = min(self.row, max(0, len(spans) - 1))

    def shift_for(self, r: int) -> int:
        """줄 r 로 갈 때 내용을 올릴 양."""
        if self.overflow <= 0 or not self.spans:
            return 0
        top, h = self.spans[max(0, min(len(self.spans) - 1, r))]
        return int(min(max(top + h / 2 - self.view_h / 2, 0), self.overflow))

    def go(self, r: int) -> None:
        self.row = max(0, min(max(0, len(self.spans) - 1), r))

    @property
    def dragging(self) -> bool:
        return self._base is not None

    def drag(self, g: Gesture) -> int | None:
        """끌기 · 끌기 끝. 놓아서 줄이 정해지면 그 줄 번호 (밀 것이 없으면 늘 None)."""
        if self.overflow <= 0:
            return None
        if g.kind == "drag":
            if self._base is None:
                self._base = self.pos
            self.pos = min(max(self._base - g.dy, 0.0), float(self.overflow))
        elif g.kind == "drag_end":
            base = self._base if self._base is not None else self.pos
            proj = min(max(base - (g.dy + g.vy * self._flick), 0.0), float(self.overflow))
            self._base = None
            best = self.row
            for r in range(len(self.spans)):
                if abs(self.shift_for(r) - proj) < abs(self.shift_for(best) - proj):
                    best = r
            self.row = best
            return best
        return None

    def update(self, dt: float) -> None:
        if self._base is None:
            target = self.shift_for(self.row)
            self.pos += (target - self.pos) * (1 - math.exp(-dt * EASE_RATE))
            if abs(target - self.pos) < 0.5:
                self.pos = float(target)
