"""pygame 공용 그리기 도구.

색은 고정 팔레트가 아니라 부르는 쪽이 넘긴다 (행사 색은 Theme.colors). 아래 상수는 행사와 무관한
경고·상태 표시용 기본색이다. 글자는 역할(face)로 고른다 — title · body · label · number (fonts.py).
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
import pygame

from . import fonts
from .booth_design import load as _load_tokens

FPS = 60

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def set_theme_font(path: Path | None) -> None:
    """행사 글꼴을 바꾸고 글자 캐시를 비운다."""
    fonts.set_event_font(path)
    clear_caches()


def clear_caches() -> None:
    _font.cache_clear()
    _text_surface.cache_clear()
    _ink_rect.cache_clear()
    _shape.cache_clear()
    _shadow.cache_clear()
    _gradient.cache_clear()


@lru_cache(maxsize=128)
def _font(path: str, size: int) -> pygame.font.Font:
    return pygame.font.Font(path, size)


def font(size: int, face: str = "body", s: str = "") -> pygame.font.Font:
    """s 를 그릴 수 있는 글꼴 (행사 글꼴에 없는 글자가 있으면 내장 글꼴)."""
    return _font(str(fonts.resolve(face, s)), max(6, int(size)))


@lru_cache(maxsize=512)
def _text_surface(text: str, size: int, color: tuple, face: str) -> pygame.Surface:
    return font(size, face, text).render(text, True, color)


def fit_size(s: str, size: int, max_width: int, face: str = "body") -> int:
    """max_width 를 넘으면 들어갈 때까지 줄인 크기 (행사 제목처럼 길이를 모르는 글자용)."""
    w = font(size, face, s).size(s)[0]
    return size if w <= max_width else max(10, int(size * max_width / w))


@lru_cache(maxsize=512)
def _ink_rect(text: str, size: int, face: str) -> pygame.Rect:
    """글자 이미지 안에서 실제로 칠해진 부분. 줄 높이의 위아래 여백을 뺀 '눈에 보이는 글자'."""
    return _text_surface(text, size, (0, 0, 0), face).get_bounding_rect()


def text(surf: pygame.Surface, s: str, size: int, color, pos, anchor: str = "center", shadow: tuple | None = None,
         face: str = "body", max_width: int | None = None, ink: bool = False) -> pygame.Rect:
    """anchor: center, midtop, topleft, midleft, midright, topright, midbottom ...

    ink=True 면 줄 높이가 아니라 실제 글자 모양으로 자리를 맞춘다 — 원·배지 안의 숫자처럼
    도형 한가운데에 와야 하는 글자에 쓴다.
    """
    if not s:
        return pygame.Rect(int(pos[0]), int(pos[1]), 0, 0)
    if max_width:
        size = fit_size(s, size, max_width, face)
    img = _text_surface(s, size, tuple(color), face)
    if ink:
        box = _ink_rect(s, size, face)
        placed = box.copy()
        setattr(placed, anchor, (int(pos[0]), int(pos[1])))
        rect = img.get_rect(topleft=(placed.x - box.x, placed.y - box.y))
    else:
        rect = img.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
    if shadow:
        sh = _text_surface(s, size, tuple(shadow), face)
        off = max(2, size // 22)
        surf.blit(sh, rect.move(off, off))
    surf.blit(img, rect)
    return rect


# ── 매끈한 도형 ──────────────────────────────────────────────────────
# pygame.draw 는 둥근 모서리를 안티앨리어싱 없이 칠해서 곡선이 계단처럼 보인다.
# 그래서 SUPERSAMPLE 배로 크게 그린 뒤 부드럽게 줄인다. 같은 모양은 캐시해서 한 번만 만든다.
SUPERSAMPLE = 3


@lru_cache(maxsize=256)
def _shape(size: tuple[int, int], radius: int, fill: tuple | None, border: tuple | None, border_w: int) -> pygame.Surface:
    """둥근 사각형 이미지. fill 은 RGBA(없으면 테두리만), border 는 RGB."""
    k = SUPERSAMPLE
    big = pygame.Surface((size[0] * k, size[1] * k), pygame.SRCALPHA)
    # 투명한 바깥도 같은 색으로 채워 둬야 줄일 때 가장자리가 검게 번지지 않는다
    big.fill((*(fill or border)[:3], 0))
    r = radius * k
    if border:
        pygame.draw.rect(big, (*border, 255), big.get_rect(), border_radius=r)
        inner = big.get_rect().inflate(-2 * border_w * k, -2 * border_w * k)
        pygame.draw.rect(big, fill or (*border, 0), inner, border_radius=max(0, r - border_w * k))
    else:
        pygame.draw.rect(big, fill, big.get_rect(), border_radius=r)
    return pygame.transform.smoothscale(big, size)


def rrect(surf, color, rect, radius: int, width: int = 0) -> None:
    """매끈한 둥근 사각형. width > 0 이면 테두리만. color 에 알파(4번째 값)를 줄 수 있다."""
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    radius = min(radius, rect.width // 2, rect.height // 2)
    if width:
        img = _shape(rect.size, radius, None, tuple(color[:3]), width)
    else:
        img = _shape(rect.size, radius, (*color[:3], color[3] if len(color) > 3 else 255), None, 0)
    surf.blit(img, rect)


def circle(surf, color, center, r: float, width: int = 0) -> None:
    """매끈한 원 (안티앨리어싱). width > 0 이면 고리."""
    pygame.draw.aacircle(surf, color, (int(center[0]), int(center[1])), max(1, int(r)), width)


def badge(surf, center, r: float, fill, s: str, size: int, color, face: str = "number",
          ring: tuple | None = None, ring_w: int = 4) -> None:
    """원 안에 글자 하나 (번호 · 순서). 글자는 실제 모양 기준으로 원 한가운데에 놓는다."""
    if ring:
        circle(surf, ring, center, r + ring_w)
    circle(surf, fill, center, r)
    text(surf, s, size, color, center, face=face, ink=True)


def panel(surf, rect, color=WHITE, radius: int = 28, alpha: int = 255, border: tuple | None = None,
          border_w: int = 0) -> None:
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    if radius <= 0 and not border:  # 각진 반투명 띠 — 계단이 생길 곡선이 없다
        tmp = pygame.Surface(rect.size, pygame.SRCALPHA)
        tmp.fill((*color[:3], alpha))
        surf.blit(tmp, rect)
        return
    radius = min(radius, rect.width // 2, rect.height // 2)
    surf.blit(_shape(rect.size, radius, (*color[:3], alpha), tuple(border[:3]) if border else None,
                     border_w or 4), rect)


def arrow(surf, center, size: int, direction: str, color) -> None:
    """direction: right | left | up | down"""
    cx, cy = center
    s = size / 2
    pts = {
        "right": [(cx - s, cy - s), (cx + s, cy), (cx - s, cy + s)],
        "left": [(cx + s, cy - s), (cx - s, cy), (cx + s, cy + s)],
        "up": [(cx - s, cy + s), (cx, cy - s), (cx + s, cy + s)],
        "down": [(cx - s, cy - s), (cx, cy + s), (cx + s, cy - s)],
    }[direction]
    pygame.draw.polygon(surf, color, pts)


def progress_ring(surf, center, r: int, frac: float, color, width: int = 12, back=WHITE) -> None:
    circle(surf, back, center, r, width)
    if frac > 0:
        # 굵은 arc 는 구멍·계단이 생겨서 크게 그려 줄인다
        k = SUPERSAMPLE
        big = pygame.Surface((r * 2 * k + 2 * k, r * 2 * k + 2 * k), pygame.SRCALPHA)
        big.fill((*color[:3], 0))
        rect = pygame.Rect(k, k, r * 2 * k, r * 2 * k)
        pygame.draw.arc(big, (*color[:3], 255), rect, math.pi / 2 - 2 * math.pi * min(1, frac), math.pi / 2, width * k)
        img = pygame.transform.smoothscale(big, (r * 2 + 2, r * 2 + 2))
        surf.blit(img, img.get_rect(center=(int(center[0]), int(center[1]))))


def bar(surf, rect, frac: float, color, back=(225, 232, 242), radius: int = 18) -> None:
    rect = pygame.Rect(rect)
    rrect(surf, back, rect, radius)
    if frac > 0:
        fill = rect.copy()
        fill.width = max(radius * 2, int(rect.width * min(1.0, frac)))
        rrect(surf, color, fill, radius)


def vertical_gradient(size, top, bottom) -> pygame.Surface:
    w, h = size
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    col = (np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t).astype(np.uint8)
    arr = np.repeat(col[:, None, :], w, axis=1)
    return pygame.surfarray.make_surface(arr.swapaxes(0, 1))


def lerp_color(a, b, t: float) -> tuple[int, int, int]:
    """두 색 사이 (t=0 이면 a, 1 이면 b)."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ink_on(bg) -> tuple[int, int, int]:
    """배경색 위에서 읽히는 글자색 (밝은 배경엔 검정, 어두운 배경엔 흰색)."""
    lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return (20, 20, 28) if lum > 160 else WHITE


# ── 카메라 프레임 ────────────────────────────────────────────────────
class CameraView:
    """카메라 RGB 프레임을 화면 영역에 '꽉 채워' 그린다 (넘치는 쪽은 잘라냄).

    landmark(0~1, 프레임 기준) → 화면 좌표 변환도 여기서 한다.
    """

    def __init__(self, rect):
        self.rect = pygame.Rect(rect)
        self.crop = (0.0, 0.0, 1.0, 1.0)  # 프레임 안에서 쓰는 영역 (x0, y0, x1, y1), 0~1

    def surface(self, frame: np.ndarray, dim: float = 0.0) -> pygame.Surface:
        import cv2

        fh, fw = frame.shape[:2]
        tw, th = self.rect.size
        scale = max(tw / fw, th / fh)
        cw, ch = tw / scale, th / scale
        x0 = (fw - cw) / 2
        y0 = (fh - ch) / 2
        self.crop = (x0 / fw, y0 / fh, (x0 + cw) / fw, (y0 + ch) / fh)
        sub = frame[int(y0): int(y0 + ch), int(x0): int(x0 + cw)]
        sub = cv2.resize(sub, (tw, th), interpolation=cv2.INTER_LINEAR)
        if dim > 0:
            sub = cv2.convertScaleAbs(sub, alpha=1 - dim)  # float 곱셈보다 훨씬 빠르다
        return pygame.image.frombuffer(np.ascontiguousarray(sub).tobytes(), (tw, th), "RGB")

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        x0, y0, x1, y1 = self.crop
        sx = self.rect.x + (x - x0) / (x1 - x0) * self.rect.width
        sy = self.rect.y + (y - y0) / (y1 - y0) * self.rect.height
        return int(sx), int(sy)


def np_to_surface(rgb: np.ndarray) -> pygame.Surface:
    h, w = rgb.shape[:2]
    return pygame.image.frombuffer(np.ascontiguousarray(rgb).tobytes(), (w, h), "RGB")


def pil_to_surface(img) -> pygame.Surface:
    """PIL 이미지 → RGBA Surface. 화면이 없을 때(로딩 중)도 쓸 수 있게 convert 하지 않고 복사만 한다."""
    img = img.convert("RGBA")
    return pygame.image.frombuffer(img.tobytes(), img.size, "RGBA").copy()


# ── 공용 그리기 (부스 디자인 체계) ───────────────────────────────────────
# 시안 shared/booth-design/mockups/screens/parts.js · prints.js · mockups.css 를 따른다.
# 값은 모두 토큰에서 읽는다. 색은 부르는 쪽이 theme.roles 를 넘긴다.

@lru_cache(maxsize=1)
def _tok() -> dict:
    return _load_tokens()


def _alpha(name: str) -> float:
    return _tok()["color"]["alpha"][name]


LABEL_WRAP_SCALE = 0.75  # 한 줄로 줄이면 이 비율보다 작아지는 글자는 두 줄로 나눈다
LABEL_LINE = 1.2  # 두 줄일 때 줄 간격 (글자 크기 배)


class ScaledSprite:
    """그려 둔 Surface 를 소수 배율로 얹는다 — 크기를 정수로 다시 만들면 1px 계단이 보여 끊겨 보인다.

    가장자리를 픽셀 안에서 섞어 그리므로 1px 보다 작은 변화도 화면에 나타난다.
    알파를 미리 곱해 두어 투명한 곳과 섞일 때 테두리가 어두워지지 않는다. 배율은 1 이하만 쓴다 (크게 그려 두고 줄인다).
    """

    def __init__(self, surface: pygame.Surface):
        alpha = pygame.surfarray.array_alpha(surface).astype(np.float32)
        rgb = pygame.surfarray.array3d(surface).astype(np.float32) * alpha[..., None] / 255.0
        rgba = np.dstack((np.round(rgb), alpha)).astype(np.uint8)
        self._rgba = np.ascontiguousarray(rgba.swapaxes(0, 1))

    def blit(self, dst: pygame.Surface, center: tuple[int, int], scale: float) -> None:
        import cv2

        h, w = self._rgba.shape[:2]
        cx, cy = (w - 1) / 2, (h - 1) / 2
        m = np.array([[scale, 0, cx * (1 - scale)], [0, scale, cy * (1 - scale)]], np.float64)
        out = cv2.warpAffine(self._rgba, m, (w, h), flags=cv2.INTER_LINEAR)
        img = pygame.image.frombuffer(out.tobytes(), (w, h), "RGBA")
        dst.blit(img, img.get_rect(center=center), special_flags=pygame.BLEND_PREMULTIPLIED)


def focus_margin(ring: int) -> int:
    """포커스 고리가 버튼 바깥으로 나가는 폭 — 버튼을 따로 그려 둘 때 이만큼 여백을 둔다."""
    return _tok()["space"]["step"][0] + ring


def action_button(surf, rect, label: str, roles: dict, *, kind: str = "action", focused: bool = False,
                  enabled: bool = True, ring: int = 6, size: int = 48, face: str = "title",
                  radius: int | None = None) -> pygame.Rect:
    """지금 누를 버튼(kind="action", 강조색 면)과 보조 버튼(kind="line", 테두리).

    focused 는 리모컨 입력일 때만 부르는 쪽이 켠다 (터치면 끈다). 고리는 버튼 밖에 그린다.
    enabled=False 면 color.alpha.disabled 로 흐리게 그리고 고리는 그리지 않는다.
    radius 가 None 이면 알약 (space.radius.button = pill).
    """
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return rect
    t = _tok()
    line_w = t["touch"]["line_px"]
    r = rect.height // 2 if radius is None else radius
    if kind == "action":
        fill, edge, ink = roles["action"], roles.get("action_edge"), roles["on_action"]
    else:
        fill, edge, ink = None, roles["line"], roles["title"]
    body = pygame.Surface(rect.size, pygame.SRCALPHA)
    local = body.get_rect()
    if fill:
        rrect(body, fill, local, r)
    if edge:
        rrect(body, edge, local, r, line_w)
    room = max(10, rect.width - 2 * t["space"]["step"][2])
    small = round(size * LABEL_WRAP_SCALE)
    if fit_size(label, size, room, face) < small and 2 * small * LABEL_LINE <= rect.height - 2 * line_w:
        # 한 줄로 줄이면 너무 작아지는 긴 이름은 작은 글자 두 줄로 (넘치면 …)
        lines = wrap_lines(label, small, room, face)
        step_y = small * LABEL_LINE
        y0 = local.centery - (len(lines) - 1) * step_y / 2
        for i, line in enumerate(lines):
            text(body, line, small, ink, (local.centerx, round(y0 + i * step_y)), face=face, max_width=room)
    else:
        text(body, label, size, ink, local.center, face=face, max_width=room)
    if not enabled:
        body.fill((255, 255, 255, int(255 * _alpha("disabled") + 0.5)), special_flags=pygame.BLEND_RGBA_MULT)
    if focused and enabled:
        margin = focus_margin(ring)
        rrect(surf, roles["line"], rect.inflate(2 * margin, 2 * margin), r + margin, ring)
    surf.blit(body, rect)
    return rect


def number_badge(surf, center, r: float, n, roles: dict, *, kind: str = "order", size: int | None = None) -> pygame.Rect:
    """번호 동그라미. kind="order"(고른 순서, 강조색) · "cut"(컷 번호, 인화지색 + 선)."""
    t = _tok()
    fx = t["color"]["fixed"]
    line_w = t["touch"]["line_px"]
    if kind == "order":
        fill, edge, ink = roles["action"], roles.get("action_edge"), roles["on_action"]
    else:
        fill, edge, ink = hex_rgb(fx["paper"]), roles["line"], hex_rgb(fx["dark_ink"])
    center = (int(center[0]), int(center[1]))
    circle(surf, edge or fill, center, r)
    if edge:
        circle(surf, fill, center, r - line_w)
    text(surf, str(n), size or t["type"]["size"]["badge"], ink, center, face="number", ink=True)
    ri = int(r)
    return pygame.Rect(center[0] - ri, center[1] - ri, 2 * ri, 2 * ri)


def hex_rgb(v: str) -> tuple[int, int, int]:
    """'#rrggbb' → (r, g, b)."""
    return int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16)


@lru_cache(maxsize=16)
def _shadow(size: tuple[int, int], blur: int, alpha: int, color: tuple) -> tuple[pygame.Surface, int]:
    """인화지 그림자 (가우시안 번짐). 돌려주는 값은 (그림, 사방 여백)."""
    import cv2

    pad = blur
    w, h = size[0] + 2 * pad, size[1] + 2 * pad
    mask = np.zeros((h, w), np.uint8)
    mask[pad:pad + size[1], pad:pad + size[0]] = 255
    k = blur | 1  # CSS blur 반지름 = 2σ
    mask = cv2.GaussianBlur(mask, (k * 2 + 1, k * 2 + 1), blur / 2)
    img = pygame.Surface((w, h), pygame.SRCALPHA)
    img.fill((*color, 0))
    pygame.surfarray.pixels_alpha(img)[:] = (mask.T.astype(np.float32) * alpha / 255).astype(np.uint8)
    return img, pad


def print_card(surf, photo: pygame.Surface, center, tokens: dict, roles: dict) -> pygame.Rect:
    """인화지에 붙인 사진 — 흰 여백 · 아래 필름 구멍 줄 · 그림자. 돌려주는 Rect 는 인화지 전체."""
    p = tokens["print"]
    b, bb = p["border"], p["border_bottom"]
    w, h = photo.get_width() + 2 * b, photo.get_height() + b + bb
    rect = pygame.Rect(0, 0, w, h)
    rect.center = (int(center[0]), int(center[1]))

    sh = p["shadow"]
    shadow, pad = _shadow((w, h), sh["blur"], int(255 * tokens["color"]["alpha"]["print_shadow"] + 0.5),
                          hex_rgb(tokens["color"]["fixed"]["dark_ink"]))
    surf.blit(shadow, (rect.x - pad, rect.y - pad + sh["y"]))

    pygame.draw.rect(surf, hex_rgb(tokens["color"]["fixed"]["paper"]), rect)
    surf.blit(photo, (rect.x + b, rect.y + b))

    # 아래 여백의 옅은 구멍 줄 — 한 칸(구멍 + 간격)을 줄 길이에 맞춰 늘려 딱 떨어지게 (CSS background-repeat: round)
    pf = p["perforation"]
    span = w - 2 * b
    pitch = pf["hole_w"] + pf["gap"]
    n = max(1, int(span / pitch + 0.5))
    step = span / n
    holes = pygame.Surface((span, pf["hole_h"]), pygame.SRCALPHA)
    ink = roles["perforation"]
    for i in range(n):
        x = int(i * step + pf["gap"] / 2 + 0.5)
        pygame.draw.rect(holes, (*ink, 255), (x, 0, pf["hole_w"], pf["hole_h"]))
    holes.fill((255, 255, 255, int(255 * tokens["color"]["alpha"]["perforation"] + 0.5)),
               special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(holes, (rect.x + b, rect.bottom - pf["inset"] - pf["hole_h"]))
    return rect


def numpad_size(layout: dict) -> tuple[int, int]:
    """숫자 패드 칸 묶음의 (폭, 높이) — 12칸을 layout.keypad_cols 열로 놓았을 때."""
    cols = layout["keypad_cols"]
    kw, kh = layout["keypad_key"]
    gap = layout["keypad_gap"]
    rows = -(-12 // cols)
    return cols * kw + (cols - 1) * gap, rows * kh + (rows - 1) * gap


def numpad(surf, rect, roles: dict, press: Callable[[str], None], hit, *, layout: dict, scale: float = 1.0) -> pygame.Rect:
    """숫자 패드 — 0~9 · 지움 · 확인. 칸마다 hit 을 하나씩 등록하고, 누르면 press(키) 를 부른다.

    press 가 받는 값: "0"~"9" · "back" · "ok". layout 은 stage.layout("dial") (keypad_cols · keypad_key · keypad_gap).
    칸 묶음은 rect 안에서 가로 가운데, 위쪽에 붙는다. 시안 parts.js 의 순서를 따른다 (가로는 한 줄, 세로는 3열).
    """
    t = _tok()
    cols = layout["keypad_cols"]
    kw, kh = layout["keypad_key"]
    gap = layout["keypad_gap"]
    rect = pygame.Rect(rect)
    keys = (list("123456789") + ["back", "0", "ok"]) if cols == 3 else (list("1234567890") + ["back", "ok"])
    grid = pygame.Rect((0, 0), numpad_size(layout))
    grid.midtop = (rect.centerx, rect.top)
    radius = t["space"]["radius"]["card"]
    for i, k in enumerate(keys):
        cell = pygame.Rect(grid.x + (i % cols) * (kw + gap), grid.y + (i // cols) * (kh + gap), kw, kh)
        word = {"back": "지움", "ok": "확인"}.get(k)
        action_button(surf, cell, word or k, roles, kind="action" if k == "ok" else "line", radius=radius,
                      size=int((t["type"]["size"]["caption"] if word else t["type"]["size"]["button"]) * scale),
                      face="title" if word else "number")
        hit(cell, lambda k=k: press(k))
    return grid


@lru_cache(maxsize=8)
def _gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> pygame.Surface:
    return vertical_gradient(size, top, bottom)


def backdrop(surf, roles: dict) -> None:
    """바탕 — background_top 에서 background_bottom 으로 가는 세로 그라데이션."""
    surf.blit(_gradient(surf.get_size(), tuple(roles["background_top"]), tuple(roles["background_bottom"])), (0, 0))


def credit_mark(surf, roles: dict, tokens: dict, size: int, x: int | None = None, bottom: int | None = None) -> pygame.Rect:
    """아래 제작 표기 — credit.text 를 color.alpha.credit 으로. x 는 글자 가운데, bottom 은 바닥에서 글자 아래까지."""
    c = tokens["credit"]
    img = _text_surface(c["text"], size, tuple(roles["credit"]), "title").copy()
    img.fill((255, 255, 255, int(255 * tokens["color"]["alpha"]["credit"] + 0.5)), special_flags=pygame.BLEND_RGBA_MULT)
    r = img.get_rect(midbottom=(surf.get_width() // 2 if x is None else x,
                                surf.get_height() - (c["bottom"] if bottom is None else bottom)))
    surf.blit(img, r)
    return r


def wrap_lines(s: str, size: int, max_width: int, face: str = "body", lines: int = 2) -> list[str]:
    """max_width 안에 들어가게 최대 lines 줄로 나눈다. 넘치면 마지막 줄 끝을 말줄임(…)으로 줄인다.

    공백이 있으면 낱말 단위로, 없으면 글자 단위로 나눈다 (긴 한글 제목도 두 줄까지 보이게).
    """
    f = font(size, face, s)

    def fits(t: str) -> bool:
        return f.size(t)[0] <= max_width

    s = s.strip()
    out: list[str] = []
    starts: list[int] = []  # 각 줄이 시작한 원문 위치
    pos = 0
    while pos < len(s) and len(out) < lines:
        while pos < len(s) and s[pos] == " ":
            pos += 1
        if pos >= len(s):
            break
        starts.append(pos)
        rest = s[pos:]
        if fits(rest):
            out.append(rest)
            pos = len(s)
            break
        cut = len(rest)
        while cut > 1 and not fits(rest[:cut]):
            cut -= 1
        sp = rest.rfind(" ", 0, cut + 1)
        if 0 < sp < cut:
            cut = sp
        out.append(rest[:cut].rstrip())
        pos += cut
    if pos < len(s) and out and s[pos:].strip():
        last = s[starts[-1]:]  # 마지막 줄은 원문에서 다시 잘라야 공백이 살아 있다
        while last and not fits(last + "…"):
            last = last[:-1]
        out[-1] = last.rstrip() + "…"
    return out or [""]
