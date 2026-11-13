"""리모컨 OLED 화면 둘러보기 — 부스를 띄우지 않고 새 프로토콜(스펙 7.1)의 줄을 리모컨에 차례로 보낸다.

    python tools/remote_demo.py            # 자동으로 찾은 리모컨에
    python tools/remote_demo.py COM5       # 포트 지정

장면마다 Enter 를 누르면 다음 장면으로 넘어간다 (q + Enter 로 끝). 부스가 켜져 있으면 포트를
부스가 쥐고 있으므로 먼저 끈다. 끝나면 리모컨은 3초 뒤 '부스 연결 대기' 로 돌아간다.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from walnut.remote import Remote, fmt_line  # noqa: E402

TITLE = "가을 축제 포토부스"


def scenes() -> list[tuple[str, list[str]]]:
    """(설명, 보낼 줄 목록). 줄이 여럿이면 Enter 없이 차례로 흘려 보낸다 (카운트다운 등)."""
    out: list[tuple[str, list[str]]] = [
        ("페어링 안 됨 / 행사 준비 중", [fmt_line("W")]),
        ("PIN 입력 (1자리째)", [fmt_line("N", 1, 6)]),
        ("PIN 입력 (4자리째)", [fmt_line("N", 4, 6)]),
        ("대기 화면", [fmt_line("I", TITLE)]),
    ]
    for kind, names in (("F", ["원본", "흑백", "밝게", "따뜻하게", "차갑게", "빈티지"]),
                        ("K", ["없음", "토끼 귀", "왕관"]),
                        ("R", ["기본 4컷", "세로 2컷", "가을 프레임"])):
        for i, name in enumerate(names):
            out.append((f"목록 {kind} {i + 1}/{len(names)}", [fmt_line("L", kind, i, len(names), name)]))
    for shot in range(4):
        out.append((f"촬영 {shot + 1}/4 카운트다운",
                    [fmt_line("C", shot, 4, t, 100) for t in range(100, -1, -5)]))
        if shot < 3:
            out.append(("다음 포즈 준비", [fmt_line("C", shot + 1, 4, -1, 100)]))
    out.append(("더 찍고 고르기 (2장 골랐음)", [fmt_line("G", "2,0,-,-,1,-", 2, 4)]))
    out.append(("더 찍고 고르기 (다 골랐음)", [fmt_line("G", "2,0,3,-,1,-", 3, 4)]))
    for sel in (0, 1):
        out.append((f"완성 확인 (선택 {sel})", [fmt_line("V", sel, 25 - sel, 25, 2)]))
    out.append(("완성 확인 — 버튼 1개 (QR 받기만)", [fmt_line("V", 0, 20, 25, 1)]))
    for keep, cur, row, btn in [("1111", 0, 0, 0), ("1011", 1, 0, 0), ("1010", 3, 0, 0),
                                ("1010", 3, 1, 0), ("1010", 3, 1, 1)]:
        out.append((f"다시 찍을 컷 {keep} 커서 {cur} 줄 {row} 버튼 {btn}",
                    [fmt_line("P", keep, cur, row, btn)]))
    for up, label in ((0, "업로드 중"), (1, "업로드 완료"), (2, "재시도"), (3, "서버 없음")):
        out.append((f"공유 — {label}", [fmt_line("S", 45 - up * 3, 45, up)]))
    out.append(("인쇄 매수", [fmt_line("Q", 2, 4)]))
    out.append(("그 밖의 장면", [fmt_line("-")]))
    out += edge_cases()
    return out


def edge_cases() -> list[tuple[str, list[str]]]:
    """경계 사례 — 큰 행사 · 긴 이름 · 범위 밖 값 · 버전 불일치에도 화면이 깨지지 않는지."""
    picked = ",".join([str(i) for i in range(12)] + ["-"] * 6)
    return [
        ("긴 제목 (흐르는지)", [fmt_line("I", "가나다라마바사아자차카타파하 가을 축제 포토부스")]),
        ("긴 프레임 이름 (흐르는지)", [fmt_line("L", "R", 0, 3, "아주아주 긴 프레임 이름 세로 두 컷 가을 한정판")]),
        ("필터 12개 중 10번째 (점 대신 숫자)", [fmt_line("L", "F", 9, 12, "열 번째")]),
        ("18장 촬영 중 8번째", [fmt_line("C", 7, 18, 55, 100)]),
        ("18장 고르기 — 12장 다 골라 [완료]", [fmt_line("G", picked, 18, 12)]),
        ("18장 고르기 — 커서가 사진 위", [fmt_line("G", "1,-,0," + ",".join(["-"] * 15), 4, 12)]),
        ("12컷 재촬영 — 컷 줄", [fmt_line("P", "101101110111", 5, 0, 0)]),
        ("12컷 재촬영 — 취소 버튼", [fmt_line("P", "101101110111", 5, 1, 1)]),
        ("범위 밖 숫자 C|0|99|-7|0", [fmt_line("C", 0, 99, -7, 0)]),
        ("숫자 아닌 필드 G|x,y|99|0", [fmt_line("G", "x,y", 99, 0)]),
        ("모르는 종류 Z (그 밖의 장면)", ["Z|아무거나"]),
        ("구분자만 |||", ["|||"]),
        ("버전 불일치 H|2 → '부스 업데이트 필요'", [fmt_line("H", 2, TITLE)]),
        ("대기 화면 — 10초 안에 H|1 이 오면 풀린다", [fmt_line("I", TITLE)]),
    ]


def main() -> None:
    remote = Remote(sys.argv[1] if len(sys.argv) > 1 else "")
    remote.set_title(TITLE)
    time.sleep(1.5)  # 포트 찾기
    print("연결됨" if remote.connected else "리모컨을 못 찾았습니다 (계속 찾는 중)")
    try:
        for desc, lines in scenes():
            for line in lines:
                remote.set(line)
                if len(lines) > 1:
                    time.sleep(0.2)
            print(f"{desc}  →  {lines[-1]}")
            if input("  Enter = 다음, q = 끝 > ").strip().lower() == "q":
                break
    finally:
        remote.stop()


if __name__ == "__main__":
    main()
