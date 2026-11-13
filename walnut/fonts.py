"""글꼴 역할 — 화면에서 쓰는 글꼴을 역할로 고른다.

    title    큰 제목 · 행사 이름 · 카운트다운        (행사 글꼴이 있으면 그것)
    body     안내문 · 운영 문구                       (행사 글꼴이 있으면 그것)
    label    버튼 · 짧은 라벨                         Paperlogy ExtraBold
    number   숫자 (다이얼 · 남은 시간)                Paperlogy Black

행사 글꼴(Theme.font_path)에 그 문자열의 글자가 하나라도 없으면 그 문자열만 내장 Paperlogy 로 그린다.
Paperlogy 에는 ★ ♥ 가 없다 (↑↓←→ ● · … 는 있다). 그 밖의 기호는 도형으로 그린다 (ui.circle, ui.arrow).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_D = Path(__file__).resolve().parent.parent / "assets" / "fonts"

FILES: dict[str, Path] = {
    "title": _D / "Paperlogy-8ExtraBold.ttf",
    "body": _D / "Paperlogy-5Medium.ttf",
    "label": _D / "Paperlogy-8ExtraBold.ttf",
    "number": _D / "Paperlogy-9Black.ttf",
}

EVENT_FACES = ("title", "body")  # 행사 글꼴로 바꾸는 역할

_event: Path | None = None


def set_event_font(path: Path | None) -> None:
    """행사 글꼴을 바꾼다 (None 이면 내장). ui 쪽 캐시는 ui.set_theme_font 가 비운다.
    열어 둔 글꼴 객체(_probe)도 놓는다 — 윈도에서는 열린 파일을 지울 수 없어 옛 글꼴 에셋 정리가 막힌다."""
    global _event
    _event = Path(path) if path else None
    clear_caches()


@lru_cache(maxsize=8)
def _probe(path: str):
    import pygame.freetype

    if not pygame.freetype.get_init():
        pygame.freetype.init()
    return pygame.freetype.Font(path, 24)


@lru_cache(maxsize=2048)
def covers(path: str, text: str) -> bool:
    """path 글꼴에 text 의 글자가 모두 있는가 (공백 제외). 열 수 없으면 False."""
    chars = "".join(c for c in set(text) if not c.isspace())
    if not chars:
        return True
    try:
        return all(m is not None for m in _probe(path).get_metrics(chars))
    except Exception:
        return False


@lru_cache(maxsize=2048)
def resolve(face: str, text: str = "") -> Path:
    """이 문자열을 그릴 글꼴 파일."""
    if _event is not None and face in EVENT_FACES and covers(str(_event), text):
        return _event
    return FILES[face]


def clear_caches() -> None:
    """pygame 을 다시 초기화했을 때 (테스트에서 앱을 여러 번 만들 때)."""
    _probe.cache_clear()
    covers.cache_clear()
    resolve.cache_clear()
