"""터치 시험 도구가 dummy 드라이버에서 오류 없이 돌고 로그를 남기는지."""

import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "touch_probe.py"


def _load():
    spec = importlib.util.spec_from_file_location("touch_probe", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_frames_5_로_깨끗이_끝나고_로그를_쓴다(tmp_path):
    log = tmp_path / "probe.log"
    code = _load().main(["--windowed", "--frames", "5", "--log", str(log)])
    assert code == 0
    text = log.read_text(encoding="utf-8")
    assert "logical=" in text  # 시작 줄에 논리 크기를 남긴다
