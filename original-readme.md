# 부스 앱 (booth)

행사장 PC 에서 도는 촬영 앱 (pygame-ce). 관리자 웹에서 게시한 행사 설정(번들)을 서버에서 받아
촬영 → 고르기 → 합성 → QR 공유(→ 인쇄)까지 한다. 완성 사진은 백그라운드로 서버에 올라간다.

## 설치 · 업데이트 (부스 PC — Windows · Mac)

부스 PC 에서 **https://walnutfourcut.team-cluster.kr/download/** 를 열어 설치 파일 하나를 받아 실행한다.
(관리자 웹 → 행사 → 부스 탭의 "부스 앱 설치 파일 받기" 도 같은 곳.) 새로 설치한 PC 여도 된다.

| | Windows | Mac |
|---|---|---|
| 설치 파일 | `walnutstudio-setup.cmd` — 더블클릭 ('Windows의 PC 보호' 가 뜨면 추가 정보 → 실행) | `walnutstudio-setup.command` — Finder 에서 **우클릭 → 열기** |
| Python 3.11 이 없으면 | winget 으로 사용자 계정에 설치 (없으면 python.org 3.11.9 설치 파일) | python.org 3.11.9 설치 파일 (Mac 비밀번호 한 번) |
| 설치 위치 | `%LOCALAPPDATA%\walnutstudio` | `~/walnutstudio` |
| 바탕화면 | `호두네사진관` (실행) · `호두네사진관 업데이트` | `호두네사진관.command` · `호두네사진관 업데이트.command` |

설치 파일이 하는 일: Python 3.11 확인 · 설치 → 부스 앱 zip 받아 풀기 → 가상환경 · 의존성 → 얼굴 모델 →
`.env`(없을 때만, 서버 주소가 채워져 있다) → 바탕화면 아이콘 → 실행. 그다음 관리자 웹에서 받은 페어링 코드를 넣는다.

- **업데이트**: 바탕화면의 '호두네사진관 업데이트' (= 설치 파일을 다시 실행). 코드만 바꾸고 `data/`(사진 · 번들) · `.env` · `.venv` · `models/` 는 그대로 둔다. 중간에 끊겨도 다시 실행하면 이어서 된다.
- **Mac 카메라 권한**: 첫 촬영 때 '터미널이 카메라에 접근' 을 [허용]. 놓쳤으면 시스템 설정 → 개인정보 보호 및 보안 → 카메라 에서 터미널을 켠다.
- 설치 파일 · zip 은 관리자 웹과 함께 Cloudflare Pages 가 `main` 푸시마다 만든다 (`admin/pages/package-booth.mjs`). 누구나 받을 수 있다 — 페어링 코드 없이는 쓸 수 없는 프로그램이다.
- 버전: zip 의 `VERSION`(예: `0.1.0+a1b2c3d` = 앱 버전 + 커밋)이 서버에 알리는 앱 버전이 된다 → 관리자 웹 부스 목록에서 부스별 버전을 본다.
- 설치 스크립트 시험용 환경 변수: `WALNUTSTUDIO_DIR`(설치 위치), `WALNUTSTUDIO_ZIP`(zip 주소나 로컬 경로), `WALNUTSTUDIO_BASE`, `WALNUTSTUDIO_NO_SHORTCUT=1`, `WALNUTSTUDIO_NO_LAUNCH=1`.

## 개발 PC 에서 실행

저장소에서 바로 돌릴 때는 Python 3.11 (또는 3.12 — 3.13 이상은 mediapipe 휠이 없다) 로 `.venv` 를 만들고
`.env.example` 을 `.env` 로 복사한 뒤 `run.bat`(Windows) · `run.command`(Mac).

직접 실행할 때 (Windows):

```
.venv\Scripts\python main.py                 # 전체 화면 (.env 의 BOOTH_FULLSCREEN)
.venv\Scripts\python main.py --windowed      # 창 모드 (개발용)
.venv\Scripts\python main.py --no-camera     # 카메라 없이 화면 흐름만 확인
.venv\Scripts\python main.py --list-cameras  # 연결된 카메라 번호 확인
```

직접 실행할 때 (Mac):

```
.venv/bin/python main.py                     # 전체 화면 (.env 의 BOOTH_FULLSCREEN)
.venv/bin/python main.py --windowed          # 창 모드 (개발용)
.venv/bin/python main.py --no-camera         # 카메라 없이 화면 흐름만 확인
.venv/bin/python main.py --list-cameras      # 연결된 카메라 번호 확인
```

- `source .venv/bin/activate` 로 venv 를 켜 두면 그 터미널에서는 `python main.py` 로 짧게 쓸 수 있다.
- 처음 실행하면 macOS 가 카메라 권한을 묻는다. 실행한 앱(터미널 · VS Code 등)에 허용해야 웹캠이 잡힌다
  (나중에 바꾸려면 시스템 설정 → 개인정보 보호 및 보안 → 카메라).

## 개발자 모드 (연결 코드 없이 버스트샷 보기)

연결 코드 · 서버 없이 바로 촬영해 보는 모드다. 기본 번들(기본 설정 + 기본 4컷 프레임)로 대기 화면에서 시작하고,
버스트샷(컷마다 셔터 앞뒤 약 1초의 연속 프레임에서 가장 좋은 한 장을 고르는 기능)이 켜진다.

| 인자 | 동작 |
|---|---|
| `--dev-mode` | 버스트샷이 들어간 부스를 평소처럼 써 본다 |
| `--dev-mode-all` | 위에 더해, 컷마다 **베스트 컷 분석 화면**으로 고르는 과정을 보여 준다 |

준비 (처음 한 번, `booth/` 폴더에서. Python 3.11 또는 3.12):

```
# Windows (PowerShell · cmd)
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# Mac (zsh)
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

실행:

```
# Windows (PowerShell · cmd)
.venv\Scripts\python main.py --dev-mode-all
.venv\Scripts\python main.py --dev-mode
.venv\Scripts\python main.py --dev-mode-all --windowed    # 창 모드

# Mac (zsh)
.venv/bin/python main.py --dev-mode-all
.venv/bin/python main.py --dev-mode
.venv/bin/python main.py --dev-mode-all --windowed
```

- 두 인자는 함께 쓸 수 없다. `--windowed` · `--no-camera` 와는 함께 쓸 수 있다. `run.bat` · `run.command` 뒤에 붙여도 된다.
- **첫 실행에는 인터넷이 필요하다.** 얼굴 모델(`models/face_landmarker.task`, 약 4MB)이 없으면 자동으로 내려받는다.
  못 받으면 이유를 출력하고 끝난다 (모델 없이 버스트샷이 꺼진 채 도는 일을 막는다).
- `.env` 가 없어도 된다. 카메라 번호가 0번이 아니면 `--list-cameras` 로 확인해 `.env` 에 `CAMERA_INDEX` 를 적는다.
- 카운트다운은 4초. 사진 · 기록은 `booth/data-dev/` 에만 남는다 (실제 `data/` 의 페어링 · 사진은 건드리지 않고, 서버로 아무것도 보내지 않는다).
- 조작: `Enter` 시작 · 선택, `F2` 건너뛰기, `F5` 처음 화면, `ESC` 패널 → `Q` 두 번이면 종료.

베스트 컷 분석 화면 읽는 법 (`--dev-mode-all`):

- 윗줄: 셔터 -0.7초 ~ +0.3초 사이의 후보 전부 (0.08초 간격, 보통 10~13장). 아래 숫자는 셔터 기준 시각과 종합 점수.
  흐려진 컷은 탈락이고 사유가 적힌다 — `흔들림`(선명도 부족) · `눈 감음` · `얼굴 수 부족`.
- 가운데: **카운트다운 순간**(버스트샷이 없었다면 찍혔을 컷)과 **베스트 컷**(실제로 쓴 컷), 그리고 각각의 선명도 · 눈 뜸 · 정면 · 점수.
- 아래: 고른 이유 한 줄. `Enter` 로 다음 컷, 20초 동안 입력이 없으면 자동으로 넘어간다.
- 썸네일은 필터 · 스티커를 입히지 않은 원본이다 (비교가 목적).

## `.env` (이 기기에만 해당하는 값)

| 키 | 기본값 | 뜻 |
|---|---|---|
| `SERVER_URL` | (없음) | 서버 주소, 끝 `/` 없이. 비우면 페어링 화면에 안내만 뜬다 |
| `CAMERA_INDEX` | `0` | 카메라 번호 (`--list-cameras` 로 확인) |
| `CAMERA_WIDTH` · `CAMERA_HEIGHT` | `1920` · `1080` | 카메라 해상도 |
| `REMOTE_PORT` | (빈 값) | 리모컨 시리얼 포트. 빈 값 = 자동 탐색, `off` = 끔, `COM3` 처럼 직접 지정 |
| `BOOTH_FULLSCREEN` | `true` | 전체 화면 |
| `SYNC_INTERVAL` | (빈 값) | 동기화 주기(초). 있으면 번들 값보다 우선 |

나머지(브랜딩·촬영·필터·스티커·공유·인쇄·PIN)는 모두 관리자 웹에서 정하고 번들로 받는다.

## 페어링

1. 관리자 웹 → 행사 → **부스** 탭 → [부스 추가] → 이름을 넣으면 8자리 코드가 나온다 (10분, 한 번만).
2. 부스 첫 화면(페어링)에서 그 코드를 넣는다. 키보드 숫자 또는 리모컨(방향키 + Enter).
3. 연결되면 번들을 받아 대기 화면으로 간다. 행사가 아직 게시 전이면 "행사 준비 중" 화면에서 기다린다.

관리자 웹에서 부스를 **폐기**하면 다음 동기화 때 부스가 연결 해제되고 페어링 화면으로 돌아간다.
못 올린 사진은 지우지 않고 `data/outbox/orphaned/` 로 옮긴다.

## 연결 없이 시작

페어링 화면 오른쪽 위의 **[연결 없이 시작]** (키보드는 `Tab`)을 누르면 코드 없이 기본 번들로 바로 촬영할 수 있다.
`SERVER_URL` 이 비어 있어도 된다.

- 기본 번들 = 기본 설정값 + 기본 프레임 하나 (4컷 2×2, 원본 `shared/booth-design/default-frame/`).
- 되는 것: 촬영 · 필터 · 합성, 사진은 이 PC 의 `data/collage/` 에 `0_<월일-시분초>_<토큰>.jpg` 로 저장.
- 안 되는 것: QR · 업로드 · 스티커 · 인쇄 · 관리자 PIN. 공유 화면은 "부스 PC 에 저장되었어요" 로 나온다.
- 대기 화면 맨 위에 "연결 없이 사용 중" 이 표시된다.
- **저장하지 않는다.** 부스를 다시 켜면 페어링 화면으로 돌아온다 (행사장에서 연결을 잊은 채 돌아가지 않게).
- ESC (또는 구석 길게 누르기) 패널은 PIN 없이 열리고 [연결 코드 입력으로] 로 페어링 화면에 돌아간다.

## 관리자 키

| 키 | 동작 |
|---|---|
| `ESC` | 관리자 패널 열기/닫기 (PIN 6자리부터) |
| `F2` | 지금 단계 건너뛰기 |
| `F5` | 처음 화면으로 |
| 패널 안에서 `Q` 두 번 (3초 안) | 앱 종료 |

- 관리자 PIN 은 관리자 웹 → 행사 → **부스** 탭 → "동기화·관리자 PIN" 에서 보고 바꾼다. 바꾼 뒤 **게시**해야 부스에 반영된다.
  5번 틀리면 60초 잠긴다.
- 패널: 상태(서버 연결·번들 버전·대기 사진 수) + [지금 동기화] [번들 파일 가져오기] [연결 해제(재페어링)].
  연결 해제는 한 번 더 눌러야 실행된다.
- 페어링은 됐지만 번들을 아직 못 받은 상태(PIN 없음)에서는 ESC 가 PIN 없이 [번들 파일 가져오기] 만 있는 패널을 연다.
  페어링 전에는 종료 안내만 나온다.

## 비상용 번들 (서버에 닿지 않는 현장)

1. 관리자 웹 → 행사 → **게시** 탭 → [비상용 번들 받기] 로 zip 을 받는다.
2. zip 을 USB 에 담아 부스 PC 에 꽂거나, `booth/data/import/` 또는 사용자 `다운로드` 폴더에 넣는다.
3. 부스에서 ESC → 패널 → [번들 파일 가져오기] → 목록(최신 순, `data/import/` · 다운로드 · USB 루트)에서 고른다.

zip 은 같은 행사에 페어링된 부스에서만 열린다 (서명 확인). 페어링은 먼저 되어 있어야 한다.

## 데이터 폴더 (`booth/data/`, git 에 올라가지 않음)

```
data/
  device.json          서버 주소 · 기기 토큰 · 번들 키 (페어링 결과)
  bundles/<v>/         받은 번들 (bundle.json). 현재 + 바로 아래 1개만 남긴다
  bundles/current      지금 쓰는 번들 버전
  assets/<sha256>      프레임·로고·글꼴·스티커 파일
  collage/             완성 사진 (부스 PC 보관본)
  outbox/              올릴 사진 대기열 (<토큰>.jpg)
  outbox/failed/       서버가 거절한 사진 (다시 올리지 않음)
  outbox/orphaned/     연결 해제 때 남아 있던 사진
  print_spool/         인쇄할 이미지 (지금은 더미 프린터가 여기에 쌓는다)
  import/              비상용 번들 zip 넣는 곳
```

상태 파일은 모두 임시 파일에 쓴 뒤 바꿔 넣으므로, 전원이 꺼져도 다음 실행은 마지막 온전한 번들로 시작한다.

## 오프라인 동작

- 서버에 닿지 않아도 마지막으로 받은 번들로 계속 촬영한다. 동기화는 간격을 늘려 가며 다시 시도한다.
- QR 은 업로드를 기다리지 않고 바로 띄운다. 사진은 `outbox/` 에 남아 있다가 연결되면 올라간다
  (앱을 껐다 켜도 남은 것부터 올린다). 연결이 돌아오기 전에 QR 을 찍으면 잠깐 "준비 중" 페이지가 보인다.
- 완성 사진은 항상 `data/collage/` 에도 저장된다. QR 공유가 꺼졌거나 서버가 없으면 "부스 PC 에 저장되었어요" 로 끝난다.
- 새 번들은 받아 두기만 하고, 촬영 중이 아닐 때(대기 화면) 적용한다.

## 터치 시험 (터치 모니터)

터치 모니터에서 터치가 마우스 입력으로 한 번씩, 맞는 좌표로 들어오는지 부스 앱과 같은 화면 설정으로 확인하는 도구.

```
.venv\Scripts\python tools\touch_probe.py              # 전체 화면
.venv\Scripts\python tools\touch_probe.py --windowed   # 창 모드
```

확인할 것 (Q 또는 ESC 로 끝):

- 네 모서리 표식을 손가락으로 눌러 본다. 화면에 찍히는 좌표가 표식에 적힌 좌표와 거의 같아야 한다.
- 한 번 탭하면 `GESTURE tap` 이 한 번만 나와야 한다 (두 번 나오면 안 된다).
- 끌면 `drag` → `drag_end`, 왼쪽 위 노란 네모 안을 1.2초 이상 누르면 `long` 이 나와야 한다.
- 끝낸 뒤 `tools\touch_probe.log` 를 보내 주면 된다.

## 테스트

```
cd booth
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q            # 전체 (화면은 SDL dummy 드라이버)
.venv\Scripts\python -m pytest -m e2e -q     # 실제 서버 왕복만
```

- E2E(`tests/test_e2e.py`)는 서버 venv 로 `tests/e2e/server_harness.py` 를 띄워 페어링 → 번들 → 합성 → 업로드 →
  참가자 페이지 → 폐기까지 확인한다. 서버 venv 가 먼저 있어야 한다:
  `cd server; py -3.11 -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements.txt`.
  다른 python 을 쓰려면 환경 변수 `WALNUT_SERVER_PYTHON`. 서버 python 이 없으면 건너뛴다.
- 자동 테스트는 카메라를 쓰지 않는다. 행사 전에 실제 웹캠으로 한 번 확인한다:
  `--list-cameras` 로 번호를 확인해 `.env` 에 넣고 `main.py --windowed` 로 미리보기·얼굴 스티커·거울 방향·촬영·QR 까지 한 바퀴.
  리모컨은 `tools/remote_demo.py` 로 따로 확인할 수 있다 (배선 · 펌웨어 업로드는 `controller/README.md`).
  행사 전 전체 점검은 `docs/rehearsal-checklist.md`.
