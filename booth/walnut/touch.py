"""터치 인식기 — 마우스 이벤트(터치스크린도 SDL 이 마우스로 보낸다)를 탭 · 끌기 · 길게 누르기로 바꾼다.

FINGER* 이벤트는 쓰지 않는다. 터치와 진짜 마우스를 구분하지 않는다.
화면(App)과 무관한 순수 입력 모듈이다.
"""

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import pygame


@dataclass(frozen=True)
class Gesture:
    kind: str  # tap · drag · drag_end · long
    pos: tuple[int, int]
    start: tuple[int, int]
    dx: int = 0
    dy: int = 0
    vx: float = 0.0  # 단위/초, drag_end 에만 값
    vy: float = 0.0


class TouchTracker:
    def __init__(self, touch_tokens: dict, zone: "pygame.Rect | None" = None, clock=time.monotonic):
        self._threshold = touch_tokens["drag_threshold_px"]
        self._long_sec = touch_tokens["long_press_ms"] / 1000
        self._flick_sec = touch_tokens["flick_project_ms"] / 1000
        self.zone = zone
        self._clock = clock
        self.cancel()

    def cancel(self) -> None:
        """진행 중인 누름을 버린다. 이후의 움직임 · 뗌은 아무것도 내지 않는다."""
        self._start: tuple[int, int] | None = None
        self._dragging = False
        self._long_fired = False
        self._t0 = 0.0
        self._samples: deque = deque()

    def feed(self, event) -> list[Gesture]:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = tuple(event.pos)
            self.cancel()
            self._start = pos
            self._t0 = self._clock()
            self._samples.append((self._t0, pos))
            return []
        if self._start is None:
            return []
        if event.type == pygame.MOUSEMOTION:
            return self._motion(tuple(event.pos))
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            return self._release(tuple(event.pos))
        return []

    def tick(self) -> list[Gesture]:
        if (
            self._start is None
            or self._dragging
            or self._long_fired
            or self.zone is None
            or not self.zone.collidepoint(self._start)
            or self._clock() - self._t0 < self._long_sec
        ):
            return []
        self._long_fired = True
        return [Gesture("long", self._start, self._start)]

    def _motion(self, pos) -> list[Gesture]:
        self._record(pos)
        if not self._dragging:
            if max(abs(pos[0] - self._start[0]), abs(pos[1] - self._start[1])) <= self._threshold:
                return []
            self._dragging = True
        return [Gesture("drag", pos, self._start, pos[0] - self._start[0], pos[1] - self._start[1])]

    def _release(self, pos) -> list[Gesture]:
        start, dragging, long_fired = self._start, self._dragging, self._long_fired
        if dragging:
            self._record(pos)
            vx, vy = self._velocity()
            g = [Gesture("drag_end", pos, start, pos[0] - start[0], pos[1] - start[1], vx, vy)]
        elif long_fired:
            g = []
        else:
            g = [Gesture("tap", pos, start)]
        self.cancel()
        return g

    def _record(self, pos) -> None:
        now = self._clock()
        self._samples.append((now, pos))
        while self._samples and now - self._samples[0][0] > self._flick_sec:
            self._samples.popleft()

    def _velocity(self) -> tuple[float, float]:
        """최근 flick_project_ms 안 표본의 첫 점 → 끝 점 속도 (단위/초)."""
        (t1, p1), (t2, p2) = self._samples[0], self._samples[-1]
        dt = t2 - t1
        if dt <= 0:
            return 0.0, 0.0
        return (p2[0] - p1[0]) / dt, (p2[1] - p1[1]) / dt


class HitMap:
    """그려진 버튼 영역 → 동작. 나중에 더한(위에 그려진) 것이 먼저 받는다."""

    def __init__(self):
        self._items: list[tuple[pygame.Rect, Callable[[], None]]] = []

    def clear(self) -> None:
        self._items.clear()

    def add(self, rect: pygame.Rect, action: Callable[[], None]) -> None:
        self._items.append((rect, action))

    def tap(self, pos) -> bool:
        for rect, action in reversed(self._items):
            if rect.collidepoint(pos):
                action()
                return True
        return False
