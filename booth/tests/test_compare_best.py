"""베스트 컷 비교 도구 — 가짜 시퀀스와 가짜 landmarker 로 시험한다."""

from __future__ import annotations

import csv
from types import SimpleNamespace as P

import numpy as np

from facekit import fake_face, with_eyes
from tools import compare_best as cb
from tools import record_burst as rb
from walnut.analysis import BurstAnalyzer
from walnut.burst import TimedFrame


class FakeLandmarker:
    """프레임 평균 밝기를 40 으로 나눈 몫으로 프레임을 구별한다 (JPEG 손실에 안전)."""

    def __init__(self, open_ratios):
        self.open_ratios = open_ratios  # 프레임 번호 -> 눈 뜬 정도

    def detect(self, image):
        i = int(np.asarray(image.numpy_view()).mean() // 40)
        face = with_eyes(fake_face(), self.open_ratios[i], aspect=32 / 24)
        m = np.eye(4)
        return P(face_landmarks=[face], face_blendshapes=[], facial_transformation_matrixes=[m])

    def close(self):
        pass


def make_seq(root, name, conditions=("눈감음",), n=3, shutter_idx=1):
    frames = [TimedFrame(10.0 + 0.1 * i, np.full((24, 32, 3), 40 * i + 10, np.uint8)) for i in range(n)]
    rb.save_sequence(root / name, frames, frames[shutter_idx].t, {"subject": "x", "conditions": list(conditions)})


def analyzer(tmp_path, ratios=None):
    return BurstAnalyzer(tmp_path / "none.task", landmarker=FakeLandmarker(ratios or {0: 0.05, 1: 0.35, 2: 0.35}),
                         detect_mode="full")  # 가짜가 조각을 구별하지 못한다


def test_compare_sequence_reports_choice_and_rows(tmp_path):
    make_seq(tmp_path, "seqA")
    an = analyzer(tmp_path)
    try:
        r = cb.compare_sequence(an, tmp_path / "seqA")
    finally:
        an.close()
    assert r["name"] == "seqA" and r["conditions"] == ["눈감음"]
    assert r["nearest"] == "001.jpg"
    assert r["chosen"] in ("001.jpg", "002.jpg")  # 눈을 감은 000 은 제외된다
    assert len(r["rows"]) == 3 and sum(row[-1] for row in r["rows"]) == 1
    assert r["ms"] >= 0


def test_run_writes_csv_with_bom_and_one_row_per_frame(tmp_path):
    make_seq(tmp_path, "seqA")
    make_seq(tmp_path, "seqB", n=2, shutter_idx=0)
    an = analyzer(tmp_path)
    lines = []
    try:
        cb.run(tmp_path, an, out=lines.append)
    finally:
        an.close()
    raw = (tmp_path / "compare.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(raw.decode("utf-8-sig").splitlines()))
    assert rows[0] == cb.CSV_HEADER
    assert len(rows) == 1 + 3 + 2
    assert {r[0] for r in rows[1:]} == {"seqA", "seqB"}
    assert any("seqA" in ln and "reason=" in ln for ln in lines)
    assert not any("사람 라벨과 비교" in ln for ln in lines)  # 라벨 파일이 없으면 그 부분을 건너뛴다


def test_labels_are_shown_and_counted(tmp_path):
    make_seq(tmp_path, "seqA")
    make_seq(tmp_path, "seqB")
    make_seq(tmp_path, "seqC")
    an = analyzer(tmp_path)
    try:
        chosen = cb.compare_sequence(an, tmp_path / "seqA")["chosen"]
        other = "000.jpg" if chosen != "000.jpg" else "001.jpg"
        (tmp_path / "best_labels.csv").write_text(
            f"시퀀스,베스트,메모\nseqA,{chosen},\nseqB,{other},일부러 다름\nseqC,없음,전부 감김\n",
            encoding="utf-8-sig")
        lines = []
        cb.run(tmp_path, an, out=lines.append)
    finally:
        an.close()
    assert any("seqB" in ln and f"사람 {other}" in ln for ln in lines)
    summary = [ln for ln in lines if "사람 라벨과 비교" in ln]
    assert summary and "시퀀스 3개" in summary[0] and "일치 1개" in summary[0] and "횟수 2" in summary[0]


def test_summarize_ignores_unlabeled_sequences():
    results = [{"name": "a", "chosen": "000.jpg"}, {"name": "b", "chosen": "001.jpg"}]
    assert cb.summarize(results, {"a": "000.jpg"}) == {"compared": 1, "same": 1, "different": 0}


def test_missing_root_is_empty(tmp_path):
    an = analyzer(tmp_path)
    lines = []
    try:
        assert cb.run(tmp_path / "없는폴더", an, out=lines.append) == []
    finally:
        an.close()
    assert lines and not (tmp_path / "없는폴더").exists()


def test_broken_sequence_is_skipped(tmp_path):
    make_seq(tmp_path, "seqA")
    (tmp_path / "seqBad").mkdir()
    (tmp_path / "seqBad" / "meta.json").write_text("{깨짐", encoding="utf-8")
    an = analyzer(tmp_path)
    lines = []
    try:
        results = cb.run(tmp_path, an, out=lines.append)
    finally:
        an.close()
    assert [r["name"] for r in results] == ["seqA"]
    assert any("seqBad" in ln and "건너뜀" in ln for ln in lines)
