"""터치 인식기 — 탭 · 끌기 · 길게 누르기 (시계는 주입)."""

import pygame
import pytest

from walnut.booth_design import load
from walnut.touch import HitMap, TouchTracker

ZONE = pygame.Rect(0, 0, 100, 100)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def down(pos, button=1):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)


def move(pos):
    return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(1, 0, 0))


def up(pos, button=1):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tracker(clock):
    return TouchTracker(load()["touch"], zone=ZONE, clock=clock)


def kinds(gs):
    return [g.kind for g in gs]


def test_short_press_is_tap(tracker):
    assert tracker.feed(down((300, 300))) == []
    gs = tracker.feed(up((300, 300)))
    assert kinds(gs) == ["tap"]
    assert gs[0].pos == (300, 300)


def test_move_past_threshold_is_drag(tracker, clock):
    tracker.feed(down((300, 300)))
    clock.t = 0.05
    gs = tracker.feed(move((313, 300)))
    assert kinds(gs) == ["drag"]
    assert (gs[0].dx, gs[0].dy, gs[0].start) == (13, 0, (300, 300))
    clock.t = 0.1
    end = tracker.feed(up((313, 300)))
    assert kinds(end) == ["drag_end"]


def test_threshold_is_strictly_greater(tracker):
    tracker.feed(down((300, 300)))
    assert tracker.feed(move((312, 300))) == []
    assert kinds(tracker.feed(up((312, 300)))) == ["tap"]


def test_move_under_threshold_stays_tap(tracker):
    tracker.feed(down((300, 300)))
    assert tracker.feed(move((311, 300))) == []
    assert kinds(tracker.feed(up((311, 300)))) == ["tap"]


def test_drag_stays_drag_after_returning(tracker):
    tracker.feed(down((300, 300)))
    tracker.feed(move((330, 300)))
    gs = tracker.feed(move((300, 300)))
    assert kinds(gs) == ["drag"]
    assert kinds(tracker.feed(up((300, 300)))) == ["drag_end"]


def test_drag_end_velocity(tracker, clock):
    tracker.feed(down((300, 300)))
    clock.t = 0.05
    tracker.feed(move((320, 300)))
    clock.t = 0.10
    tracker.feed(move((360, 300)))
    clock.t = 0.15
    (end,) = tracker.feed(up((360, 300)))
    # 창(160ms) 안 첫 표본은 누른 점(t=0) 이 아니라 마지막 160ms 안의 표본 → 모두 포함
    assert end.vx == pytest.approx(60 / 0.15)
    assert end.vy == 0


def test_drag_end_velocity_ignores_old_samples(tracker, clock):
    tracker.feed(down((300, 300)))
    clock.t = 0.05
    tracker.feed(move((400, 300)))
    clock.t = 1.0
    tracker.feed(move((400, 301)))
    clock.t = 1.05
    (end,) = tracker.feed(up((400, 305)))
    assert end.vx == 0
    assert end.vy == pytest.approx(4 / 0.05)


def test_drag_end_zero_velocity_when_no_time_passed(tracker):
    tracker.feed(down((300, 300)))
    tracker.feed(move((330, 300)))
    (end,) = tracker.feed(up((330, 300)))
    assert (end.vx, end.vy) == (0, 0)


def test_long_press_in_zone(tracker, clock):
    tracker.feed(down((50, 50)))
    clock.t = 1.19
    assert tracker.tick() == []
    clock.t = 1.2
    assert kinds(tracker.tick()) == ["long"]
    assert tracker.tick() == []
    assert tracker.feed(up((50, 50))) == []


def test_long_press_outside_zone_is_tap(tracker, clock):
    tracker.feed(down((300, 300)))
    clock.t = 3.0
    assert tracker.tick() == []
    assert kinds(tracker.feed(up((300, 300)))) == ["tap"]


def test_no_zone_never_long(clock):
    t = TouchTracker(load()["touch"], clock=clock)
    t.feed(down((50, 50)))
    clock.t = 3.0
    assert t.tick() == []


def test_drag_cancels_long_press(tracker, clock):
    tracker.feed(down((50, 50)))
    clock.t = 0.5
    tracker.feed(move((90, 50)))
    clock.t = 2.0
    assert tracker.tick() == []
    assert kinds(tracker.feed(up((90, 50)))) == ["drag_end"]


def test_cancel_drops_the_release(tracker):
    tracker.feed(down((300, 300)))
    tracker.cancel()
    assert tracker.feed(up((300, 300))) == []


def test_cancel_drops_motion_and_tick(tracker, clock):
    tracker.feed(down((50, 50)))
    tracker.cancel()
    assert tracker.feed(move((90, 50))) == []
    clock.t = 3.0
    assert tracker.tick() == []


def test_release_without_press_yields_nothing(tracker):
    assert tracker.feed(up((10, 10))) == []
    assert tracker.feed(move((10, 10))) == []


def test_only_left_button(tracker):
    assert tracker.feed(down((300, 300), button=3)) == []
    assert tracker.feed(down((300, 300), button=4)) == []
    assert tracker.feed(up((300, 300), button=3)) == []
    assert tracker.feed(up((300, 300), button=4)) == []
    tracker.feed(down((300, 300)))
    assert tracker.feed(up((300, 300), button=3)) == []  # 다른 버튼 뗌은 눌림을 끝내지 않는다
    assert kinds(tracker.feed(up((300, 300)))) == ["tap"]


def test_other_events_ignored(tracker):
    assert tracker.feed(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a)) == []


def test_hitmap_top_wins_and_miss_is_false():
    hits = HitMap()
    calls = []
    hits.add(pygame.Rect(0, 0, 100, 100), lambda: calls.append("back"))
    hits.add(pygame.Rect(40, 40, 100, 100), lambda: calls.append("front"))
    assert hits.tap((50, 50)) is True
    assert calls == ["front"]
    assert hits.tap((10, 10)) is True
    assert calls == ["front", "back"]
    assert hits.tap((500, 500)) is False
    hits.clear()
    assert hits.tap((10, 10)) is False


def test_hitmap_action_exception_propagates():
    hits = HitMap()

    def boom():
        raise RuntimeError("x")

    hits.add(pygame.Rect(0, 0, 10, 10), boom)
    with pytest.raises(RuntimeError):
        hits.tap((1, 1))
