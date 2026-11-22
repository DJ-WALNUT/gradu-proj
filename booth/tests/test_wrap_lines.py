"""ui.wrap_lines — 줄바꿈과 말줄임."""

from __future__ import annotations

import pygame
import pytest

from walnut import ui



@pytest.fixture(autouse=True)
def _fonts():
    """다른 시험이 pygame 을 껐다 켠 뒤에도 글꼴을 쓸 수 있게 한다."""
    pygame.font.init()
    ui.clear_caches()


def w(s, size=40, face="body"):
    return ui.font(size, face, s).size(s)[0]


def test_fits_on_one_line():
    assert ui.wrap_lines("호두 가을 축제", 40, 1000) == ["호두 가을 축제"]


def test_word_wrap_keeps_words():
    out = ui.wrap_lines("Hello World foo bar", 40, 300, lines=3)
    assert len(out) >= 2 and " ".join(out) == "Hello World foo bar"


def test_korean_without_spaces_wraps_by_character():
    s = "가나다라마바사아자차카타파하" * 3
    out = ui.wrap_lines(s, 40, 400, lines=5)
    assert len(out) > 1 and "".join(out) == s and all(w(x) <= 400 for x in out)


def test_exactly_max_lines_has_no_ellipsis():
    s = "가나다라마바사아자차카타파하" * 2
    one = ui.wrap_lines(s, 40, 10000, lines=1)
    assert one == [s]
    two = ui.wrap_lines(s, 40, w(s) // 2 + 2, lines=2)
    assert len(two) == 2 and "…" not in "".join(two) and "".join(two) == s


def test_overflow_keeps_spaces_from_original_text():
    s = "Hello World foo bar baz qux quux corge grault garply"
    out = ui.wrap_lines(s, 40, 300, "body")
    assert out[0] == "Hello World"
    assert out[1].endswith("…") and out[1].startswith("foo bar baz q")


def test_overflow_ellipsis_fits_width():
    s = "아주 긴 행사 제목입니다 " * 12
    out = ui.wrap_lines(s, 40, 500, lines=2)
    assert len(out) == 2 and out[-1].endswith("…") and all(w(x) <= 500 for x in out)
