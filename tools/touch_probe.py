"""터치 시험 도구 — 터치 모니터에서 탭이 한 번만 들어오는지, 논리 좌표가 손가락 위치와 맞는지 본다.

    .\\.venv\\Scripts\\python tools\\touch_probe.py              # 실제 부스와 같은 전체 화면 (SCALED + FULLSCREEN)
    .\\.venv\\Scripts\\python tools\\touch_probe.py --windowed   # 창 모드
    .\\.venv\\Scripts\\python tools\\touch_probe.py --frames 5   # 5프레임만 돌고 끝 (자동 시험용)

원본 이벤트(MOUSE* · FINGER*)와 TouchTracker 가 낸 동작을 화면 아래쪽과 로그 파일(touch_probe.log)에 남긴다.
Q 또는 ESC 로 끝낸다. 부스 앱과 같은 디스플레이 설정이라 여기서 보이는 좌표가 앱이 받는 좌표다.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from walnut import ui  # noqa: E402
from walnut.booth_design import load as load_tokens  # noqa: E402
from walnut.stage import geometry as stage_geometry  # noqa: E402
from walnut.touch import TouchTracker  # noqa: E402

SHOWN_LINES = 12
BG, INK, MARK, DIM = (24, 24, 28), (240, 240, 240), (255, 190, 70), (150, 150, 160)


def _raw_line(e) -> str | None:
    """원본 이벤트 한 줄. 관심 없는 이벤트는 None."""
    name = pygame.event.event_name(e.type)
    if e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        return f"{name} pos={tuple(e.pos)} button={e.button} touch={getattr(e, 'touch', '-')}"
    if e.type == pygame.MOUSEMOTION:
        return f"{name} pos={tuple(e.pos)} rel={tuple(e.rel)} touch={getattr(e, 'touch', '-')}"
    if e.type in (pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION):
        return f"{name} x={e.x:.4f} y={e.y:.4f} finger={getattr(e, 'finger_id', '-')}"
    return None


def _finger_px(e, size) -> str:
    return f"  -> px=({round(e.x * size[0])}, {round(e.y * size[1])})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="터치 시험 도구")
    ap.add_argument("--windowed", action="store_true", help="창 모드")
    ap.add_argument("--frames", type=int, default=0, help="이 프레임 수만 돌고 끝 (0 = 계속)")
    ap.add_argument("--log", type=Path, default=Path(__file__).resolve().parent / "touch_probe.log")
    args = ap.parse_args(argv)

    os.environ.setdefault("SDL_RENDER_SCALE_QUALITY", "linear")  # app.py 와 같게
    pygame.init()
    flags = pygame.SCALED
    if not args.windowed:
        flags |= pygame.FULLSCREEN
    try:
        display = tuple(pygame.display.get_desktop_sizes()[0])
    except (pygame.error, IndexError):
        display = (1920, 1080)
    tokens = load_tokens()
    stage = stage_geometry(display[0], display[1], tokens, "auto")
    screen = pygame.display.set_mode((stage.w, stage.h), flags)
    pygame.display.set_caption("호두네사진관 터치 시험")
    pygame.mouse.set_visible(True)
    size = (stage.w, stage.h)

    hotspot = stage.layout("idle")["admin_hotspot"]
    zone = pygame.Rect(0, 0, hotspot, hotspot)  # 앱에서 길게 누르기를 받는 구석
    tracker = TouchTracker(tokens["touch"], zone)
    clock = pygame.time.Clock()
    lines: deque[str] = deque(maxlen=SHOWN_LINES)

    with args.log.open("w", encoding="utf-8") as logf:
        def log(msg: str) -> None:
            lines.append(msg)
            logf.write(msg + "\n")
            logf.flush()

        log(f"시작 display={display} logical={size} flags={'SCALED' if args.windowed else 'SCALED|FULLSCREEN'} "
            f"long_press_zone={tuple(zone)} drag_threshold={tokens['touch']['drag_threshold_px']}px")

        frame, running = 0, True
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key in (pygame.K_q, pygame.K_ESCAPE)):
                    running = False
                    continue
                raw = _raw_line(e)
                if raw is not None:
                    log(raw + (_finger_px(e, size) if e.type in (pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION) else ""))
                for g in tracker.feed(e):
                    log(f"GESTURE {g.kind} pos={g.pos} start={g.start} d=({g.dx},{g.dy}) v=({g.vx:.0f},{g.vy:.0f})")
            for g in tracker.tick():
                log(f"GESTURE {g.kind} pos={g.pos} start={g.start}")
            _draw(screen, stage, zone, lines)
            pygame.display.flip()
            clock.tick(60)
            frame += 1
            if args.frames and frame >= args.frames:
                running = False
    pygame.quit()
    return 0


def _draw(screen, stage, zone, lines) -> None:
    w, h = stage.w, stage.h
    screen.fill(BG)
    pygame.draw.rect(screen, DIM, (0, 0, w, h), 2)
    pad = max(40, min(w, h) // 8)
    corners = [("왼쪽 위", 0, 0), ("오른쪽 위", w - 1, 0), ("왼쪽 아래", 0, h - 1), ("오른쪽 아래", w - 1, h - 1)]
    for label, cx, cy in corners:
        pygame.draw.circle(screen, MARK, (cx, cy), pad // 2, 3)
        pygame.draw.line(screen, MARK, (cx - pad // 3, cy), (cx + pad // 3, cy), 2)
        pygame.draw.line(screen, MARK, (cx, cy - pad // 3), (cx, cy + pad // 3), 2)
        text = f"{label} ({cx}, {cy})"
        surf = ui.font(22, "body", text).render(text, True, INK)
        x = cx + pad // 2 + 8 if cx == 0 else cx - pad // 2 - 8 - surf.get_width()
        y = cy + pad // 2 + 8 if cy == 0 else cy - pad // 2 - 8 - surf.get_height()
        screen.blit(surf, (min(max(x, 4), w - surf.get_width() - 4), min(max(y, 4), h - surf.get_height() - 4)))
    pygame.draw.rect(screen, MARK, zone, 2)  # 길게 누르기 구석
    note = f"길게 누르기 구석 {zone.w}x{zone.h} (왼쪽 위). 논리 크기 {w}x{h}. Q 또는 ESC 로 끝"
    screen.blit(ui.font(22, "body", note).render(note, True, MARK), (zone.right + 12, zone.y + 8))
    f = ui.font(20, "body", "한글 ()=:0")
    y0 = h // 2 - SHOWN_LINES * 14
    for i, ln in enumerate(lines):
        screen.blit(f.render(ln, True, INK), (max(pad, 40), y0 + i * 28))


if __name__ == "__main__":
    sys.exit(main())
