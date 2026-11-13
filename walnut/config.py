"""기기 고유 설정(.env). 행사 설정은 번들에서 오고 여기엔 없다."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping


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
    """개발자 모드용 설정: 버스트 켬, 서버 없음, 데이터는 data-dev/ (실제 data/ 는 건드리지 않는다)."""
    return replace(cfg, burst=True, smart_crop=False, server_url="",
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
        burst=_bool(env, "BOOTH_BURST", False),
        smart_crop=_bool(env, "BOOTH_SMART_CROP", False),
        capture_log=_bool(env, "BOOTH_CAPTURE_LOG", False),
    )
