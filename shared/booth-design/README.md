# shared/booth-design/

부스(Python · 웹)와 참가자 사진 페이지가 **함께 쓰는 디자인 토큰**. 부스 · 사진 페이지의 값은 여기만 고친다.
설계: `docs/superpowers/specs/2026-10-19-booth-design-system-design.md` (3.1 토큰).
화면 규칙 요약(impeccable 화면 문서): `.impeccable/surfaces/booth.md`. 남은 과제: `docs/superpowers/followups/2026-10-19-booth-design.md`.

| 파일 | 내용 |
| --- | --- |
| `tokens.json` | 색 역할 · 글자 · 간격 · 화면별 배치(가로/세로) · 인화지 · 표기 · 움직임 · 터치 값 |
| `booth_tokens.py` | Python 로더 (표준 라이브러리만). `load()` · `validate()` · `layout()` |
| `tests/test_tokens.py` | 구조 검증 테스트 |
| `booth-tokens.js` · `.d.ts` | JS 로더 (의존성 없음, 브라우저 import 가능). `contrast` · `inkOn` · `mix` · `resolveRoles` · `creditVisible` · `applyEventColors` |
| `tools/build-css.mjs` · `tokens.css` | CSS 변수 생성기와 그 결과물 (커밋한다) |
| `mockups/` · `tools/check-mockups.mjs` | 기준 시안(정적 HTML)과 시안의 직접 값 검사 — 아래 '시안' 절 |

- 토큰은 행사 색 '값'을 담지 않는다. 행사 색(`primary` · `accent` · `bg_top` · `bg_bottom`)은 번들에서 오고, 토큰은 어디에 쓰는지만 정한다.
- 가로 배치(1920×1080 기준)는 지금 Python 부스 상수와 같다. `booth/tests/test_design_tokens.py` 가 대조한다.
- 세로 배치는 1080×1920 기준. 값은 숫자 · 배열만 쓴다 (JS 로더 · CSS 생성기가 그대로 읽는다).

## 테스트

저장소 루트에서:

```
server/.venv/bin/python -m pytest shared/booth-design/tests -q
cd booth && .venv/bin/python -m pytest tests/test_design_tokens.py -q
```

## 색 역할 해석

`resolve_roles(tokens, event)` 는 행사 색 네 개를 색 역할로 풀어낸다. 글씨 색은 위·아래 배경 **두 끝 모두**에서 본다. 기준 파일 `expected.json` 은 `tools/gen_expected.py` 가 만들고 (사례 목록은 `tests/cases.py` 한 곳), JS 구현이 같은 값을 내는지 대조한다. 색은 소문자 `#rrggbb`.

- **`on_action` 은 3.0 으로 검사한다.** 검정 · 흰색 중 나은 쪽을 고르므로 중간 명도 강조색(예: `#7f7f7f`)에서는 4.5 를 못 넘을 수 있다. 버튼 글자는 48px 굵은 글씨(WCAG 큰 글자)라 기준이 3.0 이다.
- **`credit`(제작 표기)은 대비 기준에서 뺀다.** 상표 문자열(로고타입)이라 스펙 4.1 의 '모든 글자 역할'에서 제외된다. 색은 `title` 을 따르되 알파 0.45 로 옅게 쓴다.
- **`perforation`(인화지 필름 구멍)** 은 `primary` 와 인화지(`fixed.paper`)의 대비가 3.0(`non_text`) 이상이면 `primary`, 아니면 `dark_ink`. 알파 0.16 은 그대로. `film`(= primary)은 인화지 밖(필름 넘김 전환)에서 계속 쓴다.
- `credit_visible()` 은 지금 항상 `True`. 나중에 `branding.show_credit` 를 읽을 자리다.

## JS 로더 · tokens.css

- JS `resolveRoles` 는 Python `resolve_roles` 와 같은 값을 낸다. `admin/src/boothDesign/boothTokens.test.ts` 가 `expected.json` 으로 대조한다 (`cd admin && npx vitest run src/boothDesign`).
- `applyEventColors(el, tokens, event)` 는 요소에 `--role-<이름>` (밑줄은 `-`) 변수를 넣는다. `action_edge` 가 null 이면 `transparent`.
- `tokens.css` 는 생성물이다. `tokens.json` 을 고친 뒤 저장소 루트에서 다시 만든다 (테스트가 최신인지 확인한다):

```
node shared/booth-design/tools/build-css.mjs
```

- 변수 이름: `--type-<크기>` · `--type-portrait-scale` · `--type-weight-<regular|bold|number>` · `--space-<0..6>`(step 배열 순번) · `--radius-<이름>` · `--print-*`(인화지 구멍 `--print-perforation-*`, 필름 넘김 구멍 `--print-film-strip-*`) · `--credit-*` · `--motion-ease` · `--motion-<short|base|long>` · `--alpha-<이름>` · `--fixed-<이름>` · `--touch-*`(선 두께 `--touch-line`).
- 알파(`color.alpha`)는 0 보다 크고 1 이하: 표기 · 필름 구멍 · 안내 글자 · 인화지 그림자 외에 `disabled`(누를 수 없는 버튼 · 칸) · `muted`(끝에 닿은 화살표) · `dim`(다시 찍을 컷 덮개) · `overlay`(셔터 번쩍임 · 현상 막) · `placeholder`(사진이 오기 전 자리) · `frame_bed`(프레임 미리보기 바탕) · `empty_slot`(빈 컷 칸 점선). 시안의 투명도는 모두 이 이름으로 쓴다.
- `validate()` 는 묶음 · 화면 · 방향 외에 `color.roles` · `fixed` · `alpha` · `min_contrast` 가 있는지, 알파 범위, 화면 배치가 묶음(dict)인지, `motion.transition.*.duration` 이 `short` · `base` · `long` 중 하나인지 확인한다 (실패하면 한국어 `ValueError`). 픽셀 값은 `px`, 시간은 `ms`, 비율 · 알파는 단위 없음. 밑줄은 `-` 로 바뀐다.
- 행사 색(`--role-*`)과 화면 배치(`layout`)는 `tokens.css` 에 넣지 않는다. 배치가 CSS 에서 필요해지면 `--layout-<화면>-<방향>-<키>` 이름으로 생성기에 추가한다.

## 시안 (`mockups/`)

빌드 도구 없는 정적 HTML · CSS · ES 모듈. 색 · 크기는 `tokens.css` 변수와 행사 색 역할(`--role-*`)로만 그린다.

### 보기

저장소 루트에서:

```
python3 -m http.server 8765 --directory shared/booth-design
# 브라우저: http://localhost:8765/mockups/?screen=demo-flow&ratio=16x9
node shared/booth-design/tools/check-mockups.mjs              # 직접 적은 색 · 크기 검사 (있으면 종료 코드 1)
node shared/booth-design/tools/check-mockups.mjs --self-test  # 검사기 자체 확인
```

스크린샷 · 기준 비교 (macOS, chrome-headless-shell 은 `~/Library/Caches/ms-playwright` 에서 찾고 없으면 `CHROME` 환경 변수):

```
node shared/booth-design/tools/shoot-mockups.mjs [--out DIR] [--only 화면이름]   # 기본 출력 .superpowers/mockup-shots/ (git 제외)
```

화면 × 기본 상태 × 화면비 6종과 모든 상태 × 16x9 를 찍고(약 110장, 20초 안팎), `compare.html` 에 기준 PNG(`docs/design/booth-baseline`)와 16:9 시안을 나란히 붙인다. 기준 ↔ 시안 짝은 스크립트 위쪽 `BASELINE_MAP` 표 한 곳에 있다. `demo-flow` 는 화면비 훑기에서 뺀다.

`shared/booth-design` 을 뿌리로 열어야 한다 (시안이 `../tokens.json` · `../tokens.css` · `../booth-tokens.js` 를 읽는다).

### URL 질의값

위쪽 조절 막대로 바꾸면 주소에 바로 적힌다. 스크린샷 도구는 이 주소를 그대로 쓴다.

| 값 | 뜻 | 기본 |
| --- | --- | --- |
| `screen` | 화면 이름 (`screens/index.js` 의 `name`) | 목록 첫 화면 |
| `state` | 화면별 상태 (`screens/index.js` 의 `states`) | 그 화면의 첫 상태 |
| `ratio` | `16x9` `16x10` `4x3` `3x4` `9x16` `9x19.5` — 가로/세로 ≥ 1 이면 가로 배치 (`layout.ratio_switch`) | `16x9` (화면 목록에 `ratio` 가 있으면 그것 — 사진 페이지는 `9x19.5`) |
| `colors` | 행사 색 프리셋 `default` `dark` `light-primary` `yellow-accent` `custom` (`mockups/presets.js`) | `default` |
| `custom` | `colors=custom` 일 때 `주요-강조-배경위-배경아래` (`#` 없는 6자리 16진, 예 `1b2550-e66e82-fff8f9-eaf4fb`) | 기본 색 |
| `credit` | 하단 표기 `on` · `off` | `on` |
| `input` | `remote` (포커스 테두리 보임) · `touch` (숨김) | `remote` |
| `cuts` | 컷 수 `1` `4` `12` `18` | `4` |
| `bar` | `off` 면 조절 막대를 숨기고 무대만 (스크린샷용) | `on` |

그리기가 끝나면 `document.body.dataset.ready === "1"` 이 된다 (글꼴까지 읽은 뒤).

### 무대

- 무대는 설계 단위로 그린다: 가로 배치는 폭 1920, 세로 배치는 폭 1080 (높이는 화면비로). 창에는 `transform: scale` 로 맞춘다. 무대 안에서 `1px` = 설계 단위 1.
- **화면비 맞춤은 무대의 규칙 하나** (스펙 2.3). `tokens.layout` 은 가로 1920×1080 · 세로 1080×1920 기준(`ctx.base`)이다. `k = min(무대 폭 / 기준 폭, 무대 높이 / 기준 높이)` 로 두고, `ctx.screenBox()` 는 무대를 꽉 채우는 `(무대 / k)` 크기 상자를 `k` 배로 줄여 그린다 — 기준보다 남는 쪽(slack)만 늘어난다. 상자 크기는 `ctx.box` (`{w, h, k}`).

  | 화면비 | 상자 (배치 단위) | k |
  | --- | --- | --- |
  | 16:9 · 9:16 | 1920×1080 · 1080×1920 (기준 그대로) | 1 |
  | 16:10 · 4:3 | 1920×1200 · 1920×1440 | 1 |
  | 9:19.5 | 1080×2340 | 1 |
  | 3:4 | 1440×1920 | 0.75 |

- 파이썬 좌표는 `ctx.x(baseX, pin)` · `ctx.y(baseY, pin)` 로 옮긴다. `pin` 은 남는 폭 · 높이를 얼마나 더할지 — `left`/`top` 0, `center` 절반(기본), `right`/`bottom` 전부. 핵심 요소(미리보기 · 컷)는 `center`, 제목은 `top`, 세로 화면의 버튼 줄 · 최근 컷 줄은 `bottom` (엄지가 닿는 아래, 세로 규칙 3). 16:9 · 9:16 에서는 남는 쪽이 0 이라 파이썬 좌표와 똑같다.
- 배경 그라데이션 · 하단 표기 · 필름 넘김 층은 무대가 그린다. 화면은 그리지 않는다. 표기는 `--stage-k` 로 화면 상자와 같은 배율이 된다.
- **표기 자리 규칙**: 표기는 무대가 그리는 요소 하나, 보일지는 `creditVisible()` 하나. 자리는 기본이 아래 가운데 `credit.bottom` 이고, 화면이 요소와 겹치면 그 화면의 배치 토큰 `layout.<화면>.<방향>` 에 선택 값 `credit_x`(기준 x — 화면 상자에서 가운데 핀) · `credit_bottom`(바닥에서의 높이, 상자 단위)을 적어 덮어쓴다. 무대가 화면을 열 때 읽고(`placeCredit`), 장면을 스스로 바꾸는 화면(움직임 데모)은 장면마다 `ctx.creditAt(화면 배치 이름)` 을 부른다. `credit_bottom` 은 `--credit-bottom` 을 덮어써 `--credit-reserve` 도 따라간다. 지금 덮어쓰는 곳: 촬영 가로 `credit_x` 170 — 미리보기(y 40~1040, 1240×1000 고정) 왼쪽 칸 ('컷 k / N' 열) 아래. 미리보기가 가장 넓을 때(1240) 왼쪽 칸의 가운데라 어떤 컷 비율에서도 미리보기와 겹치지 않는다.
- 화면의 안내 줄 · 바닥에 붙는 것은 `--credit-reserve` 위에 둔다 (`bottom: var(--credit-reserve)` — 상자 단위, 표기를 숨기면 `--credit-hidden-bottom`). 가로 미리보기 크기는 파이썬 값 그대로 둔다 (표기 쪽을 줄이지 않고 안내 줄을 올린다).

### 화면 더하기 (Task 7 · 8)

1. `mockups/screens/<이름>.js` 를 만든다.

```js
import { registerScreen, h } from "../stage.js";
import { carousel } from "../motion.js";

registerScreen("idle", (ctx) => {
  const L = ctx.layout("idle");                 // tokens.layout.idle[ctx.orientation]
  const root = h(`<div></div>`);                // 무대가 .scene 을 붙여 넣는다
  const box = ctx.screenBox();                  // 무대를 꽉 채우는 화면 상자
  root.append(box);
  const title = h(`<div class="t-hero ink-title"></div>`);
  title.textContent = ctx.text.normal.title;
  box.append(ctx.place(title, { x: ctx.x(ctx.base.w / 2), y: ctx.y(L.title_y), w: L.title_max_w, anchor: "center" }));
  const start = h(`<div class="btn-action focus">버튼을 눌러 시작!</div>`);
  const low = ctx.orientation === "portrait" ? "bottom" : "center";
  box.append(ctx.place(start, { x: ctx.x(ctx.base.w / 2), y: ctx.y(L.start_button_center_y, low),
    w: L.start_button[0], h: L.start_button[1], anchor: "center" }));
  ctx.onKey((key) => { /* "left" "right" "up" "down" "enter" "back" */ });
  return root;
});
```

2. `mockups/screens/index.js` 의 `SCREENS` 에 `{ name, label, file, states, css? }` 를 더한다. `css` 를 적으면 `screens/<css>` 를 그 화면을 열 때 함께 읽는다.
3. `node shared/booth-design/tools/check-mockups.mjs` 통과, `ratio=16x9` 와 `ratio=9x19.5` 로 열어 본다.

사진이 없는 화면(`pairing` `dial` `idle` `choose` `admin` `import_zip` `waiting`)은 공용 조각 `screens/parts.js` 와 `screens/booth.css` 를 같이 쓴다:
`hint()`(아래 안내 줄 — 파이썬 자리, 단 `--credit-reserve` 위로만) · `message()`(오류 · 잠금 — 강조색 배지 + 제목색 글자) · `numberInput()`(리모컨 다이얼 + 터치 숫자 패드가 같은 칸을 채운다) · `pairingScreen()` · `adminScreen()` · `adminHotspot()` · `note()`.
사진이 있는 화면(`capture` `pick` `review` `retake` `share` `print_copies`)은 `screens/photo.css`(첫 줄에서 `booth.css` 를 이어 읽는다)와
`screens/prints.js` 를 쓴다: `fit()` · `cutRatio()`(샘플 프레임 컷 비율) · `photoAt()` · `print()` · `printSize()` · `printIn()`(인화지 — 찍힌 사진에만) ·
`composite()`(완성본 — 프레임 아래 컷 사진, 기본 `.fx-develop`) · `qrCode()` · `badge()`(고른 순서 = 강조색 `is-order`, 컷 번호 = 인화지색 `is-cut`) · `ticking()`(남은 초).
움직임 데모(`demo-flow`)도 같은 `print` · `composite` · `qrCode` 를 쓴다. 공용 모양 `.composite` · `.qr` 은 `mockups.css`.
사진 고르기의 `cuts=` 는 프레임 컷 수 N 이고 격자는 N + 2 장(기준 번들 `extra_shots`)이다. 고르기는 칸을 줄여 격자 영역에 다 넣는다.
다시 찍기는 사진 크기를 줄이지 않는다 — 가로는 파이썬 한 줄(`thumb_box` 380×480), 세로는 2열이고 컷이 많으면(12 · 18) 같은 크기의 줄이 여럿이 된다. 제목 · 컷 줄 · 버튼 줄이 한 지도로 ↑↓(`rowShift` — 그 줄이 창 가운데로 와서 다 보인다) · 손가락 끌기(`dragScroll`)로 함께 밀린다.
인쇄 매수는 동그라미(표시, 강조색 아님) 양옆 ◀ ▶ · 리모컨 ←→ 로 매수를 바꾸고, 아래 따로 있는 강조색 [n장 인쇄] 버튼(`print_button` · `print_button_y`)으로 인쇄한다 — 리모컨은 ↓ 로 버튼 줄, Enter.
촬영 · 다시 찍기 · 필터 목록은 함수(`captureScene` · `retakeScene` · `liveList`)로 내보내 움직임 데모가 그대로 쓴다 — 조절 막대의 컷 수가 데모의 촬영 · 다시 찍기에도 들어간다.
`photo_page` 는 실제 페이지(`server/app/templates/photo.html`)를 옮긴 것 — 무대 안에 기기 화면(`samples.json` 의 `devices`: 휴대폰 390×844 · 노트북 1280×720 CSS 픽셀)을 그리고, 템플릿의 픽셀 값을 기기 1픽셀(`--u`)의 배수로 쓴다. 이 화면은 부스 하단 표기 대신 페이지 자신의 표기('호두네사진관으로 찍었어요')를 그린다.

리모컨 · 터치에 따라 다른 문구는 `.remote-only` · `.touch-only` 로 둘 다 그려 두면 무대 `data-input` 으로 하나만 보인다. 점선 `.mk-mark` · `.mk-note` 는 시안에서만 보이는 표시(관리자 숨은 동작 자리 · 예외 상황 설명)다. 관리자 숨은 동작은 그 자리를 `touch.long_press_ms`(1200ms, CSS `--touch-long-press`) 동안 누르고 있는 것이다.

`registerScreen(name, render)` — `render(ctx)` 는 화면 뿌리 요소를 돌려준다. 조절 막대에서 화면 · 상태 · 화면비 · 컷 수를 바꾸면 다시 부르고, 색 · 표기 · 입력 모드는 다시 부르지 않고 무대에 바로 입힌다 (CSS 변수 · `data-*` 로 반영되게 그린다).

`ctx` (StageCtx):

| 이름 | 내용 |
| --- | --- |
| `orientation` | `"landscape"` · `"portrait"` |
| `cuts` · `state` · `input` | URL 질의값 |
| `roles` | `resolveRoles` 결과 (JS 에서 대비 판단이 필요할 때만 — 색은 CSS `var(--role-*)` 로 쓴다) |
| `tokens` | `tokens.json` 전체 |
| `size` · `base` | 무대 크기 · 배치 토큰 기준 크기 (설계 단위 `{w, h}`) |
| `screenBox()` · `box` | 화면 상자 요소 · 그 크기 `{w, h, k}` (위 '무대') |
| `x(baseX, pin)` · `y(baseY, pin)` | 기준 좌표 → 상자 좌표 (`left`·`center`·`right` / `top`·`center`·`bottom`) |
| `layout(screen, orientation?)` | `tokens.layout[screen][orientation]` |
| `px(n)` | 설계 단위 숫자 → `"<n>px"` (토큰에서 읽은 숫자에만 쓴다) |
| `place(el, {x, y, w?, h?, anchor?})` | 절대 위치. `anchor` 는 `topleft` `midtop` `topright` `midleft` `center` `midright` `bottomleft` `midbottom` `bottomright` (파이썬 `ui.text` 기준점과 같다). 기준점은 CSS `translate` 로 맞추므로 `transform` 연출과 겹치지 않는다 |
| `onKey(fn)` | 리모컨 키 받기. 키보드(←↑↓→ · Enter/스페이스 · Esc/Backspace)와 조절 막대의 화살표 버튼이 같은 키를 보낸다 |
| `credit` | 표기가 보이는지 |
| `creditAt(screen)` | 표기 자리를 그 화면 배치 토큰(`credit_x` · `credit_bottom`)으로 — 무대가 화면을 열 때 부르고, 움직임 데모는 장면마다 |
| `text` | 행사 글자 샘플 `normal` · `long` (`presets.js`) |
| `samples` | `photos` (4장) · `photoRatio` · `frame` (`url`, `ratio`, `windows` = 컷 자리 `[x, y, w, h]` 비율) · `logo` (`url`, `size` — 행사 로고 자리) · `devices` (`phone` · `desktop` — 사진 페이지가 흉내 내는 기기 CSS 픽셀) |
| `stage` | 무대 요소 |

`h(html)` — 문자열 한 덩어리를 요소로.

### 공용 요소 (`mockups.css`)

| 클래스 | 쓰는 곳 |
| --- | --- |
| `.print` + 안에 `img`(또는 `.print-photo`) + `.perf` | 인화지 — **찍힌 사진이 있는 곳에만**. 크기는 `.print` 에 준다(여백 포함). `.perf` 는 아래 여백 안 필름 구멍 줄 (`--role-perforation`) |
| `.credit` | 하단 표기 — 무대가 하나만 그린다 (`creditVisible()` && `credit=on`). 화면은 만들지 않는다 |
| `--credit-reserve` | 화면 아래에 비워 둘 높이 (상자 단위). 표기가 보이면 표기 자리, 숨기면 `--credit-hidden-bottom` (빈자리 없이). 안내 줄 등 아래 붙는 요소는 `bottom: var(--credit-reserve)` |
| `.btn-action` | 지금 누를 버튼 — 강조색, 글자는 `--role-on-action`, 강조색이 배경에 묻히면 `--role-action-edge` 테두리 |
| `.btn-line` | 보조 버튼 — 테두리형 주요색 (`--role-line`) |
| `.focus` | 포커스된 요소에 붙인다. 테두리는 `input=remote` 일 때만 보인다 |
| `.camera` + 안에 `img` | 카메라 미리보기 — 둥근 화면, 흔적 없음 |
| `.t-countdown` `.t-display` `.t-hero` `.t-title-xl` `.t-question` `.t-title-l` `.t-title` `.t-headline` `.t-button` `.t-body` `.t-label` `.t-caption` `.t-badge` | 글자 크기 단계 (세로는 `--type-portrait-scale` 배). `display` 150 · `title_xl` 110 · `question` 90 · `title_l` 80 · `badge` 24 는 파이썬 대기 제목 · 페어링 제목 · 인쇄 매수 질문 · 번들 제목 · 촬영 컷 번호가 가까운 단계와 4 넘게 달라 따로 둔 단계, `countdown` 은 파이썬 촬영 숫자 260 (가로 = 파이썬 그대로) |
| `.ink-title` · `.ink-hint` | 글자색 역할 |
| `.fx-develop` · `.fx-pop` · `.fx-reveal` | 새로 그린 요소에 붙이면 한 번 재생 — 현상되듯(인화지) · 카운트다운 숫자 · QR 등장 |
| `--mk-line` | 선 두께 (포커스 테두리의 절반 — 토큰에 따로 없다) |

### 움직임 (`motion.js`, 스펙 2.4)

| 함수 | 입력 | 움직임 |
| --- | --- | --- |
| `slideTo("forward", nextEl)` | 다음 단계 (Enter · 탭) | 지금 화면은 왼쪽으로, 다음 화면이 오른쪽에서 |
| `slideTo("back", nextEl)` | 뒤로 | 화면이 오른쪽으로 밀린다 |
| `rowShift(containerEl, row)` | ↑↓ 줄 이동 | `containerEl` 의 `[data-row]` 자식 중 `row` 번째로. 내용이 위로 올라온다. 창에 다 들어가면 `--space-4` 만큼, 넘치면 그 줄이 가운데로. 돌려준 값이 실제 줄 번호 |
| `carousel(listEl, index)` | ←→ 목록 | 고른 항목을 부모(보이는 창) 가운데로, `.is-current` 를 붙인다. 축은 `data-axis="x|y"` 또는 `flex-direction`. 돌려준 값이 실제 번호 |
| `filmTo(nextEl)` | 큰 전환 (촬영 시작 · 완성) | 주요색 필름 한 칸이 오른쪽 → 왼쪽으로 한 번에 지나간다 (film 길이). 필름이 화면을 다 덮은 순간 장면이 바뀐다 |
| `fadeHome(nextEl)` | 처음으로 (공유 끝 · 시간 초과) | 지금 화면이 사라지며 아래의 대기 화면 |
| `flash()` · `flyTo(fromEl, toEl)` | 셔터 · 찍힌 컷 | 번쩍임 · 복사본이 칸으로 날아간다 |
| `dragScroll(listEl, {snap, axis?, onSettle})` | 손가락 끌기 · 휙 넘기기 · 휠 | `snap: "item"` 은 회전목마 목록, `"row"` 는 `rowShift` 줄 묶음. 끄는 동안 transform 만 따라가고, 놓으면 휙 넘긴 속도만큼(`touch.flick_project_ms`) 더 간 자리에서 가장 가까운 항목 · 줄 번호로 `onSettle` — 화면은 거기서 `carousel` · `rowShift` 를 다시 부른다(키 입력과 같은 길). 끌기와 탭의 문턱은 `touch.drag_threshold_px`, 끈 뒤의 click 은 먹는다. 줄 묶음은 넘칠 때만 끌린다 |
| `busy()` · `motionMs(step)` | | 장면 전환 중인지 · `--motion-<short|base|long>` 밀리초 |

- 장면 전환(`slideTo` · `filmTo` · `fadeHome`)은 무대 장면 층(또는 세 번째 인자 `host`)의 마지막 장면을 `nextEl` 로 바꾼다. 다음 장면은 미리 한 번 그려 두고 transform · opacity 로만 움직인다. 전환은 줄 세워 차례로 돈다.
- 길이 · 곡선은 `--motion-*` 변수. 어느 단계를 쓰는지는 `tokens.motion.transition` (밀어내기 base · 필름 long · 처음으로 base).
- `prefers-reduced-motion` 이면 움직이지 않고 바로 바뀐다.
- 움직임 데모: `?screen=demo-flow` — 대기 → 필터 → (필름) 촬영 → (필름) 완성 확인 → 공유 → (사라지며) 대기, 완성 확인의 '다시 찍기' → 다시 찍기 고르기(컷 줄 ↔ 버튼 줄, 취소는 뒤로).

### 검사 (`tools/check-mockups.mjs`)

`mockups/` 의 `.html .css .js` 에서 16진 색 · 색 함수 · 색 속성 자리의 이름 색 · 절대 길이(`<숫자>px` 등)를 찾는다 (주석 포함). 허용: `samples/` · `fonts/` 폴더, `presets.js` 의 색(행사 입력 데이터), `calc()` 안의 `0px`, 단위 없는 숫자(토큰 배수 · JS 배치 계산). `var(--x, 12px)` 같은 대체값은 허용하지 않는다. 자세한 근거는 스크립트 머리 주석.

- `#abc` 처럼 16진 글자만으로 된 id 선택자(`#bad` `#face`)는 색으로 잡히니 쓰지 않는다.
- 글꼴: `mockups/fonts/` 에 Paperlogy(SIL OFL, `OFL.txt`) 복사본 — Medium · ExtraBold 원본은 `admin/public/fonts/`, 숫자용 Black(`type.weight.number` 900, `.t-number`)은 `booth/assets/fonts/Paperlogy-9Black.ttf` 그대로 (파이썬 부스 number 글꼴).
- 샘플: `mockups/samples/` 의 사진 4장 · 4컷 프레임 1장 · 행사 로고 자리 1장은 직접 만든 단색 그라데이션 + 도형 PNG 다 (외부 사진 없음). 컷 자리는 `samples.json`. 다시 만들기: `server/.venv/bin/python shared/booth-design/tools/make-samples.py` (Pillow).

## 복사본 (서버 · Python 부스)

서버(`server/app/booth_design/`)와 Python 부스(`booth/walnut/booth_design/`)는 각자 배포되므로 `tokens.json` · `booth_tokens.py` 복사본을 쓴다.
원본을 고치면 저장소 루트에서 `python3 shared/booth-design/tools/sync-server.py` 로 두 곳을 함께 갱신한다.

기본 프레임(`default-frame/frame.png` · `frame.json`, 4컷 2×2)도 같은 스크립트가 Python 부스(`booth/walnut/default_frame/`)로 옮긴다.
부스를 연결 없이 시작할 때 쓰는 기본 번들의 프레임이다. 그림을 바꾸려면 PNG 와 슬롯(`frame.json`)을 함께 고치고 스크립트를 다시 돈다.
어긋남은 `server/tests/test_photo_design.py` · `booth/tests/test_design_tokens.py` 가 잡는다.
