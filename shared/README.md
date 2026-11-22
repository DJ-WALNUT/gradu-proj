# shared/

관리자 웹(`admin/`)과 부스 앱(Python)이 **함께 쓰는** 계약 파일.

## compose_fixtures.json — 합성 기하 기대값

관리자 웹의 합성 미리보기와 부스의 실제 합성이 같은 결과를 내도록, 슬롯 꼭짓점과 사진 자르기 영역의
기대값을 담는다. **부스(Python) 테스트도 이 파일을 읽는다.** 규칙을 바꾸면 양쪽 구현과 이 파일을 함께 바꾼다.

### 형식

```jsonc
{ "version": 1,
  "cases": [
    { "name": "upright 3:4",
      "slot":  {"cx": 512, "cy": 680, "w": 812, "h": 1082, "rot": 0},   // 프레임 PNG 픽셀, rot 은 시계 방향 도(y 아래)
      "photo": {"w": 1440, "h": 1080},                                  // 촬영 사진 크기
      "corners": [[106,139],[918,139],[918,1221],[106,1221]],           // 좌상 → 우상 → 우하 → 좌하 (회전 전 기준)
      "crop": {"x": 315, "y": 0, "w": 810, "h": 1080} },                // 사진에서 잘라낼 영역(정수 픽셀)
    … ]}
```

`corners` 는 소수 6자리로 반올림해 저장한다. 비교 허용 오차 1e-6. `crop` 은 정확히 같아야 한다.

### 규칙

```
slotCorners(slot)
  local = [(-w/2,-h/2), (w/2,-h/2), (w/2,h/2), (-w/2,h/2)]
  θ = rot·π/180;  x' = cx + x·cosθ − y·sinθ;  y' = cy + x·sinθ + y·cosθ

coverCrop(pw, ph, w, h)
  ar = w / h
  if pw / ph > ar:  cw = max(1, floor(ph·ar + 0.5)); ch = ph; x = floor((pw − cw) / 2); y = 0
  else:             cw = pw; ch = max(1, floor(pw / ar + 0.5)); x = 0; y = floor((ph − ch) / 2)
```

- 반올림은 반드시 `floor(v + 0.5)` 다. Python 의 `round()` 는 은행원 반올림(540.5 → 540)이라 결과가 달라진다.
- ar = w / h 를 먼저 float 로 계산하고, ph·ar / pw / ar 순서를 바꾸지 말 것 (분수·Decimal 금지).
  예: w=350, h=1000, ph=1350 → `1350 * (350/1000)` = 472.49999999999994 → 472 (`1350*350/1000` = 472.5 → 473 은 틀림).
- crop 크기는 최소 1px (`max(1, …)`). 극단 비율(1×4000 슬롯 등)에서 0 이 되는 것을 막는다.
  분기 조건 때문에 cw ≤ pw, ch ≤ ph 이므로 x, y 는 항상 0 이상이다.

합성 순서: 흰 바탕 → 슬롯마다 crop → w×h 로 리사이즈 → 중심 기준 rot 만큼 회전 → 중심을 (cx, cy) 에 → 그 위에 프레임 PNG.

### 다시 만들기

기대값은 구현 코드가 아니라 독립 스크립트 `tools/gen_compose_fixtures.py`(표준 라이브러리만)로 계산한다.
케이스를 추가하려면 스크립트의 `CASES` 에 넣고 저장소 루트에서 실행한다.

```
server\.venv\Scripts\python.exe shared\tools\gen_compose_fixtures.py
```

관리자 웹 테스트: `admin/src/geometry/slots.test.ts` (`cd admin; npm test`).

## booth-design/ — 부스 · 사진 페이지 디자인 토큰

`tokens.json` 과 Python 로더. 자세한 내용은 [booth-design/README.md](booth-design/README.md).

## compose/ — 합성 기하 · 그리기 (TypeScript)

관리자 웹과 웹 부스가 함께 쓰는 `composePlan` · `renderCompose` · `coverCrop` 등. 자세한 내용은 [compose/README.md](compose/README.md).
