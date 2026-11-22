"""4조건 비교 평가 도구 — 가짜 분석기(얼굴 위치를 정해 준다)와 Pillow 로 만든 작은 시퀀스 · 프레임으로 시험한다.

실제 얼굴 사진은 쓰지 않는다.
"""

from __future__ import annotations

import csv
from concurrent.futures import Future

import numpy as np
import pytest
from PIL import Image

from tools import eval_capture as ec
from tools import record_burst as rb
from walnut.burst import TimedFrame
from walnut.compose import cover_crop
from walnut.framing import home_crop
from walnut.quality import FaceObs

PW, PH = 320, 180          # 카메라 (16:9)
SHUTTER = 1                # 셔터에 가장 가까운 프레임 번호
RIGHT = (0.70, 0.35, 0.80, 0.55)   # 오른쪽에 몰린 얼굴 (가운데 크롭 밖으로 걸친다)


class FakeAnalyzer:
    """detect_frames 만 흉내 낸다. 프레임 순서대로 정해 둔 얼굴을 돌려준다."""

    def __init__(self, per_frame, ms=10.0, fail=False):
        self.per_frame = per_frame   # [[FaceObs, ...], ...] — 프레임 번호 순
        self.ms = ms
        self.fail = fail
        self.modes = []

    def detect_frames(self, frames, mode=None):
        self.modes.append(mode)
        fut = Future()
        if self.fail:
            fut.set_exception(RuntimeError("가짜 분석 실패"))
        else:
            fut.set_result([(list(self.per_frame[i]), self.ms) for i in range(len(frames))])
        return fut


def face(box, eye=0.95):
    return FaceObs(tuple(box), eye, 1.0)


def frames3(n=3):
    # 같은 무늬라 선명도가 모두 같다 — 고르기는 눈 뜸으로만 갈린다
    rng = np.random.default_rng(0)
    base = rng.integers(0, 255, (PH, PW, 3), dtype=np.uint8)
    return [TimedFrame(10.0 + 0.1 * i, base.copy()) for i in range(n)]


def per_frame_right():
    """셔터 프레임(1)은 눈 감음, 프레임 2 는 눈 뜸 — 버스트는 2 를 고른다."""
    return [[face(RIGHT, 0.2)], [face(RIGHT, 0.3)], [face(RIGHT, 0.95)]]


def make_frame(n_slots=2):
    """투명 구멍이 n_slots 개인 RGBA 프레임과 그 슬롯."""
    img = Image.new("RGBA", (200, 300), (250, 240, 220, 255))
    holes = [(10, 10, 90, 116), (110, 10, 190, 116), (10, 150, 90, 256), (110, 150, 190, 256)][:n_slots]
    px = img.load()
    for x0, y0, x1, y1 in holes:
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = (0, 0, 0, 0)
    from walnut.default_bundle import detect_slots
    return img, detect_slots(img)


def seq(n=3):
    fr = frames3(n)
    return fr, fr[SHUTTER].t


def write_seq(root, name, n=3):
    fr = frames3(n)
    rb.save_sequence(root / name, fr, fr[SHUTTER].t, {"subject": "x", "conditions": []})


def read_csv(path):
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    return list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))


# ---- 조건 ----

def test_four_conditions_run_on_same_sequence(tmp_path):
    frame, slots = make_frame(2)
    an = FakeAnalyzer(per_frame_right())
    res = ec.run_conditions(seq(), frame, slots, an)
    assert list(res) == ["baseline", "A", "B", "AB"]
    assert an.modes == ["full+halves"]  # 시퀀스 하나에 한 번만 검출, 전체 + 좌우 반쪽
    for name, r in res.items():
        assert r.condition == name and not r.failed
        assert [s.slot for s in r.slots] == ["s1", "s2"]
        assert r.ms >= 0


def test_baseline_uses_frame_nearest_shutter_and_center_crop(tmp_path):
    frame, slots = make_frame(2)
    r = ec.run_conditions(seq(), frame, slots, FakeAnalyzer(per_frame_right()))["baseline"]
    assert r.frame_index == SHUTTER
    for s, slot in zip(r.slots, slots):
        assert s.crop == cover_crop(PW, PH, slot["w"], slot["h"])
        assert s.zoom == pytest.approx(1.0) and s.reason == "center"
    assert r.eye_min == pytest.approx(0.3)


def test_A_uses_selected_frame_with_center_crop(tmp_path):
    frame, slots = make_frame(2)
    r = ec.run_conditions(seq(), frame, slots, FakeAnalyzer(per_frame_right()))["A"]
    assert r.frame_index == 2  # 셔터 프레임은 눈을 감아 탈락
    assert r.eye_min == pytest.approx(0.95)
    for s, slot in zip(r.slots, slots):
        assert s.crop == cover_crop(PW, PH, slot["w"], slot["h"]) and s.reason == "center"


def test_B_and_AB_use_center_stage_crop(tmp_path):
    frame, slots = make_frame(2)
    res = ec.run_conditions(seq(), frame, slots, FakeAnalyzer(per_frame_right()), mirror=False)
    assert res["B"].frame_index == SHUTTER and res["AB"].frame_index == 2
    for name in ("B", "AB"):
        for s, slot in zip(res[name].slots, slots):
            assert s.reason == "follow"
            hx, hy, hw, hh = home_crop(PW, PH, slot["w"], slot["h"])
            assert (s.crop[2], s.crop[3]) == (hw, hh) and s.crop[0] > hx  # 같은 배율로 오른쪽으로
            assert s.zoom == pytest.approx(cover_crop(PW, PH, slot["w"], slot["h"])[2] / hw)
            assert s.metrics["all_in"] == 1
    for s in res["baseline"].slots:
        assert s.metrics["all_in"] == 0


# ---- 지표 ----

def test_all_in_and_face_cut_metrics(tmp_path):
    # 가운데 크롭 x 92~228, 얼굴 x 224~256 (폭 32) → 안쪽 4px, 잘림 28/32
    crop = (92, 0, 136, 180)
    m = ec.slot_metrics(crop, PW, PH, [face(RIGHT)], None)
    assert m["face_cut_max"] == pytest.approx(0.875)
    assert m["face_cut_mean"] == pytest.approx(0.875)
    assert m["all_in"] == 0
    assert m["face_fill"] == pytest.approx(max(32 / 136, 36 / 180))
    assert m["occluded"] is None  # 격자가 없으면 재지 않는다

    # 두 얼굴: 하나는 안, 하나는 반쯤 밖
    inside = (0.40, 0.30, 0.50, 0.50)   # x 128~160
    m2 = ec.slot_metrics(crop, PW, PH, [face(inside), face(RIGHT)], None)
    assert m2["face_cut_max"] == pytest.approx(0.875)
    assert m2["face_cut_mean"] == pytest.approx(0.875 / 2)
    assert m2["all_in"] == 0
    m3 = ec.slot_metrics(crop, PW, PH, [face(inside)], None)
    assert m3["face_cut_max"] == 0 and m3["all_in"] == 1

    # 장식 가림: 크롭 = 전체, 왼쪽 위 칸만 장식, 얼굴이 왼쪽 위 사분면 전체
    grid = np.array([[1.0, 0.0], [0.0, 0.0]])
    m4 = ec.slot_metrics((0, 0, PW, PH), PW, PH, [face((0.0, 0.0, 0.5, 0.5))], grid)
    assert m4["occluded"] == pytest.approx(1.0)

    # 얼굴이 없으면 얼굴 지표는 비운다 (측정한 것만)
    m5 = ec.slot_metrics(crop, PW, PH, [], None)
    assert m5["all_in"] is None and m5["face_cut_max"] is None and m5["face_fill"] is None


# ---- 출력 ----

def test_csv_has_sample_count_and_failures(tmp_path, monkeypatch):
    root, out = tmp_path / "data", tmp_path / "out"
    write_seq(root, "seq1")
    write_seq(root, "seq2")
    frame, slots = make_frame(2)

    def boom(*a, **k):
        raise RuntimeError("구도 계산 실패")

    monkeypatch.setattr(ec, "compute_crop", boom)
    lines = []
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out, seed=1, log=lines.append)

    rows = read_csv(out / "results.csv")
    assert list(rows[0].keys()) == ec.RESULT_HEADER
    assert len(rows) == 2 * 4 * 2   # 시퀀스 × 조건 × 슬롯
    failed = {(r["조건"], r["실패"]) for r in rows}
    assert ("B", "1") in failed and ("AB", "1") in failed and ("baseline", "0") in failed
    assert all(r["오류"] for r in rows if r["실패"] == "1")

    summary = {r["조건"]: r for r in read_csv(out / "summary.csv")}
    assert list(summary) == ["baseline", "A", "B", "AB"]
    # 표본 수 = 시퀀스 수 (슬롯 2개는 같은 컷이라 세지 않는다)
    assert summary["baseline"]["표본 수(시퀀스)"] == "2" and summary["baseline"]["실패 수"] == "0"
    assert summary["B"]["표본 수(시퀀스)"] == "0" and summary["B"]["실패 수"] == "2"
    assert summary["baseline"]["all_in 비율"] == "0.0000"
    assert any("baseline" in ln for ln in lines)  # 콘솔 표
    assert ec.CAVEAT in lines  # 자기 채점 주의가 요약 바로 아래


def test_blind_sheet_hides_condition_names(tmp_path):
    root, out = tmp_path / "data", tmp_path / "out"
    write_seq(root, "seq1")
    frame, slots = make_frame(2)
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out, seed=3, log=lambda s: None)
    files = sorted(p.relative_to(out / "blind").as_posix() for p in (out / "blind").rglob("*") if p.is_file())
    assert files == ["seq1.jpg"]
    sheet = Image.open(out / "blind" / "seq1.jpg")
    assert sheet.width > 4 * 100  # 네 장이 가로로 이어 붙었다
    key = read_csv(out / "blind_key.csv")
    assert [r["번호"] for r in key] == ["1", "2", "3", "4"]
    assert sorted(r["조건"] for r in key) == sorted(ec.CONDITIONS)
    assert {r["시퀀스"] for r in key} == {"seq1"}


def test_blind_order_is_reproducible_with_seed(tmp_path):
    root = tmp_path / "data"
    for i in range(6):
        write_seq(root, f"seq{i}")
    frame, slots = make_frame(1)

    def order(out, seed):
        ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out, seed=seed, log=lambda s: None)
        return [(r["시퀀스"], r["번호"], r["조건"]) for r in read_csv(out / "blind_key.csv")]

    a = order(tmp_path / "o1", 7)
    b = order(tmp_path / "o2", 7)
    c = order(tmp_path / "o3", 8)
    assert a == b
    assert a != c  # 시퀀스 6개 × 4! 가지라 우연히 같을 일은 거의 없다


def test_existing_blind_key_is_kept_so_labels_stay_valid(tmp_path):
    root, out = tmp_path / "data", tmp_path / "out"
    write_seq(root, "seq1")
    frame, slots = make_frame(1)
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out, seed=1, log=lambda s: None)
    first = read_csv(out / "blind_key.csv")
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out, seed=99, log=lambda s: None)
    assert read_csv(out / "blind_key.csv") == first
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out, seed=99, reshuffle=True,
           log=lambda s: None)
    assert len(read_csv(out / "blind_key.csv")) == 4


def test_labels_merged_by_sequence_id(tmp_path):
    root, out = tmp_path / "data", tmp_path / "out"
    write_seq(root, "seq1")
    write_seq(root / "field_20261120_test", "shootA_c0")
    frame, slots = make_frame(1)
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out, seed=5, log=lambda s: None)
    key = read_csv(out / "blind_key.csv")
    assert {r["시퀀스"] for r in key} == {"seq1", "field_20261120_test/shootA_c0"}
    assert (out / "blind" / "field_20261120_test" / "shootA_c0.jpg").is_file()

    # 구도선호: AB 5 · B 4 · A 2 · baseline 1, 눈감음은 baseline 만 1 (흐림 · 잘림은 빈칸)
    score = {"baseline": 1, "A": 2, "B": 4, "AB": 5}
    with (root / "labels.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["시퀀스", "번호", "눈감음", "흐림", "잘림", "구도선호"])
        for r in key:
            w.writerow([r["시퀀스"], r["번호"], 1 if r["조건"] == "baseline" else 0, "", "", score[r["조건"]]])
        w.writerow(["없는시퀀스", "1", 1, 1, 1, 1])  # 답안에 없는 줄은 건너뛴다

    lines = []
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out, log=lines.append)
    summary = {r["조건"]: r for r in read_csv(out / "summary.csv")}
    for cond, v in score.items():
        assert float(summary[cond]["구도선호 평균"]) == pytest.approx(v)
        assert summary[cond]["사람 평가 수"] == "2"
        assert summary[cond]["흐림 평균"] == ""
    assert float(summary["baseline"]["눈감음 평균"]) == 1.0
    assert float(summary["AB"]["눈감음 평균"]) == 0.0
    assert any("없는시퀀스" in ln for ln in lines)


def test_debug_off_writes_no_face_images(tmp_path):
    root, out = tmp_path / "data", tmp_path / "out"
    write_seq(root, "seq1")
    frame, slots = make_frame(2)
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out, seed=1, log=lambda s: None)
    assert not (out / "debug").exists()
    assert sorted(p.name for p in out.iterdir()) == ["blind", "blind_key.csv", "results.csv", "summary.csv"]

    out2 = tmp_path / "out2"
    lines = []
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right()), out2, seed=1, debug=True, log=lines.append)
    names = sorted(p.name for p in (out2 / "debug").iterdir())
    assert names == ["seq1_AB_s1.jpg", "seq1_AB_s2.jpg", "seq1_B_s1.jpg", "seq1_B_s2.jpg"]
    assert any("얼굴" in ln and "debug" in ln for ln in lines)  # 원본 얼굴 사진 경고


def test_analysis_failure_counts_all_conditions_failed_and_continues(tmp_path):
    root, out = tmp_path / "data", tmp_path / "out"
    write_seq(root, "seq1")
    frame, slots = make_frame(1)
    ec.run(root, frame, slots, FakeAnalyzer(per_frame_right(), fail=True), out, seed=1, log=lambda s: None)
    summary = {r["조건"]: r for r in read_csv(out / "summary.csv")}
    assert all(summary[c]["실패 수"] == "1" for c in ec.CONDITIONS)


def test_find_sequences_includes_field_folders(tmp_path):
    write_seq(tmp_path, "seq1")
    write_seq(tmp_path / "field_20261120_x", "s_c0")
    (tmp_path / "_eval").mkdir()
    ids = [i for i, _ in ec.find_sequences(tmp_path)]
    assert ids == ["field_20261120_x/s_c0", "seq1"]


def test_summary_averages_slots_within_sequence_first():
    def res(values):
        r = ec.Result("baseline", 0, [ec.SlotResult(f"s{i}", (0, 0, 1, 1), "center", 1.0,
                                                    {**{k: None for k in ec.METRICS + ec.ALL_METRICS},
                                                     "face_cut_max": v}) for i, v in enumerate(values)])
        return {c: (r if c == "baseline" else ec.Result(c, -1, failed=True)) for c in ec.CONDITIONS}

    # 시퀀스 1 슬롯 [0, 빈칸] → 0, 시퀀스 2 슬롯 [1, 1] → 1. 시퀀스 평균 0.5 (슬롯을 모두 섞으면 0.667)
    s = ec.summarize([("q1", res([0.0, None])), ("q2", res([1.0, 1.0]))], {})[0]
    assert s["표본 수(시퀀스)"] == 2
    assert float(s["face_cut_max 평균"]) == pytest.approx(0.5)


def test_all_faces_columns_include_small_background_face(tmp_path):
    frame, slots = make_frame(1)
    subject = (0.40, 0.25, 0.55, 0.60)      # 가운데 큰 얼굴
    passer = (0.02, 0.40, 0.06, 0.48)       # 왼쪽 끝 작은 행인 (가장 큰 얼굴 높이의 40% 미만)
    an = FakeAnalyzer([[face(subject), face(passer)]] * 3)
    r = ec.run_conditions(seq(), frame, slots, an, mirror=False)["baseline"]
    m = r.slots[0].metrics
    assert m["all_in"] == 1 and m["face_cut_max"] == 0          # 구도 얼굴만: 다 들어옴
    assert m["all_in_all"] == 0 and m["face_cut_max_all"] == pytest.approx(1.0)  # 행인은 크롭 밖
    root, out = tmp_path / "d", tmp_path / "o"
    write_seq(root, "seq1")
    ec.run(root, frame, slots, an, out, seed=1, log=lambda s: None)
    row = read_csv(out / "results.csv")[0]
    assert row["all_in_all"] == "0" and row["face_cut_max_all"] == "1.0000"
    summary = read_csv(out / "summary.csv")[0]
    assert summary["all_in 비율"] == "1.0000" and summary["all_in_all 비율"] == "0.0000"


def test_mirror_flips_cut_and_face_boxes_like_booth(tmp_path):
    frame, slots = make_frame(1)
    an = lambda: FakeAnalyzer(per_frame_right())  # noqa: E731
    off = ec.run_conditions(seq(), frame, slots, an(), mirror=False)
    on = ec.run_conditions(seq(), frame, slots, an(), mirror=True)
    fr, _ = seq()
    assert np.array_equal(on["B"].rgb, fr[SHUTTER].rgb[:, ::-1])
    assert on["B"].faces[0].box == pytest.approx((1 - RIGHT[2], RIGHT[1], 1 - RIGHT[0], RIGHT[3]))
    # 장식이 없으면 크롭도 정확히 좌우 대칭
    x, y, cw, ch = off["B"].slots[0].crop
    assert on["B"].slots[0].crop == (PW - x - cw, y, cw, ch)
    # meta 에 mirror 가 없으면 부스 기본값(켬), meta 의 false 는 따른다
    assert ec.run_conditions(seq(), frame, slots, an())["B"].mirror is True
    fr2, t2 = seq()
    assert ec.run_conditions((fr2, t2, {"mirror": False}), frame, slots, an())["B"].mirror is False


def test_mirror_with_one_sided_decoration_matches_booth_crop(tmp_path):
    from walnut.framing import compute_crop, occlusion_grid
    from walnut.analysis import _mirror_box

    frame, slots = make_frame(1)
    # 슬롯 왼쪽 45% 에 장식 (위아래 가장자리는 투명으로 남겨 구멍 상자는 그대로)
    px = frame.load()
    for yy in range(14, 112):
        for xx in range(10, 46):
            px[xx, yy] = (200, 60, 60, 255)
    from walnut.default_bundle import detect_slots
    assert detect_slots(frame) == slots
    grid = occlusion_grid(frame, slots[0])
    sw, sh = slots[0]["w"], slots[0]["h"]

    on = ec.run_conditions(seq(), frame, slots, FakeAnalyzer(per_frame_right()), mirror=True)
    off = ec.run_conditions(seq(), frame, slots, FakeAnalyzer(per_frame_right()), mirror=False)
    mirrored = [face(_mirror_box(RIGHT))]
    c = compute_crop(PW, PH, sw, sh, mirrored, grid)
    assert on["B"].slots[0].crop == (c.x, c.y, c.w, c.h)   # 부스: 뒤집은 컷 + 뒤집은 박스로 계산
    x, y, cw, ch = off["B"].slots[0].crop
    assert on["B"].slots[0].crop != (PW - x - cw, y, cw, ch)  # 장식 때문에 단순 대칭이 아니다
    # 가운데 크롭에서 얼굴이 장식 쪽(왼쪽)으로 가면 가림이 생긴다
    assert on["baseline"].slots[0].metrics["occluded"] > off["baseline"].slots[0].metrics["occluded"]


# ---- 확인 지점 3: 부스와 같은 꾸준한 얼굴 거르기 · 이웃 얼굴 빌리기 ----

FAKE = (0.10, 0.60, 0.16, 0.75)    # 배경 물건이 5장 중 2장에서만 얼굴로 잡혔다


def per_frame_flicker():
    p = lambda eye: face(RIGHT, eye)  # noqa: E731
    return [[p(0.75), face(FAKE)], [p(0.75), face(FAKE)], [p(0.8)], [p(0.99)], [p(0.8)]]


def test_burst_conditions_drop_flickering_face_like_booth(tmp_path):
    frame, slots = make_frame(2)
    res = ec.run_conditions(seq(5), frame, slots, FakeAnalyzer(per_frame_flicker()), mirror=False)
    # 거르지 않으면 얼굴 2개인 0 · 1 번만 후보로 남는다. 부스처럼 거르면 눈을 가장 잘 뜬 3 번
    assert res["A"].frame_index == 3 and res["AB"].frame_index == 3
    assert res["AB"].unstable_faces == 2 and res["AB"].faces_from is None
    # 버스트가 없는 조건은 부스처럼 셔터 프레임 한 장만 본다 (거르지 않는다)
    assert len(res["B"].faces) == 2 and res["B"].unstable_faces == 0
    rows = ec.result_rows("s", slots, res)
    ab = [r for r in rows if r[1] == "AB"][0]
    assert ab[ec.RESULT_HEADER.index("걸러진 얼굴")] == 2 and ab[ec.RESULT_HEADER.index("얼굴 빌림")] == ""


def test_AB_borrows_neighbor_faces_when_selected_frame_has_none(tmp_path, monkeypatch):
    frame, slots = make_frame(2)
    per_frame = [[face(RIGHT)], [], [face(RIGHT)]]
    real = ec.select_best

    def pick_faceless(cands, shutter_t):
        sel = real(cands, shutter_t)
        sel.index = 1
        return sel

    monkeypatch.setattr(ec, "select_best", pick_faceless)
    res = ec.run_conditions(seq(), frame, slots, FakeAnalyzer(per_frame), mirror=False)
    ab = res["AB"]
    assert ab.frame_index == 1 and ab.faces_from == 0
    for s in ab.slots:
        assert s.reason == "follow"                        # 빌린 얼굴로 오른쪽을 따라간다
        assert s.metrics["all_in"] is None                 # 지표는 그 프레임에서 검출한 얼굴로만 (없음)
    for s in res["B"].slots:                               # 셔터 프레임(1)은 얼굴이 없어 가장 넓게
        assert s.reason == "no_face" and s.crop == cover_crop(PW, PH, slots[0]["w"], slots[0]["h"])


def test_all_conditions_scored_against_same_raw_faces(tmp_path):
    # 고른 프레임에 가짜 얼굴이 남아 있어도 (거르기는 고르기 · 크롭에만) 네 조건 모두 같은 얼굴로 채점한다
    frame, slots = make_frame(2)
    per = [[face(RIGHT, 0.95), face(FAKE)] if i == SHUTTER else [face(RIGHT, 0.8)] for i in range(5)]
    per[3] = [face(RIGHT, 0.99), face(FAKE)]   # 가짜 얼굴이 5장 중 2장 — 걸러진다
    res = ec.run_conditions(seq(5), frame, slots, FakeAnalyzer(per), mirror=False)
    assert res["AB"].unstable_faces == 2 and res["A"].frame_index == 3   # 거른 뒤 고른 프레임에 가짜 얼굴이 있다
    for name, r in res.items():
        assert [f.box for f in r.faces] == [RIGHT, FAKE], name          # 채점 얼굴 = 검출 그대로
        for s in r.slots:
            assert s.metrics["all_in_all"] == 0, name                    # 가짜 얼굴(왼쪽 끝)은 모든 조건이 똑같이 잘린 것으로
    # 구도에는 고른 프레임의 얼굴 전부(꾸준하지 않은 가짜 얼굴 포함)를 쓴다 — 같은 얼굴인 B 와 크롭이 같다
    assert [s.crop for s in res["AB"].slots] == [s.crop for s in res["B"].slots]
    rows = ec.result_rows("s", slots, res)
    counts = {r[1]: r[ec.RESULT_HEADER.index("얼굴 수")] for r in rows}
    assert set(counts.values()) == {2}


def test_AB_crop_adds_person_missed_in_chosen_frame_like_booth(tmp_path):
    # 두 번째 사람이 0 · 1 번에만 잡히고 고른 3 번에서는 놓쳤다 → 부스처럼 구도에 더한다 (채점은 3 번 검출 그대로)
    frame, slots = make_frame(2)
    other = (0.45, 0.35, 0.52, 0.55)
    per = [[face(RIGHT, 0.75), face(other)], [face(RIGHT, 0.75), face(other)], [face(RIGHT, 0.8)],
           [face(RIGHT, 0.99)], [face(RIGHT, 0.8)]]
    res = ec.run_conditions(seq(5), frame, slots, FakeAnalyzer(per), mirror=False)
    ab = res["AB"]
    assert ab.frame_index == 3 and [f.box for f in ab.faces] == [RIGHT]   # 채점 얼굴은 고른 프레임 그대로
    for s in ab.slots:
        x, y, w, h = s.crop
        for b in (RIGHT, other):
            assert x <= b[0] * PW and b[2] * PW <= x + w


# ---- 사람 찾기 (Task H): 구도 보정 조건은 부스처럼 사람 찾기 머리를 크롭에 더한다 ----

class PersonAnalyzer(FakeAnalyzer):
    """얼굴은 없고, 사람 찾기가 오른쪽에 머리 하나를 돌려준다 (BurstAnalyzer.person_heads_for 흉내)."""

    def __init__(self, per_frame, head=RIGHT):
        super().__init__(per_frame)
        self.head = head
        self.calls = []

    def person_heads_for(self, rgb, faces):
        self.calls.append(len(faces))
        fut = Future()
        fut.set_result(([face(self.head, None)] if not faces else [], 5.0))
        return fut


def test_smart_conditions_add_person_heads_like_booth(tmp_path):
    frame, slots = make_frame(2)
    an = PersonAnalyzer([[], [], []])
    res = ec.run_conditions(seq(), frame, slots, an)
    assert res["B"].person_heads == 1 and res["AB"].person_heads == 1
    assert res["baseline"].person_heads == 0 and res["A"].person_heads == 0
    for c in ("B", "AB"):
        assert all(s.reason != "no_face" for s in res[c].slots)    # 사람 위치로 크롭했다
        assert res[c].faces == []                                   # 채점은 검출한 얼굴 기준 그대로 (채점 불가)
    for c in ("baseline", "A"):
        for s, slot in zip(res[c].slots, slots):
            assert s.crop == cover_crop(PW, PH, slot["w"], slot["h"])


def test_analyzer_without_person_feature_still_works(tmp_path):
    frame, slots = make_frame(2)
    res = ec.run_conditions(seq(), frame, slots, FakeAnalyzer([[], [], []]))
    assert all(r.person_heads == 0 and not r.failed for r in res.values())


def test_person_failure_is_logged_and_crop_uses_faces(tmp_path, caplog):
    class Broken(FakeAnalyzer):
        def person_heads_for(self, rgb, faces):
            fut = Future()
            fut.set_exception(RuntimeError("사람 모델 오류"))
            return fut

    frame, slots = make_frame(2)
    res = ec.run_conditions(seq(), frame, slots, Broken(per_frame_right()))
    assert all(not r.failed and r.person_heads == 0 for r in res.values())
    assert any("사람 찾기에 실패" in m and "사람 모델 오류" in m for m in caplog.messages)


def test_person_wait_has_timeout():
    assert 0 < ec.PERSON_TIMEOUT <= 30
