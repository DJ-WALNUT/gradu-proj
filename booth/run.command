#!/bin/bash
# 호두네사진관 부스 실행 (macOS). 설치는 installer/walnutstudio-setup.command 가 한다.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "가상환경이 없습니다. 'walnutstudio-setup.command' (설치 · 업데이트) 를 먼저 실행해 주세요."
  read -r -p "Enter 를 누르면 창을 닫습니다 " _ || true
  exit 1
fi
exec .venv/bin/python main.py "$@"
