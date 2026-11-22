"""현장 기록 · 샘플 · 내보내기 · 분석 시험 (Task 5A).

세 단계: 1 진단 로그(항상) · 2 촬영 기록(BOOTH_CAPTURE_LOG) · 3 샘플(BOOTH_FIELD_SAMPLES + BOOTH_FIELD_CONSENT).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pygame
import pytest
from PIL import Image

from tests.test_app import paired_with_bundle  # noqa: F401
from tests.test_capture_burst import BURST, FakeAnalyzer, _restore_sfx, make_result, start, tick  # noqa: F401
from tools.record_burst import load_sequence
from walnut import config, fieldlog
from walnut.burst import TimedFrame
from walnut.scenes.capture import BURST_AFTER, COLLECT, CaptureScene

LOG_ON = {"BOOTH_CAPTURE_LOG": "1"}
SAMPLES_ON = {"BOOTH_FIELD_SAMPLES": "1", "BOOTH_FIELD_CONSENT": "지인테스트"}


def frames(n: int = 3, w: int = 32, h: int = 24, t0: float = 10.0) -> list[TimedFrame]:
    return [TimedFrame(t0 + i * 0.1, np.full((h, w, 3), 40 * i, np.uint8)) for i in range(n)]


def records(app) -> list[dict]:
    path = app.capture_log.path
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.fixture
def app(start):
    """app(env) → 촬영 장면에 들어선 (app, scene). 분석기는 FakeAnalyzer, 버스트 켬."""
    def _make(env: dict | None = None):
        return start({**BURST, **(env or {})}, FakeAnalyzer())
    return _make


def take_burst_cut(app, scene) -> None:
    """카운트다운 → 수집 → 분석 결과까지 컷 하나."""
    for _ in range(200):
        if scene.state == COLLECT:
            break
        app.step(0.1, [])
    tick(app, BURST_AFTER + 0.1)
    fut = app.analyzer.futures[-1]
    fut.set_result(make_result(app.frame, reason="best", n=len(app.analyzer.calls[-1][0]) or 1))
    app.step(0.1, [])


# ---- 1 진단 로그 ----
def test_file_log_rotates_and_failure_does_not_stop_app(tmp_path):
    logs = tmp_path / "logs"
    old = logs / f"booth-{(date.today() - timedelta(days=20)).isoformat()}.log"
    logs.mkdir()
    old.write_text("옛 기록\n", encoding="utf-8")
    h = fieldlog.setup_file_log(logs, max_bytes=300)
    try:
        assert h is not None
        assert not old.exists()  # 14일 넘은 파일은 지운다
        lg = logging.getLogger("walnut.test_fieldlog")
        lg.setLevel(logging.INFO)
        for i in range(40):
            lg.info("흐름 기록 %03d — 회전 확인용 긴 문장입니다", i)
        today = date.today().isoformat()
        files = sorted(p.name for p in logs.iterdir())
        assert f"booth-{today}.log" in files
        assert any(n.startswith(f"booth-{today}.") and n != f"booth-{today}.log" for n in files)  # 크기로 회전
        assert all((logs / n).stat().st_size <= 300 + 200 for n in files)
    finally:
        fieldlog.remove_file_log(h)

    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    assert fieldlog.setup_file_log(blocker / "logs") is None  # 만들 수 없어도 예외 없이 None


def _file_handlers() -> list:
    return [h for h in logging.getLogger().handlers if isinstance(h, fieldlog.DailyFileHandler)]


def test_file_log_setup_twice_keeps_one_handler(tmp_path):
    a = fieldlog.setup_file_log(tmp_path / "a")
    b = fieldlog.setup_file_log(tmp_path / "b")
    try:
        assert _file_handlers() == [b] and a is not b
        logging.getLogger("walnut.test_fieldlog").warning("한 번만 쓰여야 하는 줄")
        text = next((tmp_path / "b").glob("booth-*.log")).read_text(encoding="utf-8")
        assert text.count("한 번만 쓰여야 하는 줄") == 1
        assert "한 번만" not in next((tmp_path / "a").glob("booth-*.log")).read_text(encoding="utf-8")
    finally:
        fieldlog.remove_file_log(b)
    assert _file_handlers() == []


def test_app_file_log_stays_in_its_data_dir_and_is_removed(make_app, tmp_path):
    """시험(임시 data 폴더)이 실제 booth/data · data-dev 로그에 쓰면 안 된다."""
    app = make_app()
    hs = _file_handlers()
    assert len(hs) == 1 and hs[0].dir == tmp_path / "data" / "logs"
    app.shutdown()
    assert _file_handlers() == []


def _daily_log_text(tmp_path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "data" / "logs").glob("booth-*.log"))


def test_crash_in_run_reaches_daily_log(make_app, tmp_path, monkeypatch):
    """장면 밖(_safe 밖)에서 터진 오류도 shutdown 이 로그를 떼기 전에 일별 로그에 남는다."""
    app = make_app()

    def boom(dt, events):
        raise RuntimeError("치명 오류 시험 xyz")

    monkeypatch.setattr(app, "step", boom)
    with pytest.raises(RuntimeError):
        app.run(max_frames=3)
    text = _daily_log_text(tmp_path)
    assert "부스가 예상 밖 오류로 멈췄습니다" in text and "Traceback" in text and "치명 오류 시험 xyz" in text
    assert _file_handlers() == []


def test_crash_in_init_reaches_daily_log(make_app, tmp_path, monkeypatch):
    from walnut import app as app_mod

    def boom(self):
        raise RuntimeError("시작 오류 시험 xyz")

    monkeypatch.setattr(app_mod.App, "home", boom)
    with pytest.raises(RuntimeError):
        make_app()
    text = _daily_log_text(tmp_path)
    assert "부스를 시작하지 못했습니다" in text and "시작 오류 시험 xyz" in text
    assert _file_handlers() == []


def test_main_does_not_attach_file_log(monkeypatch):
    """main.main 은 진단 로그를 붙이지 않는다 — App 이 자기 data 폴더로 붙인다 (App 을 바꿔 낀 시험이 실제 폴더에 쓰지 않게)."""
    import main
    from walnut.app import App

    monkeypatch.setattr(App, "__init__", lambda self, cfg, **k: None)
    monkeypatch.setattr(App, "run", lambda self, max_frames=None: None)
    main.main(["--no-camera"])
    assert _file_handlers() == []


# ---- 2 촬영 기록 ----
def test_metric_lines_never_contain_image_data_or_token(app, tmp_path):
    a, scene = app(LOG_ON)
    for _ in range(scene.shoot.session.total_shots()):
        take_burst_cut(a, scene)
    from walnut.scenes.review import ReviewScene
    from walnut.scenes.share import ShareScene

    assert isinstance(a.scene, ReviewScene)
    a.scene.skip()  # QR 받기
    assert isinstance(a.scene, ShareScene)
    token = a.scene.token
    collage = next((tmp_path / "data" / "collage").glob("*.jpg"))
    text = a.capture_log.path.read_text(encoding="utf-8")
    assert token not in text and collage.name not in text and collage.stem not in text
    recs = records(a)
    types = [r["type"] for r in recs]
    assert types[0] == "session" and "cut" in types and types[-1] == "result"
    sid = recs[0]["shoot_id"]
    assert sid and all(r["shoot_id"] == sid for r in recs)
    assert token not in sid and len(sid) >= 8

    def flat(v):
        if isinstance(v, dict):
            for x in v.values():
                yield from flat(x)
        elif isinstance(v, list):
            assert len(v) <= 64  # 픽셀 배열 같은 큰 목록이 없다
            for x in v:
                yield from flat(x)
        else:
            yield v

    for r in recs:
        for v in flat(r):
            assert v is None or isinstance(v, (str, int, float, bool))
            assert not (isinstance(v, str) and len(v) > 200)
    res = recs[-1]
    assert res["collage_sha256"] == hashlib.sha256(collage.read_bytes()).hexdigest()
    assert {"retakes", "compose_ms"} <= res.keys()
    cut = next(r for r in recs if r["type"] == "cut")
    assert {"cut", "index", "cands", "faces", "preview_fps", "collect_ms", "analyze_ms", "reason",
            "fallback_used"} <= cut.keys()
    session = recs[0]
    assert {"app_version", "flags", "consts", "camera", "camera_fps", "event_id", "frame_id", "slots"} <= session.keys()


# ---- 3 샘플 ----
def test_samples_need_both_flag_and_consent():
    on = lambda env: fieldlog.samples_requested(config.load(env, root=Path(".")))  # noqa: E731
    assert not on({})
    assert not on({"BOOTH_FIELD_SAMPLES": "1"})
    assert not on({"BOOTH_FIELD_SAMPLES": "1", "BOOTH_FIELD_CONSENT": "   "})
    assert not on({"BOOTH_FIELD_CONSENT": "지인테스트"})
    assert on(SAMPLES_ON)


def test_samples_off_writes_no_frames(app, tmp_path):
    a, scene = app({**LOG_ON, "BOOTH_FIELD_SAMPLES": "1"})  # 동의 이름 없음
    assert a.samples is None
    take_burst_cut(a, scene)
    assert not (tmp_path / "eval_data").exists()
    assert not list(tmp_path.rglob("*.jpg"))
    cut = next(r for r in records(a) if r["type"] == "cut")
    assert "sample" not in cut


def test_samples_on_saves_burst_sequence(app, tmp_path):
    a, scene = app({**LOG_ON, **SAMPLES_ON})
    assert a.samples is not None
    take_burst_cut(a, scene)
    a.samples.flush(5)
    dirs = list((tmp_path / "eval_data").glob("field_*_지인테스트/*/meta.json"))
    assert len(dirs) == 1
    cut = next(r for r in records(a) if r["type"] == "cut")
    assert cut["sample"] == "queued"
    assert a.samples.saved == 1


def test_sample_sequence_loads_with_load_sequence(tmp_path):
    w = fieldlog.SampleWriter(tmp_path, "홍 길동/../x")
    try:
        assert w.save(frames(3), 10.15, {"shoot_id": "abc123", "cut": 0}) == "queued"
        w.flush(5)
    finally:
        w.close()
    (folder,) = list(tmp_path.iterdir())
    assert folder.name.startswith(f"field_{date.today():%Y%m%d}_") and ".." not in folder.name
    (seq,) = [d for d in folder.iterdir() if d.is_dir()]
    got, shutter_t, meta = load_sequence(seq)
    assert len(got) == 3 and shutter_t == 10.15 and got[0].rgb.shape == (24, 32, 3)
    assert meta["shoot_id"] == "abc123" and meta["subject"] == "홍 길동/../x"


def test_sample_queue_full_drops_without_blocking(tmp_path):
    gate = threading.Event()
    w = fieldlog.SampleWriter(tmp_path, "t", queue_size=1)
    real = w._write

    def slow(*a):
        gate.wait(5)
        real(*a)

    w._write = slow
    try:
        statuses = [w.save(frames(1), 1.0, {"cut": i}) for i in range(5)]
        assert statuses.count("dropped") >= 3  # 작업 스레드가 막혀 있어도 save 는 바로 돌아온다
        assert w.dropped == statuses.count("dropped")
    finally:
        gate.set()
        w.flush(5)
        w.close()


def test_sample_stops_at_max_bytes(tmp_path):
    w = fieldlog.SampleWriter(tmp_path, "t", max_bytes=10)
    try:
        assert w.save(frames(2), 1.0, {"cut": 0}) == "queued"
        w.flush(5)
        assert w.full
        assert w.save(frames(2), 2.0, {"cut": 1}) == "full"
        w.flush(5)
    finally:
        w.close()
    (folder,) = list(tmp_path.iterdir())
    assert len([d for d in folder.iterdir() if d.is_dir()]) == 1


def test_idle_shows_notice_only_when_samples_on(make_app, paired_with_bundle, monkeypatch):
    from walnut import ui
    from walnut.scenes.idle import IdleScene

    drawn: list[str] = []
    orig = ui.text
    monkeypatch.setattr(ui, "text", lambda surf, s, *a, **k: (drawn.append(s), orig(surf, s, *a, **k))[1])
    for env, want in (({}, False), ({"BOOTH_FIELD_SAMPLES": "1"}, False), (SAMPLES_ON, True)):
        drawn.clear()
        a = make_app(env)
        a.step(1 / 60, [])
        assert isinstance(a.scene, IdleScene)
        assert (fieldlog.SAMPLE_NOTE in drawn) is want
        if want:  # 관리자 패널 상태에 저장 장수
            from walnut.scenes.admin import AdminPanel

            lines = AdminPanel(a)._status_lines()
            assert any("분석용 샘플" in x and "0" in x for x in lines)


def test_f9_records_mark_and_keeps_scene(app):
    a, scene = app(LOG_ON)
    take_burst_cut(a, scene)
    before = a.scene
    a.step(0.1, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F9, mod=0, unicode="")])
    assert a.scene is before and a.admin is None
    mark = records(a)[-1]
    assert mark["type"] == "mark" and mark["shoot_id"] == records(a)[0]["shoot_id"]
    assert "at" in mark and "memo" in mark
    assert a.notice_text() == fieldlog.MARK_NOTICE


# ---- 내보내기 ----
TOKEN = "AbC_dEf-123456_Z"  # 16자 (new_token 모양)


def make_field_data(tmp_path: Path) -> tuple[Path, Path, Path]:
    data, ev = tmp_path / "data", tmp_path / "eval_data"
    (data / "logs").mkdir(parents=True)
    (data / "collage").mkdir()
    collage = data / "collage" / f"1_1116-120000_{TOKEN}.jpg"
    Image.new("RGB", (20, 30), (1, 2, 3)).save(collage, "JPEG")
    sha = hashlib.sha256(collage.read_bytes()).hexdigest()
    now = datetime.now().isoformat(timespec="seconds")
    lines = [
        {"type": "session", "shoot_id": "s1", "at": now},
        {"type": "cut", "shoot_id": "s1", "at": now, "reason": "best", "fallback_used": False},
        {"type": "result", "shoot_id": "s1", "at": now, "collage_sha256": sha, "compose_ms": 100.0},
        {"type": "cut", "shoot_id": "s0", "at": "2026-01-01T10:00:00", "reason": "best", "fallback_used": False},
    ]
    (data / "logs" / "capture_metrics.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines), encoding="utf-8")
    (data / "logs" / f"booth-{date.today().isoformat()}.log").write_text(
        f"INFO 합성본 저장: {collage.name}\nWARNING {TOKEN}.jpg 거절됨\n", encoding="utf-8")
    seq = ev / f"field_{date.today():%Y%m%d}_t" / "s1_c0"
    seq.mkdir(parents=True)
    (seq / "000.jpg").write_bytes(b"jpg")
    (seq / "meta.json").write_text("{}", encoding="utf-8")
    return data, ev, collage


def test_export_excludes_photos_by_default(tmp_path):
    from tools import export_field_log as ex

    data, ev, _ = make_field_data(tmp_path)
    out = tmp_path / "out.zip"
    ex.export(data, ev, date.today(), out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        metrics = z.read("logs/capture_metrics.jsonl").decode("utf-8")
    assert not [n for n in names if n.lower().endswith(".jpg")]
    assert "s1" in metrics and "s0" not in metrics  # --since 이전 줄은 빠진다
    assert f"logs/booth-{date.today().isoformat()}.log" in names


def test_export_collage_names_drop_token(tmp_path):
    from tools import export_field_log as ex

    data, ev, _ = make_field_data(tmp_path)
    out = tmp_path / "out.zip"
    ex.export(data, ev, date.today(), out, with_samples=True, with_collage=True)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        blob = b"".join(z.read(n) for n in names if not n.endswith(".jpg"))
    assert "collage/s1.jpg" in names
    assert any(n.startswith("samples/field_") and n.endswith("000.jpg") for n in names)
    assert not [n for n in names if TOKEN in n]
    assert TOKEN.encode() not in blob  # 진단 로그 속 파일 이름도 가린다


# ---- 분석 ----
def test_analyze_reports_fallback_rate_and_p95(tmp_path):
    from tools import analyze_field_log as an

    recs = [{"type": "baseline", "compose_ms": 300.0, "cuts": 4}]  # 이전 형식 — 합성 지연으로 바꿔 센다
    for i in range(20):
        sid = f"s{i // 4}"
        recs.append({"type": "cut", "shoot_id": sid, "reason": "timeout" if i < 2 else "best",
                     "fallback_used": i < 2, "collect_ms": 300.0, "analyze_ms": float(i + 1), "total_ms": 301.0 + i})
    for k in range(5):
        recs.append({"type": "result", "shoot_id": f"s{k}", "compose_ms": 100.0 + k, "retakes": 0})
    recs.append({"type": "mark", "shoot_id": "s3", "at": "2026-11-16T12:00:00", "memo": "", "scene": "ReviewScene"})
    p = tmp_path / "logs"
    p.mkdir()
    (p / "capture_metrics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    s = an.summarize(an.load_records(tmp_path)[0])
    assert s["shoots"] == 5
    assert s["cuts"] == 20 and s["fallback_rate"] == pytest.approx(0.1)
    assert s["reasons"] == {"best": 18, "timeout": 2}
    assert s["latency"]["analyze_ms"]["p95"] == 19.0  # 가까운 순위 방식
    assert s["latency"]["analyze_ms"]["mean"] == pytest.approx(10.5)
    assert s["latency"]["compose_ms"]["n"] == 6 and s["latency"]["compose_ms"]["p95"] == 300.0
    assert s["legacy_baseline"] == 1
    assert [m["shoot_id"] for m in s["marks"]] == ["s3"]
    text = an.format_report(s)
    assert "폴백률" in text and "10.0%" in text and "s3" in text


def test_broken_log_line_is_skipped(tmp_path):
    from tools import analyze_field_log as an

    path = tmp_path / "capture_metrics.jsonl"
    good = json.dumps({"type": "cut", "shoot_id": "a", "reason": "best", "fallback_used": False})
    path.write_text(good + "\n" + "[1, 2]\n" + good + "\n" + '{"type": "cut", "shoot_id": "b", "rea',
                    encoding="utf-8")  # 전원 차단으로 잘린 마지막 줄
    recs, broken = an.load_records(path)
    assert len(recs) == 2 and broken == 2
    s = an.summarize(recs)
    assert s["cuts"] == 2 and s["shoots"] == 1
    assert "건너뛴 줄 2" in an.format_report({**s, "broken": broken})


def test_cut_details_records_borrowed_faces_and_unstable_count():
    from walnut.fieldlog import cut_details
    info = {"index": 1, "scores": [None, None], "rejects": [None, None], "faces_from": 0, "unstable_faces": 3, "faces_unstable": [],
            "candidates": [{"t": 0.0, "sharpness": 1.0, "faces": 1}, {"t": 0.1, "sharpness": 1.0, "faces": 0}]}
    out = cut_details(info, 0.1, [])
    assert out["faces_from"] == 0 and out["unstable_faces"] == 3 and out["faces_unstable"] == []
    empty = cut_details(None, 0.1, None)   # 시간 초과 · 오류로 결과가 없음
    assert empty["faces_from"] is None and empty["unstable_faces"] is None and empty["faces_unstable"] is None
