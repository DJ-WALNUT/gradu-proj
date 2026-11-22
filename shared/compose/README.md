# shared/compose/

프레임 합성 기하와 그리기. 관리자 웹(편집기 미리보기)과 웹 부스(실제 합성)가 **같은 코드**를 쓴다.
의존성 없음 · 관리자 웹 import 없음 (DOM 타입만 사용).

- `types.ts` — `Geom`, `ComposeSlot`, `PlanItem`, `ComposePhoto`, `FrameLayer`, `ComposeMode`
- `geometry.ts` — `localToWorld`, `slotCorners`, `coverCrop`, `slotAABB` (규칙은 `../compose_fixtures.json`)
- `compose.ts` — `composePlan`, `renderCompose`
- `filters.ts` — `FILTERS`, `applyFilter`, `filterParams` (Python 부스 `filters.py` 와 같은 값, 규칙은 `../filter_fixtures.json` · 생성기 `../tools/gen_filter_fixtures.py`)

## mode

- `"preview"` (기본): `shot % 컷 수`. 컷이 없으면 빈 계획 / 번호 자리표시. 편집기용.
- `"booth"`: `photos[shot]` 그대로. 컷이 없으면 `RangeError("컷 n 이 없습니다")`.

편집기 전용 도우미(`RATIOS`, `snapAngle`, `resizeLocked` 등)는 `admin/src/geometry/slots.ts` 에 남아 있다.
테스트: `admin/src/geometry/slots.test.ts`, `admin/src/editor/compose.test.ts`, `admin/src/editor/filters.test.ts` (Python 쪽: `booth/tests/test_filter_fixtures.py`).
