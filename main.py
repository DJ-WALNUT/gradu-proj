"""호두네사진관 부스 실행.

    python main.py                 # 전체 화면 (.env 의 BOOTH_FULLSCREEN)
    python main.py --windowed      # 창 모드 (개발용)
    python main.py --no-camera     # 카메라 없이 화면 흐름만 확인
    python main.py --list-cameras  # 연결된 카메라 번호 확인
    python main.py --dev-mode      # 개발자 모드: 연결 코드 없이 기본 번들 + 버스트샷
    python main.py --dev-mode-all  # 개발자 모드 + 컷마다 베스트 컷 분석 화면
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# 어디서 실행하든 booth/ 기준으로 동작하게 한다 (바로가기·작업 스케줄러 대비).
os.chdir(Path(__file__).resolve().parent)
os.environ.setdefault("GLOG_minloglevel", "2")  # MediaPipe 로그 줄이기
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="호두네사진관 부스")
    ap.add_argument("--windowed", action="store_true", help="창 모드")
    ap.add_argument("--no-camera", action="store_true", help="카메라 없이 실행")
    ap.add_argument("--list-cameras", action="store_true", help="카메라 번호 확인")
    ap.add_argument("--frames", type=int, default=None, help=argparse.SUPPRESS)  # 실행 확인용: N 프레임 뒤 종료
    dev = ap.add_mutually_exclusive_group()
    dev.add_argument("--dev-mode", action="store_true",
                     help="개발자 모드: 연결 코드 없이 기본 번들로 시작하고 버스트샷을 켠다")
    dev.add_argument("--dev-mode-all", action="store_true",
                     help="개발자 모드 + 컷마다 베스트 컷이 골라지는 과정을 보여 준다")
    return ap.parse_args(argv)


def dev_mode(args: argparse.Namespace) -> str:
    """"" (일반) · "on" (--dev-mode) · "all" (--dev-mode-all)."""
    return "all" if args.dev_mode_all else "on" if args.dev_mode else ""


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # 한국어 Windows 콘솔(cp949)에 없는 글자(— 등)로 죽지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.list_cameras:
        from walnut.camera import list_cameras

        list_cameras()
        return

    from walnut import config
    from walnut.app import App

    cfg = config.load()
    mode = dev_mode(args)
    if mode:
        from walnut import model_files

        cfg = config.dev_config(cfg, mode)
        try:  # 모델 없이 뜨면 버스트샷이 조용히 꺼진 채 돈다 — 그 전에 받아 둔다
            got = model_files.ensure(cfg.models_dir, on_start=lambda name: print(
                f"얼굴 모델을 내려받는 중입니다 (약 4MB, 처음 한 번): {name}", flush=True))
        except OSError as exc:
            print(f"얼굴 모델을 내려받지 못했습니다: {exc}")
            print("인터넷 연결을 확인하고 다시 실행하거나, python tools/download_models.py 를 먼저 실행해 주세요.")
            sys.exit(1)
        if got:
            print(f"얼굴 모델을 내려받았습니다: {', '.join(got)}")
        print(f"개발자 모드: 사진과 기록은 {cfg.data_dir} 에 남습니다")

    App(cfg, no_camera=args.no_camera, windowed=args.windowed).run(max_frames=args.frames)


if __name__ == "__main__":
    main()
