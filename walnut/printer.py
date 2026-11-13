"""프린터. 지금은 더미만 있다 — 인쇄할 이미지를 data/print_spool/ 에 PNG 로 쌓는다."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from PIL import Image

log = logging.getLogger(__name__)


class Printer(Protocol):
    def available(self) -> bool: ...

    def print(self, image: Image.Image, copies: int, *, token: str = "") -> None: ...


class DummyPrinter:
    def __init__(self, spool: Path, clock: Callable[[], datetime] = datetime.now) -> None:
        self.spool = Path(spool)
        self._clock = clock

    def available(self) -> bool:
        return True

    def print(self, image: Image.Image, copies: int, *, token: str = "") -> None:
        self.spool.mkdir(parents=True, exist_ok=True)
        name = f"{self._clock():%Y%m%d-%H%M%S}_{token}_x{copies}.png"
        path = self.spool / name
        tmp = path.with_name(path.name + ".tmp")
        image.save(tmp, format="PNG")
        os.replace(tmp, path)  # 반쯤 쓴 파일을 남기지 않는다
        log.info("[printer] 더미 인쇄 %d매 → %s", copies, path)
