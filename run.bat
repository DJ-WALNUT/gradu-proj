@echo off
rem 호두네사진관 부스 실행 (Windows). 설치 · 업데이트는 walnutstudio-setup.cmd 가 한다.
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo 가상환경이 없습니다. 설치 · 업데이트 파일 walnutstudio-setup.cmd 를 먼저 실행해 주세요.
  echo 개발 PC 라면: py -3.11 -m venv .venv 를 만든 뒤 .venv\Scripts\python -m pip install -r requirements.txt
  pause
  exit /b 1
)
.venv\Scripts\python main.py %*
if errorlevel 1 pause
