"""공용 그리기 — 버튼 · 인화지 · 번호 배지 · 숫자 패드 · 배경 · 표기."""

from types import SimpleNamespace

import pygame
import pytest

from walnut import ui
from walnut.booth_design import load, resolve_roles
from walnut.scenes.base import Scene

TOKENS = load()
EVENT = {"primary": "#2a6f97", "accent": "#e85d75", "bg_top": "#eaf4fb", "bg_bottom": "#cfe3f3"}
ROLES = {k: (tuple(int(v[i:i + 2], 16) for i in (1, 3, 5)) if v else None)
         for k, v in resolve_roles(TOKENS, EVENT).items()}
BG = (240, 240, 240)


@pytest.fixture(autouse=True)
def _pygame():
    pygame.init()
    ui.clear_caches()
    yield
    pygame.quit()


def canvas(w=900, h=500) -> pygame.Surface:
    s = pygame.Surface((w, h))
    s.fill(BG)
    return s


def blend(fg, bg, a):
    return tuple(int(fg[i] * a + bg[i] * (1 - a) + 0.5) for i in range(3))


def near(a, b, tol=2):
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))


def test_action_button_returns_rect_and_fills_with_action_color():
    s = canvas()
    r = ui.action_button(s, pygame.Rect(100, 100, 400, 120), "시작", ROLES)
    assert r == pygame.Rect(100, 100, 400, 120)
    assert near(s.get_at((130, 160)), ROLES["action"])


def test_line_button_is_transparent_inside_with_line_border():
    s = canvas()
    ui.action_button(s, pygame.Rect(100, 100, 400, 120), "", ROLES, kind="line")
    assert near(s.get_at((300, 130)), BG)
    assert near(s.get_at((300, 101)), ROLES["line"])  # 위쪽 테두리 (line_px 3)


def test_focus_ring_changes_pixels_outside_the_button():
    ring = TOKENS["touch"]["focus_ring_px"]
    a, b = canvas(), canvas()
    rect = pygame.Rect(100, 100, 400, 120)
    ui.action_button(a, rect, "시작", ROLES, focused=False)
    ui.action_button(b, rect, "시작", ROLES, focused=True, ring=ring)
    assert pygame.image.tobytes(a, "RGB") != pygame.image.tobytes(b, "RGB")
    gap = TOKENS["space"]["step"][0]
    assert near(b.get_at((300, 100 - gap - 1)), ROLES["line"])  # 간격 바깥의 고리
    assert near(a.get_at((300, 100 - gap - 1)), BG)


def test_disabled_button_uses_disabled_alpha():
    s = canvas()
    ui.action_button(s, pygame.Rect(100, 100, 400, 120), "시작", ROLES, enabled=False)
    expect = blend(ROLES["action"], BG, TOKENS["color"]["alpha"]["disabled"])
    assert near(s.get_at((130, 160)), expect)


def test_print_card_is_bigger_than_photo_by_border():
    p = TOKENS["print"]
    photo = pygame.Surface((300, 200))
    photo.fill((200, 30, 30))
    s = canvas()
    r = ui.print_card(s, photo, (450, 250), TOKENS, ROLES)
    assert r.size == (300 + 2 * p["border"], 200 + p["border"] + p["border_bottom"])
    assert r.center == (450, 250) or abs(r.centerx - 450) <= 1
    assert s.get_at((r.x + p["border"] + 5, r.y + p["border"] + 5))[:3] == (200, 30, 30)
    assert s.get_at((r.x + 3, r.y + 3))[:3] == (255, 255, 255)  # 인화지 여백


def test_print_card_draws_a_shadow_below():
    photo = pygame.Surface((300, 200))
    s = canvas()
    r = ui.print_card(s, photo, (450, 250), TOKENS, ROLES)
    below = s.get_at((r.centerx, r.bottom + 6))[:3]
    assert below != BG and sum(below) < sum(BG)


def test_print_card_perforation_marks_the_bottom_margin():
    p = TOKENS["print"]
    photo = pygame.Surface((300, 200))
    s = canvas()
    r = ui.print_card(s, photo, (450, 250), TOKENS, ROLES)
    row = r.bottom - p["perforation"]["inset"] - p["perforation"]["hole_h"] // 2
    colors = {tuple(s.get_at((x, row))[:3]) for x in range(r.x + p["border"], r.right - p["border"])}
    assert len(colors) >= 2  # 구멍과 종이색이 번갈아 나온다


def test_number_badge_order_vs_cut_kinds():
    s = canvas()
    ui.number_badge(s, (100, 100), 30, 3, ROLES)
    assert near(s.get_at((100, 76)), ROLES["action"]) or near(s.get_at((78, 100)), ROLES["action"])


def _scene():
    return Scene(SimpleNamespace())


DIAL_L = TOKENS["layout"]["dial"]["landscape"]
DIAL_P = TOKENS["layout"]["dial"]["portrait"]


def test_numpad_keys_cover_digits_back_ok():
    pressed = []
    scene = _scene()
    s = canvas(1600, 300)
    r = ui.numpad(s, pygame.Rect(0, 100, 1600, 200), ROLES, pressed.append, scene.hit, layout=DIAL_L)
    kw, kh = DIAL_L["keypad_key"]
    gap = DIAL_L["keypad_gap"]
    assert len(scene.hits._items) == 12
    for i in range(12):
        scene.hits.tap((r.x + i * (kw + gap) + kw // 2, r.y + kh // 2))
    assert pressed == list("1234567890") + ["back", "ok"]
    assert r.height == kh


def test_numpad_portrait_three_columns():
    pressed = []
    scene = _scene()
    s = canvas(1080, 900)
    r = ui.numpad(s, pygame.Rect(0, 100, 1080, 700), ROLES, pressed.append, scene.hit, layout=DIAL_P)
    kw, kh = DIAL_P["keypad_key"]
    gap = DIAL_P["keypad_gap"]
    assert r.size == (3 * kw + 2 * gap, 4 * kh + 3 * gap)
    scene.hits.tap((r.x + kw // 2, r.bottom - kh // 2))
    assert pressed == ["back"]
    scene.hits.tap((r.x + kw + gap + kw // 2, r.bottom - kh // 2))
    assert pressed == ["back", "0"]


# ── 배경 · 표기 ─────────────────────────────────────────────────────

@pytest.fixture
def app(make_app):
    return make_app()


def test_backdrop_is_vertical_gradient_of_role_colors(app):
    s = pygame.Surface(app.screen.get_size())
    app._draw_backdrop(s)
    assert near(s.get_at((5, 0)), app.theme.roles["background_top"], 3)
    assert near(s.get_at((5, s.get_height() - 1)), app.theme.roles["background_bottom"], 3)


def test_credit_is_drawn_when_visible(app, monkeypatch):
    s = pygame.Surface(app.screen.get_size())
    app._draw_backdrop(s)
    before = pygame.image.tobytes(s, "RGB")
    app._draw_credit(s)
    assert pygame.image.tobytes(s, "RGB") != before


def test_credit_is_skipped_when_not_visible(app, monkeypatch):
    monkeypatch.setattr("walnut.app.credit_visible", lambda settings: False)
    s = pygame.Surface(app.screen.get_size())
    app._draw_backdrop(s)
    before = pygame.image.tobytes(s, "RGB")
    app._draw_credit(s)
    assert pygame.image.tobytes(s, "RGB") == before


def test_credit_follows_scene_credit_x(app):
    app.scene.layout_name = "capture"
    app.stage.layout("capture")["credit_x"] = 170  # 가로 토큰에 있는 값 (세로면 없음)
    s = pygame.Surface(app.screen.get_size())
    app._draw_backdrop(s)
    app._draw_credit(s)
    base = pygame.Surface(app.screen.get_size())
    app._draw_backdrop(base)
    diff = [x for x in range(s.get_width()) for y in (s.get_height() - 30,) if s.get_at((x, y)) != base.get_at((x, y))]
    assert diff and max(diff) < 400
