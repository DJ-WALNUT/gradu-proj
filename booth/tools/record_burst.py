"""평가용 시퀀스 녹화 도구 — 실제 웹캠으로 셔터 앞뒤 짧은 연속 프레임을 찍어 둔다.

    .\\.venv\\Scripts\\python tools\\record_burst.py --subject 홍길동 --consent --conditions 눈감음 역광 2명
    .\\.venv\\Scripts\\python tools\\record_burst.py --delete-subject 홍길동

S 또는 Enter 로 카운트다운(3초)을 시작하고, 끝나면 Space 로 셔터를 찍는다. 셔터 -0.7 ~ +0.3초를
JPEG 품질 95 로 booth/eval_data/<시각>_<피험자>/ 에 저장한다 (000.jpg ... 과 meta.json).
Q 또는 ESC 로 끝낸다. 프레임은 카메라가 준 그대로(거울 반전 없음)다.

원본 얼굴 사진이 디스크에 남는 유일한 경로다. 촬영 동의를 받은 사람만 찍고(--consent),
요청이 있으면 --delete-subject 로 지운다. 이 도구는 아무것도 업로드하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from walnut.burst import JPEG_QUALITY, TimedFrame, load_sequence, save_sequence  # noqa: E402,F401 (다른 도구가 여기서 가져간다)

EVAL_ROOT = Path(__file__).resolve().parent.parent / "eval_data"
BEFORE_SEC, AFTER_SEC = 0.7, 0.3   # 셔터 앞뒤로 남기는 길이
COUNTDOWN_SEC = 3


def _safe_name(s: str) -> str:
    """폴더 이름에 넣어도 eval_data 밖으로 나가지 못하게 문자만 남긴다."""
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE).strip("_.")
    return s[:40] or "subject"


def sequence_dir(root: Path, subject: str, stamp: str) -> Path:
    return Path(root) / f"{stamp}_{_safe_name(subject)}"


def delete_subject(root: Path, subject: str) -> int:
    """meta.json 의 subject 가 정확히 같은 시퀀스 폴더만 지우고 그 수를 돌려준다."""
    root, n = Path(root), 0
    if not root.is_dir():
        return 0
    for d in root.iterdir():
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # 읽을 수 있는 meta.json 이 없는 폴더는 건드리지 않는다
        if isinstance(meta, dict) and meta.get("subject") == subject:
            shutil.rmtree(d)
            n += 1
    return n


def record(args) -> int:
    """카메라를 열어 시퀀스를 찍는다 (실제 웹캠 · 화면 필요 — 자동 시험 없음)."""
    import pygame

    from walnut import config, ui
    from walnut.burst import FrameRing
    from walnut.camera import Camera

    cfg = config.load()
    ring = FrameRing()
    camera = Camera(cfg.camera_index, cfg.camera_width, cfg.camera_height, ring=ring)
    pygame.init()
    screen = pygame.display.set_mode((960, 600))
    pygame.display.set_caption("호두네사진관 시퀀스 녹화")
    clock = pygame.time.Clock()
    state, t_state, shutter_t, saved = "ready", 0.0, 0.0, 0
    msg = ""

    def say(text: str, y: int, size: int = 28, color=(240, 240, 240)) -> None:
        surf = ui.font(size, "body", text).render(text, True, color)
        screen.blit(surf, ((960 - surf.get_width()) // 2, y))

    try:
        running = True
        while running:
            now = time.monotonic()
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key in (pygame.K_q, pygame.K_ESCAPE)):
                    running = False
                elif e.type == pygame.KEYDOWN and state == "ready" and e.key in (pygame.K_s, pygame.K_RETURN):
                    state, t_state, msg = "count", now, ""
                elif e.type == pygame.KEYDOWN and state == "shutter" and e.key == pygame.K_SPACE:
                    shutter_t = now
                    state, t_state = "after", now
            if state == "count" and now - t_state >= COUNTDOWN_SEC:
                state = "shutter"
            if state == "after" and now - shutter_t >= AFTER_SEC:
                frames = camera.frames_between(shutter_t - BEFORE_SEC, shutter_t + AFTER_SEC)
                if not frames:
                    msg = "프레임이 없어 저장하지 않았습니다 (카메라 연결을 확인하세요)"
                else:
                    d = sequence_dir(EVAL_ROOT, args.subject, datetime.now().strftime("%Y%m%d-%H%M%S"))
                    h, w = frames[0].rgb.shape[:2]
                    save_sequence(d, frames, shutter_t, {
                        "subject": args.subject, "conditions": list(args.conditions),
                        "camera": [w, h], "fps": float(f"{camera.fps:.1f}"),
                    })
                    saved += 1
                    msg = f"저장함: {d.name} ({len(frames)}장)"
                state = "ready"
            screen.fill((24, 24, 28))
            _, rgb = camera.read()
            if rgb is not None:
                surf = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
                screen.blit(pygame.transform.smoothscale(surf, (640, 360)), (160, 20))
            else:
                say("카메라 프레임이 없습니다", 180)
            if state == "count":
                say(str(max(1, COUNTDOWN_SEC - int(now - t_state))), 400, 96, (255, 190, 70))
            elif state == "shutter":
                say("지금! Space 로 셔터", 420, 40, (255, 190, 70))
            elif state == "after":
                say("찍는 중...", 420, 40)
            else:
                say("S 또는 Enter: 카운트다운 시작   Q / ESC: 끝", 420)
            if msg:
                say(msg, 500, 24, (150, 200, 150))
            say(f"피험자 {args.subject}  ·  조건 {' '.join(args.conditions) or '-'}  ·  이번에 {saved}개 저장", 550, 20, (150, 150, 160))
            pygame.display.flip()
            clock.tick(60)
    finally:
        camera.release()
        pygame.quit()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="평가용 시퀀스 녹화 도구 (아무것도 업로드하지 않는다)")
    ap.add_argument("--subject", help="피험자 이름 (폴더 이름과 meta.json 에 남는다)")
    ap.add_argument("--consent", action="store_true", help="피험자에게 원본 사진 저장 동의를 받았다")
    ap.add_argument("--conditions", nargs="*", default=[], help="조건 표시 (눈감음 측면 움직임 역광 2명 ...)")
    ap.add_argument("--delete-subject", metavar="이름", help="이 피험자의 시퀀스를 모두 지우고 끝낸다")
    args = ap.parse_args(argv)

    if args.delete_subject is not None:
        n = delete_subject(EVAL_ROOT, args.delete_subject)
        print(f"'{args.delete_subject}' 시퀀스 {n}개를 지웠습니다.")
        return 0
    if not args.subject or not args.consent:
        ap.error("--subject 와 --consent 가 모두 필요합니다 (촬영 동의를 받은 피험자만 녹화합니다)")
    return record(args)


if __name__ == "__main__":
    sys.exit(main())
