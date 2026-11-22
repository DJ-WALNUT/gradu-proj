"""기기 고유 설정(.env). 행사 설정은 번들에서 오고 여기엔 없다."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

# 지능형 촬영 기본값 (2026-11-22 사용자 결정: 켬). .env 의 BOOTH_BURST · BOOTH_SMART_CROP=0 으로 끈다.
# 시험은 conftest 에서 둘 다 False 로 바꿔 기존 경로를 기준으로 돈다.
DEFAULT_BURST = True
DEFAULT_SMART_CROP = True


@dataclass(frozen=True)
class Config:
    server_url: str
    camera_index: int
    camera_width: int
    camera_height: int
    remote_port: str          # "" = 자동, "off" = 끔
    fullscreen: bool
    orientation: str          # auto | landscape | portrait
    motion: bool              # 움직임 연출 (끄면 바로 전환)
    sync_interval: int | None  # 있으면 번들 값보다 우선
    data_dir: Path
    assets_dir: Path
    models_dir: Path
    burst: bool = False        # 지능형 촬영: 컷마다 연속 프레임에서 베스트 컷 고르기
    smart_crop: bool = False   # 지능형 촬영: 얼굴 기준 구도 보정
    capture_log: bool = False  # 컷마다 측정값을 data/logs 에 기록
    field_samples: bool = False  # 현장 시험 샘플: 버스트 후보 원본을 eval_data 에 저장 (field_consent 도 있어야 켜진다)
    field_consent: str = ""      # 샘플 촬영에 동의한 테스트 이름 (폴더 이름에 들어간다)
    printer_port: str = "dummy"  # 영수증 프린터: "" 자동(USB 1CBE:0002) · "COMx" · "off" · "dummy" — load() 는 PRINTER_PORT (없으면 "")
    dev: str = ""              # 개발자 모드: "" 끔 · "on" (--dev-mode) · "all" (--dev-mode-all, 베스트 컷 분석 화면)


def _int(env: Mapping, key: str, default: int) -> int:
    try:
        return int(str(env.get(key, "")).strip())
    except ValueError:
        return default


def _bool(env: Mapping, key: str, default: bool) -> bool:
    v = str(env.get(key, "")).strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _orientation(env: Mapping) -> str:
    v = str(env.get("BOOTH_ORIENTATION", "")).strip().lower()
    return v if v in ("landscape", "portrait") else "auto"


def dev_config(cfg: Config, mode: str) -> Config:
    """개발자 모드용 설정: 버스트 · 구도 보정 켬, 서버 없음, 데이터는 data-dev/ (실제 data/ 는 건드리지 않는다)."""
    return replace(cfg, burst=True, smart_crop=True, server_url="",
                   data_dir=cfg.data_dir.parent / "data-dev", dev=mode)


def load(env: Mapping | None = None, root: Path | None = None) -> Config:
    """env 가 없으면 root/.env 와 환경 변수를 읽는다. 잘못된 정수는 기본값."""
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    if env is None:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
        env = os.environ
    sync = _int(env, "SYNC_INTERVAL", 0)
    return Config(
        server_url=str(env.get("SERVER_URL", "")).strip().rstrip("/"),
        camera_index=_int(env, "CAMERA_INDEX", 0),
        camera_width=_int(env, "CAMERA_WIDTH", 1920),
        camera_height=_int(env, "CAMERA_HEIGHT", 1080),
        remote_port=str(env.get("REMOTE_PORT", "")).strip(),
        fullscreen=_bool(env, "BOOTH_FULLSCREEN", True),
        orientation=_orientation(env),
        motion=_bool(env, "BOOTH_MOTION", True),
        sync_interval=sync if sync > 0 else None,
        data_dir=root / "data",
        assets_dir=root / "assets",
        models_dir=root / "models",
        burst=_bool(env, "BOOTH_BURST", DEFAULT_BURST),
        smart_crop=_bool(env, "BOOTH_SMART_CROP", DEFAULT_SMART_CROP),
        capture_log=_bool(env, "BOOTH_CAPTURE_LOG", False),
        field_samples=_bool(env, "BOOTH_FIELD_SAMPLES", False),
        field_consent=str(env.get("BOOTH_FIELD_CONSENT", "")).strip(),
        printer_port=str(env.get("PRINTER_PORT", "")).strip(),
    )
