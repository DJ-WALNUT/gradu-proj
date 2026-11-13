"""숫자 다이얼 — 페어링 코드·관리자 PIN 입력. 리모컨(방향키 + Enter)만으로도 넣을 수 있다.

    터치      숫자 패드(0~9 · 지움 · 확인)와 칸 탭 — 키와 같은 press_digit · backspace · confirm 을 부른다
    ↑↓       지금 자리 숫자 바꾸기 (빈 자리는 ↑ 0, ↓ 9 부터)
    ←→       자리 옮기기
    Enter    다 찼으면 제출(on_submit), 아니면 다음 빈 자리로
    숫자 키   지금 자리에 넣고 오른쪽으로 · Backspace 지우기
"""

from __future__ import annotations

from typing import Callable

import pygame

from .. import ui

_KEYPAD = {getattr(pygame, f"K_KP{i}"): i for i in range(10)}
_DIGIT_KEYS = {getattr(pygame, f"K_{i}"): i for i in range(10)}


class DigitDial:
    def __init__(self, length: int, masked: bool = False) -> None:
        self.length = length
        self.masked = masked  # PIN: 지금 자리 말고는 숫자를 가린다
        self.digits: list[int | None] = [None] * length
        self.cursor = 0
        self.on_submit: Callable[[str], None] | None = None
        self.locked: Callable[[], bool] | None = None  # True 면 패드 · 칸 탭이 아무 일도 안 한다 (연결 중 등)
        self.show_arrows = True  # ↑↓ 화살표는 리모컨(키) 입력일 때만 보인다 — 장면이 그릴 때마다 정한다

    def entered(self) -> int:
        return sum(d is not None for d in self.digits)

    def reset(self) -> None:
        self.digits = [None] * self.length
        self.cursor = 0

    def _put(self, n: int) -> None:
        self.digits[self.cursor] = n
        self.cursor = min(self.length - 1, self.cursor + 1)

    # ---- 키와 숫자 패드가 같이 쓰는 동작 ----

    def _locked(self) -> bool:
        return self.locked is not None and self.locked()

    def press_digit(self, n: int) -> None:
        """지금 자리에 넣고 오른쪽으로."""
        self._put(n)

    def backspace(self) -> None:
        """지금 자리를 지운다 (비어 있으면 왼쪽 자리를 지운다)."""
        if self.digits[self.cursor] is None and self.cursor > 0:
            self.cursor -= 1
        self.digits[self.cursor] = None

    def confirm(self) -> None:
        """다 찼으면 제출, 아니면 (지금 자리가 찼을 때) 다음 빈 자리로."""
        if all(x is not None for x in self.digits):
            if self.on_submit:
                self.on_submit("".join(str(x) for x in self.digits))
        elif self.digits[self.cursor] is not None:
            empty = [i for i, x in enumerate(self.digits) if x is None]
            after = [i for i in empty if i > self.cursor]
            self.cursor = (after or empty)[0]

    def _press(self, key: str) -> None:
        """숫자 패드 칸 하나 ("0"~"9" · "back" · "ok"). 잠겼으면 아무 일도 없다 (키 입력은 잠금과 상관없다)."""
        if self._locked():
            return
        if key == "back":
            self.backspace()
        elif key == "ok":
            self.confirm()
        else:
            self.press_digit(int(key))

    def handle(self, event: pygame.event.Event) -> bool:
        """처리한 키면 True."""
        if event.type != pygame.KEYDOWN:
            return False
        k = event.key
        d = self.digits[self.cursor]
        if k in _DIGIT_KEYS or k in _KEYPAD:
            self.press_digit(_DIGIT_KEYS.get(k, _KEYPAD.get(k)))
        elif k == pygame.K_UP:
            self.digits[self.cursor] = 0 if d is None else (d + 1) % 10
        elif k == pygame.K_DOWN:
            self.digits[self.cursor] = 9 if d is None else (d - 1) % 10
        elif k == pygame.K_LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif k == pygame.K_RIGHT:
            self.cursor = min(self.length - 1, self.cursor + 1)
        elif k == pygame.K_BACKSPACE:
            self.backspace()
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.confirm()
        else:
            return False
        return True

    def draw(self, surf: pygame.Surface, stage, roles: dict, hit, screen: str, origin=(0, 0)) -> None:
        """입력 칸 + 터치 숫자 패드. screen 은 "pairing"(화면 전체) 또는 "admin"(패널 안, origin 이 패널 왼쪽 위).

        hit(rect, action) 은 칸 · 패드 칸의 탭 등록 (장면의 Scene.hit 이나 관리자 패널의 hit).
        locked 면 칸과 패드를 흐리게 그리고 눌러도 아무 일도 없다.
        """
        tk = stage.tokens
        D = stage.layout("dial")
        pw, ph = ui.numpad_size(D)
        if screen == "admin":
            A = stage.layout("admin")
            ox, oy = origin
            cell = A["dial_cell"]
            cells_c = (ox + A["panel"][0] // 2, oy + A["dial_y"])
            pad_rect = pygame.Rect(0, 0, pw, ph)
            pad_rect.midtop = (cells_c[0], oy + A["keypad_top"])
        else:
            L = stage.layout("pairing")
            cell = L["dial_cell"]
            cx = stage.x(stage.base_w / 2, "center")
            cells_c = (cx, stage.y(L["dial_y"], "center"))
            pad_rect = pygame.Rect(0, 0, pw, ph)
            if stage.orientation == "portrait":  # 엄지가 닿는 아래에 붙인다
                pad_rect.midbottom = (cx, stage.y(stage.base_h - L["keypad_bottom"], "bottom"))
            else:
                pad_rect.center = (cx, stage.y(L["keypad_y"], "center"))

        # 칸 묶음 (화살표까지) + 패드가 차지하는 영역 — 잠겼을 때 이 영역만 흐리게 섞는다
        cw = self.length * cell + (self.length - 1) * round(cell * D["dial_gap_ratio"])
        ch = round(cell * D["dial_height_ratio"])
        cells_box = pygame.Rect(0, 0, cw, ch + 2 * D["arrow"] * 2)
        cells_box.center = cells_c
        area = cells_box.union(pad_rect).clip(surf.get_rect())

        locked = self._locked()
        under = surf.subsurface(area).copy() if locked and area.width > 0 else None
        self._draw_cells(surf, stage, roles, hit, cells_c, cell, D)
        ui.numpad(surf, pad_rect, roles, self._press, hit, layout=D)
        if under is not None:
            drawn = surf.subsurface(area).copy()
            surf.blit(under, area)
            drawn.set_alpha(int(255 * tk["color"]["alpha"]["disabled"] + 0.5))
            surf.blit(drawn, area)

    def _draw_cells(self, surf, stage, roles, hit, center, cell: int, D: dict) -> None:
        tk = stage.tokens
        fixed = tk["color"]["fixed"]
        paper, dark = ui.hex_rgb(fixed["paper"]), ui.hex_rgb(fixed["dark_ink"])
        gap = round(cell * D["dial_gap_ratio"])
        h = round(cell * D["dial_height_ratio"])
        total = self.length * cell + (self.length - 1) * gap
        x0 = int(center[0] - total / 2)
        y0 = int(center[1] - h / 2)
        radius = tk["space"]["radius"]["card"]
        ring = tk["touch"]["focus_ring_px"]
        for i, d in enumerate(self.digits):
            r = pygame.Rect(x0 + i * (cell + gap), y0, cell, h)
            on = i == self.cursor
            ui.panel(surf, r, paper, radius=radius, border=roles["action"] if on else roles["line"],
                     border_w=ring if on else tk["touch"]["line_px"])
            if on and self.show_arrows:
                a = D["arrow"]
                ui.arrow(surf, (r.centerx, r.y - a), a, "up", roles["action"])
                ui.arrow(surf, (r.centerx, r.bottom + a), a, "down", roles["action"])
            if d is not None:
                if self.masked and not on:
                    ui.circle(surf, dark, r.center, cell / 7)
                else:
                    ui.text(surf, str(d), int(cell * D["digit_ratio"]), dark, r.center, face="number", ink=True)
            hit(r, lambda i=i: self._move_to(i))

    def _move_to(self, i: int) -> None:
        if not self._locked():
            self.cursor = i
