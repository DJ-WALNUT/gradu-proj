"""촬영 흐름 상태 (화면과 무관). 장면은 이 객체만 바꾸고 읽는다."""

from __future__ import annotations

from PIL import Image

from .settings import cut_count, cut_ratios, preview_ratio


class ShootSession:
    def __init__(self, frame: dict, capture: dict):
        self.frame = frame
        self.capture = capture
        self.filter: str = "original"
        self.sticker: str | None = None
        self.n: int = cut_count(frame["slots"])
        self.extra: int = int(capture.get("extra_shots", 0))
        self.shots: list[Image.Image] = []
        self.shot_faces: list[list | None] = []  # shots 와 같은 자리의 얼굴 관측 (없으면 None)
        self.retake_queue: list[int] = []
        self._picks: list[int] = []  # 고른 사진 번호, 고른 순서대로

    # ---- 촬영 ----
    def total_shots(self) -> int:
        """처음 촬영 장수."""
        return self.n + self.extra

    def next_cut(self) -> int:
        """다음 add_shot 이 채울 컷 번호 (재촬영 중이면 큐 앞, extra 모드는 사진 번호)."""
        return self.retake_queue[0] if self.retake_queue else len(self.shots)

    def ratio_for_shot(self, i: int) -> float:
        """extra 모드면 미리보기 비율, 아니면 컷 i 의 비율."""
        slots = self.frame["slots"]
        if self.extra > 0:
            return preview_ratio(slots)
        return cut_ratios(slots)[i]

    def add_shot(self, img: Image.Image, faces: list | None = None) -> None:
        """컷 하나를 넣는다. faces 는 shots 와 같은 자리에 둔다 (재촬영이면 같은 자리를 바꾼다)."""
        if self.retake_queue:
            i = self.retake_queue.pop(0)
            self.shots[i] = img
            self.shot_faces[i] = faces
        else:
            self.shots.append(img)
            self.shot_faces.append(faces)

    def capturing_done(self) -> bool:
        if self.retake_queue:
            return False
        return len(self.shots) >= self.total_shots()

    # ---- 고르기 (extra 모드) ----
    def toggle_pick(self, i: int) -> None:
        if not 0 <= i < len(self.shots):
            return
        if i in self._picks:
            self._picks.remove(i)
        elif len(self._picks) < self.n:
            self._picks.append(i)

    def pick_order(self) -> list[int | None]:
        return [self._picks.index(i) if i in self._picks else None for i in range(len(self.shots))]

    def picks_complete(self) -> bool:
        return len(self._picks) == self.n

    # ---- 재촬영 (extra == 0) ----
    def can_retake(self) -> bool:
        return self.extra == 0 and bool(self.capture.get("allow_retake", True))

    def begin_retake(self, keep: list[bool]) -> None:
        """keep 이 False 인 컷만 다시 찍는다."""
        if not self.can_retake():
            raise ValueError("재촬영할 수 없는 설정")
        if len(keep) != self.n:
            raise ValueError("keep 길이가 컷 수와 다름")
        self.retake_queue = [k for k, kept in enumerate(keep) if not kept]

    # ---- 결과 ----
    def cuts(self) -> list[Image.Image]:
        """컷 번호 순 n 장."""
        if self.extra > 0:
            if not self.picks_complete():
                raise ValueError("사진을 모두 고르지 않음")
            return [self.shots[i] for i in self._picks]
        return list(self.shots)
