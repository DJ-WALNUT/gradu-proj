"""평가용 시퀀스 녹화 도구 — 저장 · 읽기 · 인자 거부 · 피험자 삭제."""

from __future__ import annotations

import json

import numpy as np
import pytest

from tools import record_burst as rb
from walnut.burst import TimedFrame


def _frames(n=4):
    return [TimedFrame(10.0 + 0.1 * i, np.full((24, 32, 3), 40 * i + 10, np.uint8)) for i in range(n)]


def test_sequence_round_trip_keeps_order_and_times(tmp_path):
    frames = _frames()
    d = tmp_path / "seq"
    rb.save_sequence(d, frames, 10.2, {"subject": "홍길동", "conditions": ["움직임"], "camera": [32, 24], "fps": 30.0})
    loaded, shutter_t, meta = rb.load_sequence(d)
    assert shutter_t == 10.2
    assert [f.t for f in loaded] == [f.t for f in frames]
    assert meta["subject"] == "홍길동" and meta["conditions"] == ["움직임"]
    assert [x["file"] for x in meta["frames"]] == ["000.jpg", "001.jpg", "002.jpg", "003.jpg"]
    for a, b in zip(frames, loaded):
        assert b.rgb.shape == a.rgb.shape and b.rgb.dtype == np.uint8
        assert abs(int(b.rgb.mean()) - int(a.rgb.mean())) <= 2  # JPEG 손실만큼만 다르다


def test_save_does_not_modify_frames(tmp_path):
    frames = _frames(2)
    before = [f.rgb.copy() for f in frames]
    rb.save_sequence(tmp_path / "s", frames, 10.1, {})
    assert all(np.array_equal(a.rgb, b) for a, b in zip(frames, before))


def test_sequence_dir_name_cannot_escape_root(tmp_path):
    d = rb.sequence_dir(tmp_path, "../..\\evil/x", "20261107-101500")
    assert d.parent == tmp_path
    assert "/" not in d.name and "\\" not in d.name and ".." not in d.name


def test_refuses_without_subject_consent_flag(monkeypatch, capsys):
    monkeypatch.setattr(rb, "record", lambda *a, **k: pytest.fail("카메라를 열면 안 된다"))
    for argv in ([], ["--subject", "a"], ["--consent"]):
        with pytest.raises(SystemExit) as e:
            rb.main(argv)
        assert e.value.code != 0


def test_delete_removes_only_that_subject(tmp_path):
    def mk(name, subject):
        d = tmp_path / name
        rb.save_sequence(d, _frames(1), 10.0, {"subject": subject})
    mk("a1", "민수")
    mk("a2", "민수")
    mk("b1", "민수2")
    mk("c1", "영희")
    (tmp_path / "nometa").mkdir()
    (tmp_path / "nometa" / "000.jpg").write_bytes(b"x")
    (tmp_path / "badmeta").mkdir()
    (tmp_path / "badmeta" / "meta.json").write_text("{깨짐", encoding="utf-8")
    assert rb.delete_subject(tmp_path, "민수") == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["b1", "badmeta", "c1", "nometa"]
    assert json.loads((tmp_path / "c1" / "meta.json").read_text(encoding="utf-8"))["subject"] == "영희"


def test_delete_subject_needs_no_other_flags(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rb, "EVAL_ROOT", tmp_path)
    rb.save_sequence(tmp_path / "a", _frames(1), 10.0, {"subject": "민수"})
    assert rb.main(["--delete-subject", "민수"]) == 0
    assert "1" in capsys.readouterr().out
    assert not (tmp_path / "a").exists()
