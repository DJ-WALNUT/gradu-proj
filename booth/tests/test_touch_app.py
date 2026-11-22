"""터치 입력의 앱 연결 — 탭 라우팅, 구석 길게 누르기, 연타 막기, 입력 종류."""

from __future__ import annotations

import pygame
import pytest

from walnut.scenes.base import Scene
from walnut.scenes.idle import IdleScene
from tests.test_app import ESC, key, paired_with_bundle, step  # noqa: F401


class FakeClock:
    def __init__(self, t: float = 100.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class Probe(Scene):
    """원 하나를 그리는 대신 hit 만 등록하는 시험용 장면."""

    def __init__(self, app, rect=(500, 400, 200, 100)):
        super().__init__(app)
        self.rect = pygame.Rect(rect)
        self.log: list[str] = []
        self.drags: list = []
        self.idle_t = 5.0

    def draw(self, surf):
        self.hit(self.rect, lambda: self.log.append("hit"))

    def drag(self, g):
        self.drags.append(g.kind)


def down(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)


def up(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)


def move(pos):
    return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(1, 0, 0))


@pytest.fixture
def app(make_app, paired_with_bundle):
    a = make_app()
    a.time_fn = clock = FakeClock()
    a.fake_clock = clock
    a._went_at = clock.t - 10  # 장면 전환 직후가 아닌 상태에서 시작
    step(a)
    return a


def tap(app, pos):
    step(app, down(pos), up(pos))


def test_tap_runs_top_hit_and_pokes(app):
    p = Probe(app)
    app.go(p)
    step(app)  # 그리면서 hit 등록
    app.fake_clock.t += 1
    order = []
    p.hit(pygame.Rect(500, 400, 200, 100), lambda: order.append("top"))  # 나중에 더한 것이 위
    tap(app, (550, 450))
    assert order == ["top"] and p.log == [] and p.idle_t == 0.0


def test_tap_poke_comes_before_action(app):
    p = Probe(app)
    app.go(p)
    step(app)
    app.fake_clock.t += 1
    seen = []
    p.hits.clear()
    p.hit(pygame.Rect(0, 300, 50, 50), lambda: seen.append(p.idle_t))
    tap(app, (10, 310))
    assert seen == [0.0]


def test_tap_outside_hit_does_not_poke(app):
    p = Probe(app)
    app.go(p)
    step(app)
    app.fake_clock.t += 1
    tap(app, (1500, 900))
    assert p.log == [] and p.idle_t == 5.0


def test_input_kind_follows_last_input(app):
    assert app.input_kind == "key"
    step(app, down((900, 900)))
    assert app.input_kind == "touch"
    step(app, key(pygame.K_LEFT))
    assert app.input_kind == "key"


def test_press_held_across_scene_change_is_not_a_tap(app):
    p = Probe(app)
    app.go(p)
    step(app)
    app.fake_clock.t += 1
    step(app, down((550, 450)))
    app.go(Probe(app))  # 손가락을 댄 채 장면이 넘어감
    app.fake_clock.t += 1
    step(app)
    step(app, up((550, 450)))
    assert p.log == [] and app.scene.log == []


def test_second_tap_right_after_go_is_dropped(app):
    p = Probe(app)
    app.go(p)
    step(app)
    t0 = app.fake_clock.t
    app.fake_clock.t = t0 + 0.29
    assert app.taps_blocked()
    tap(app, (550, 450))
    assert p.log == []
    app.fake_clock.t = t0 + 0.31
    assert not app.taps_blocked()
    tap(app, (550, 450))
    assert p.log == ["hit"]


def _hold_corner(app, secs):
    step(app, down((30, 30)))
    app.fake_clock.t += secs
    step(app)


@pytest.mark.parametrize("make", [
    lambda a: None,  # 시작 장면(대기) 그대로
    lambda a: a.go(Probe(a)),  # 다른 장면 하나 (장면 종류와 무관함을 보는 대표 사례)
])
def test_long_press_corner_opens_admin_on_any_scene(app, make):
    make(app)
    app.fake_clock.t += 1
    assert app.admin is None
    _hold_corner(app, 1.3)
    assert app.admin is not None


def test_release_after_long_press_taps_nothing(app):
    p = Probe(app, rect=(0, 0, 120, 120))
    app.go(p)
    step(app)
    app.fake_clock.t += 1
    _hold_corner(app, 1.3)
    assert app.admin is not None
    step(app, move((300, 300)), up((300, 300)))
    assert p.log == [] and p.drags == []
    assert app.admin is not None


def test_short_tap_in_corner_reaches_scene(app):
    p = Probe(app, rect=(0, 0, 120, 120))
    app.go(p)
    step(app)
    app.fake_clock.t += 1
    step(app, down((30, 30)))
    app.fake_clock.t += 0.2
    step(app, up((30, 30)))
    assert p.log == ["hit"] and app.admin is None


def test_corner_does_nothing_before_pairing(make_app):
    a = make_app()
    a.time_fn = clock = FakeClock()
    step(a)
    assert a.device is None
    step(a, down((30, 30)))
    clock.t += 2
    step(a)
    assert a.admin is None


def test_long_press_with_panel_open_does_nothing(app):
    app.fake_clock.t += 1
    _hold_corner(app, 1.3)
    panel = app.admin
    step(app, up((30, 30)))
    app.fake_clock.t += 1
    _hold_corner(app, 1.3)
    assert app.admin is panel


def test_admin_takes_taps_while_open(app):
    p = Probe(app)
    app.go(p)
    step(app)
    app.fake_clock.t += 1
    step(app, ESC)
    assert app.admin is not None
    step(app)  # 패널 그리기
    got = []
    app.admin.hit(pygame.Rect(500, 400, 200, 100), lambda: got.append(1))
    tap(app, (550, 450))
    assert got == [1] and p.log == []


def test_drag_goes_to_scene_only_without_panel(app):
    p = Probe(app)
    app.go(p)
    step(app)
    app.fake_clock.t += 1
    step(app, down((600, 450)), move((700, 450)), up((700, 450)))
    assert p.drags == ["drag", "drag_end"]
    step(app, ESC)
    step(app, down((600, 450)), move((700, 450)), up((700, 450)))
    assert p.drags == ["drag", "drag_end"]


def test_tap_error_goes_home_like_key_error(app):
    class Bad(Probe):
        def draw(self, surf):
            self.hit(self.rect, self.boom)

        def boom(self):
            raise RuntimeError("탭 오류 시험")

    app.go(Bad(app))
    step(app)
    app.fake_clock.t += 1
    tap(app, (550, 450))
    assert isinstance(app.scene, IdleScene)


def test_drag_pokes_scene_before_drag(app):
    p = Probe(app)
    order = []
    p.drag = lambda g: order.append((g.kind, p.idle_t))
    app.go(p)
    step(app)
    app.fake_clock.t += 1
    step(app, down((600, 450)), move((700, 450)))
    assert order == [("drag", 0.0)]
    p.idle_t = 7.0
    step(app, up((700, 450)))
    assert order[-1] == ("drag_end", 0.0)


def test_press_started_inside_guard_is_never_a_tap(app):
    p = Probe(app)
    app.go(p)
    step(app)
    t0 = app.fake_clock.t
    app.fake_clock.t = t0 + 0.25
    step(app, down((550, 450)))
    app.fake_clock.t = t0 + 0.35
    step(app, up((550, 450)))
    assert p.log == []
    app.fake_clock.t = t0 + 0.31
    tap(app, (550, 450))
    assert p.log == ["hit"]


def test_press_inside_guard_starts_no_long_press_or_drag(app):
    p = Probe(app)
    app.go(p)
    step(app)
    t0 = app.fake_clock.t
    app.fake_clock.t = t0 + 0.1
    step(app, down((30, 30)))
    app.fake_clock.t = t0 + 2
    step(app)
    assert app.admin is None
    step(app, down((600, 450)))  # 새 누름은 막힘 없이
    step(app, move((700, 450)), up((700, 450)))
    assert p.drags == ["drag", "drag_end"]
