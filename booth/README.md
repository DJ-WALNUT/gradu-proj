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

설치 파일이 하는 일: Python 3.11 확인 · 설치 → 부스 앱 zip 받아 풀기 → 가상환경 · 의존성 → 얼굴 · 사람 찾기 모델 →
`.env`(없을 때만, 서버 주소가 채워져 있다) → 바탕화면 아이콘 → 실행. 그다음 관리자 웹에서 받은 페어링 코드를 넣는다.

- **업데이트**: 바탕화면의 '호두네사진관 업데이트' (= 설치 파일을 다시 실행). 코드만 바꾸고 `data/`(사진 · 번들) · `.env` · `.venv` · `models/` 는 그대로 둔다. 중간에 끊겨도 다시 실행하면 이어서 된다.
- **새 Windows PC**: 설치 파일은 Visual C++ 런타임을 깔지 않는다. 설치 뒤 스티커 · 베스트 컷이 꺼져 있고 로그에 `DLL load failed` 가 있으면 아래 'Visual C++ 런타임'.
- **Mac 카메라 권한**: 첫 촬영 때 '터미널이 카메라에 접근' 을 [허용]. 놓쳤으면 시스템 설정 → 개인정보 보호 및 보안 → 카메라 에서 터미널을 켠다.
- 설치 파일 · zip 은 관리자 웹과 함께 Cloudflare Pages 가 `main` 푸시마다 만든다 (`admin/pages/package-booth.mjs`). 누구나 받을 수 있다 — 페어링 코드 없이는 쓸 수 없는 프로그램이다.
- 버전: zip 의 `VERSION`(예: `0.1.0+a1b2c3d` = 앱 버전 + 커밋)이 서버에 알리는 앱 버전이 된다 → 관리자 웹 부스 목록에서 부스별 버전을 본다.
- 설치 스크립트 시험용 환경 변수: `WALNUTSTUDIO_DIR`(설치 위치), `WALNUTSTUDIO_ZIP`(zip 주소나 로컬 경로), `WALNUTSTUDIO_BASE`, `WALNUTSTUDIO_NO_SHORTCUT=1`, `WALNUTSTUDIO_NO_LAUNCH=1`.

## 개발 PC 에서 실행

저장소에서 바로 돌릴 때는 아래 '의존성 설치' 를 한 번 하고 `run.bat`(Windows) · `run.command`(Mac).

### 의존성 설치 (처음 한 번, 다른 PC 로 옮겼을 때)

Python 3.11 (또는 3.12) 이 필요하다 — 3.13 이상은 mediapipe 0.10.21 휠이 없다. 명령은 모두 `booth/` 에서 돌린다.

```
# Windows (PowerShell · cmd)
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python tools\download_models.py
copy .env.example .env

# Mac (zsh)
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/download_models.py
cp .env.example .env
```

1. **패키지**: `requirements.txt` 가 전부다 (pygame-ce · mediapipe · Pillow · numpy · pytest 등). 코드를 새로 받은 뒤에는 `pip install -r requirements.txt` 를 다시 돌리면 빠진 것만 깔린다.
2. **모델**: 아래 '모델 받기'. 건너뛰어도 부스를 처음 실행할 때 자동으로 받지만, 인터넷이 없는 곳에서 쓸 PC 는 미리 받아 둔다.
3. **`.env`**: `.env.example` 을 복사한 뒤 이 PC 에 맞게 고친다 (아래 '`.env`' 표). 카메라 번호는 `main.py --list-cameras` 로 확인하고,
   지능형 촬영(`BOOTH_BURST` · `BOOTH_SMART_CROP`)은 기본으로 켜져 있다 (2026-11-22부터). 끄려면 `0` 을 넣는다.
4. **(선택) 시험을 빠르게**: `pip install pytest-xdist` 를 따로 깔면 `pytest -n 8` 로 나눠 돌릴 수 있다 (`requirements.txt` 에는 없다).
5. **(선택) E2E · 리모컨**: E2E 시험은 서버 venv 가 있어야 한다 (아래 '테스트'). 리모컨 펌웨어는 `controller/README.md`.

새 Windows PC 면 이 앞에 아래 'Visual C++ 런타임' 을 먼저 설치한다 (없으면 모델을 불러오지 못한다).

설치 확인: `models/` 에 파일 두 개가 있고, `.venv\Scripts\python main.py --list-cameras` 가 카메라 목록을 보여 주면 된다.

### 모델 받기

MediaPipe 모델 두 개를 `booth/models/` 에 둔다 (git 에 올라가지 않는다 — PC 마다 받는다).

| 파일 | 크기 | 쓰는 곳 |
|---|---|---|
| `face_landmarker.task` | 약 4MB | 얼굴 — AR 스티커 · 베스트 컷(눈 뜸 · 정면) · 구도 보정 |
| `efficientdet_lite0.tflite` | 약 7MB | 사람 찾기 — 얼굴 모델이 놓친 사람을 구도에 담는다 |

**방법 1 — 스크립트 (권장)**. `booth/` 에서:

```
# Windows
.venv\Scripts\python tools\download_models.py

# Mac
.venv/bin/python tools/download_models.py
```

없거나 깨진 파일만 받는다 (이미 있으면 그냥 끝난다). 받은 파일이 모델처럼 보이지 않으면(로그인 페이지 · 끊긴 파일) 지우고 오류를 낸다.
설치 파일(`walnutstudio-setup`)과 부스 첫 실행(`main.py`)도 같은 코드(`walnut/model_files.py`)로 받는다.

**방법 2 — 직접 받기** (스크립트가 막히는 네트워크, 인터넷 없는 PC 에 USB 로 옮길 때). 아래 주소를 브라우저로 열어 받은 파일을
**이름 그대로** `booth/models/` 에 넣는다 (설치본은 `%LOCALAPPDATA%\walnutstudio\models\` · `~/walnutstudio/models/`).

- 얼굴: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
- 사람 찾기: https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/latest/efficientdet_lite0.tflite

```
# 명령으로 받을 때 (booth/ 에서, Windows 10 이상 · Mac 모두 curl 이 있다)
mkdir models
curl -L -o models/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
curl -L -o models/efficientdet_lite0.tflite https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/latest/efficientdet_lite0.tflite
```

PowerShell 에서는 `curl` 이 다른 명령이라 `curl.exe` 로 적는다. 다 받은 뒤 `tools/download_models.py` 를 한 번 돌려 아무것도 받지 않고 끝나면 파일이 멀쩡한 것이다.

모델이 없으면: 얼굴 모델이 없을 때 AR 스티커 · 베스트 컷 분석이 꺼지고, 사람 찾기 모델이 없을 때 사람 찾기만 꺼진다 (로그에 경고).
개발자 모드는 모델을 못 받으면 이유를 출력하고 끝난다.

### Visual C++ 런타임 (Windows, 새 PC)

mediapipe 는 Microsoft Visual C++ 재배포 패키지(2015-2022, x64)가 있어야 돈다. 갓 설치한 Windows 에는 없거나 옛 판일 수 있고,
그러면 **모델 파일이 멀쩡히 있어도 불러오지 못한다.** Mac 은 해당 없음.

증상 (`data/logs/` · 콘솔):

- `얼굴 인식을 켤 수 없어 스티커를 건너뜁니다: …` · `베스트 컷용 얼굴 모델을 불러오지 못했습니다: …`
- 뒤에 `DLL load failed while importing _framework_bindings` · `지정된 모듈을 찾을 수 없습니다` 같은 말이 붙는다.

**확인**. `booth/` 에서 (모델을 받은 뒤):

```
.venv\Scripts\python -c "from mediapipe.tasks.python import BaseOptions, vision; vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path='models/face_landmarker.task'))); print('OK')"
```

마지막 줄에 `OK` 가 나오면 된 것이다 (그 앞의 `WARNING` · `W0000 …` 줄은 mediapipe 가 늘 찍는 것이라 괜찮다). `DLL load failed` 면 아래로 설치한다. 설치돼 있는 판은
`Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' | Select Version` 로 본다 (없으면 설치 안 된 것).

**방법 1 — winget (권장)**. PowerShell 에서:

```
winget install -e --id Microsoft.VCRedist.2015+.x64 --accept-package-agreements --accept-source-agreements
```

관리자 권한 확인 창이 한 번 뜬다. 이미 최신이면 그냥 끝난다.

**방법 2 — 직접 받기** (winget 이 없거나, 인터넷 없는 PC 에 USB 로 옮길 때). 아래 파일을 받아 실행 → [설치]
(이미 있으면 [복구]). 조용히 설치하려면 `vc_redist.x64.exe /install /quiet /norestart`.

- https://aka.ms/vs/17/release/vc_redist.x64.exe (Microsoft 공식 최신판)

설치한 뒤 부스를 다시 실행하고 위 '확인' 명령을 한 번 더 돌린다. 그래도 `DLL load failed` 면 PC 를 다시 시작해 본다.
Python 이 64비트(설치 파일 · `py -3.11` 기본)이므로 x86 판이 아니라 **x64** 판이어야 한다.

직접 실행할 때 (Windows):

```
.venv\Scripts\python main.py                 # 전체 화면 (.env 의 BOOTH_FULLSCREEN)
.venv\Scripts\python main.py --windowed      # 창 모드 (개발용)
.venv\Scripts\python main.py --no-camera     # 카메라 없이 화면 흐름만 확인
.venv\Scripts\python main.py --list-cameras  # 연결된 카메라 번호 확인
```

- venv 를 켜 두면 그 터미널에서는 `python main.py` 로 짧게 쓸 수 있다.
- CMD : `.venv\Scripts\activate.bat`
- Powershell : `.venv\Scripts\Activate.ps1`

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

## 개발자 모드 (연결 코드 없이 버스트샷 · 구도 보정 보기)

연결 코드 · 서버 없이 바로 촬영해 보는 모드다. 기본 번들(기본 설정 + 기본 4컷 프레임)로 대기 화면에서 시작하고,
버스트샷(컷마다 셔터 앞뒤 약 1초의 연속 프레임에서 가장 좋은 한 장을 고르는 기능)과
구도 보정(아래)이 켜진다 (`.env` 의 `BOOTH_BURST` · `BOOTH_SMART_CROP` 과 상관없이).

**구도 보정 (`BOOTH_SMART_CROP=1`)** — 아이폰 센터 스테이지처럼 동작한다. 결과 사진에만 적용하고, 촬영 중 미리보기는
**기본 구도(가운데를 1.3배 확대한 화면)** 로 고정해 보여 준다 (실시간 추적 아님).
합성할 때 슬롯마다: 사람이 칸 가운데 근처(데드존 `HOME_DEADBAND`)면 기본 구도 그대로(`home`), 가운데를 벗어나면
같은 1.3배로 따라가 칸 가운데로 옮기고(`follow`, 화면 끝이면 갈 수 있는 데까지), 좌우로 퍼져 기본 구도 밖으로 나가면
확대를 풀어 모두 담는다(`widen`). 얼굴 하나가 작으면 더 확대하기도 한다(`zoomed`).
가장 큰 얼굴의 40% 보다 작은 얼굴(뒤쪽 행인)은 빼고, 남은 얼굴이 4명(검출 한도) 이상이면 가장 넓게 (행인은 이 수에도 세지 않는다).
기본보다 더 확대하는 것은 얼굴 전체가 기본 구도의 25%(`FAR_FILL`, 1080p 에서 얼굴 너비 약 0.08 이하)보다 작을 때다 —
2026-11-21 행사(광각)에서 0.17 로는 손님 대부분이 1.3배에 머물러 작게 보여 올렸다.
프레임 장식에 얼굴이 가리지 않게 하는 것은 사람을 다 담는 것보다 가볍게 본다.
얼굴을 못 찾았거나 분석이 실패하면 **가장 넓게(1.0배 가운데)** — 사람이 어디 있는지 모르니 1.3배로 자르지 않는다.
**사람 찾기**: 손으로 입을 가리거나 옆모습 · 멀리 서서 얼굴 모델이 놓친 사람은, 고른 컷 한 장에서 사람 검출기(EfficientDet-Lite0)로
찾은 사람 박스에서 머리 자리를 추정해 구도에 담는다 (얼굴이 없으면 그 머리로, 얼굴이 있어도 얼굴 박스가 없는 사람은 더한다 —
`walnut/analysis.py` `HEAD_W_RATIO` · `HEAD_ASPECT` · `HEAD_TOP_PAD`). 고르기 · 점수에는 쓰지 않는다. 모델이 없으면 이것만 꺼진다.
버스트 후보 여럿 중 일부(60% 미만)에서만 잡힌 얼굴은 고르기의 얼굴 수에서만 빼고(`walnut/analysis.py` `STABLE_RATIO`),
구도에는 고른 컷에 잡힌 얼굴을 모두 담는다 — 가짜 얼굴이면 사진이 조금 넓어지지만 자꾸 놓치는 진짜 사람은 잘리지 않는다.
고른 컷에 얼굴이 없고 다른 후보에 있으면 가장 가까운 후보의 얼굴로 구도를 잡는다. 현장 기록 `cut` 줄의
`unstable_faces`(고르기에서 뺀 얼굴 수) · `faces_unstable`(구도 얼굴 중 꾸준하지 않은 번호) · `faces_from`(빌려 온 후보 번호) ·
`person_heads`(사람 찾기로 더한 머리 수, `faces` 끝에 붙는다) · `person_ms`(사람 찾기 시간, 돌지 않았으면 null)로 확인한다. 상수는 `walnut/framing.py` 맨 위.

**컷마다 '찍은 그대로' · 'AI 추천' 고르기** — 버스트샷이나 구도 보정이 켜져 있으면 셔터 뒤 분석이 끝날 때 두 장을 나란히
(사진 비율에 따라 위아래로) 보여 준다: **찍은 그대로**(셔터 순간 프레임 + 미리보기에서 본 구도)와 **AI 추천**(고른 프레임 + 구도 보정).
일부러 구석에서 찍은 연출을 지키려는 것이다. 사진(또는 이름표)을 누르거나 `←`/`→` + `Enter` 로 고르고,
10초 동안 입력이 없으면(`F2` 도) AI 추천으로 넘어간다. 고른 뒤에는 '다음 포즈 준비' 없이 바로 다음 컷 카운트다운이다 (고르지 않은 컷은 지금처럼 쉬었다 간다). 두 장이 같거나(같은 프레임 · 같은 구도) 분석이 실패 · 시간 초과면
고르지 않는다. 다시 찍은 컷도 다시 묻는다. `--dev-mode-all` 이면 분석 화면 다음에 뜬다.
더 찍고 고르기(`extra_shots` > 0) 촬영도 사진마다 묻는다. 슬롯이 아직 정해지지 않았으므로 두 장은 **대표 슬롯**(미리보기 비율과 같은 비율의 첫 슬롯, 없으면 첫 슬롯)
모양으로 보이고, 미리보기 배율이 대표 슬롯의 기본 배율보다 작으면(더 큰 슬롯이 있을 때) 찍은 그대로는 미리보기에서 본 화면 그대로 보인다.
고른 결과는 사진에 붙어 있다가 고르기 화면에서 고른 순서대로 컷이 될 때 함께 따라간다. 고르기 화면 축소판도 사진마다 고른 쪽의 크롭(대표 슬롯 모양)으로 보인다.
'찍은 그대로' 컷은 합성 · 축소판에서 얼굴과 상관없이 기본 구도로 자른다 (crop 줄 reason `as_shot`). 리모컨 화면은 고르기 전용 `A` 줄(커서 · 남은 0.1초 · 전체)로 `그대로` / `AI 추천` 두 칸을 그린다.
현장 기록 `cut` 줄에 `choice`(`ai` · `as_shot` · `timeout_ai` · `skipped`) · `choice_ms` 가 남고,
`tools/analyze_field_log.py` 가 **AI 채택률**(고르기가 있었던 컷 중 AI 추천 · 시간 초과 비율, 손님이 직접 고른 컷 중 AI 추천 비율)을 보인다.
더 찍고 고르기 촬영은 `cut` 줄이 사진마다 하나라서, AI 채택률은 손님이 최종으로 고르지 않은 사진까지 포함해 사진 단위로 센다.

| 인자 | 동작 |
|---|---|
| `--dev-mode` | 버스트샷 · 구도 보정이 들어간 부스를 평소처럼 써 본다 |
| `--dev-mode-all` | 위에 더해, 컷마다 **베스트 컷 분석 화면**으로 고르는 과정을 보여 준다 |

준비 (처음 한 번, `booth/` 폴더에서. Python 3.11 또는 3.12):

```
# Windows (PowerShell · cmd)
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python tools\download_models.py

# Mac (zsh)
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/download_models.py
```

모델을 직접 받는 방법은 위 '모델 받기'.

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
- **첫 실행에는 인터넷이 필요하다.** 모델 두 개(얼굴 `models/face_landmarker.task` · 사람 찾기 `models/efficientdet_lite0.tflite`,
  모두 약 11MB)가 없으면 자동으로 내려받는다 (미리 받거나 직접 받으려면 위 '모델 받기').
  못 받으면 이유를 출력하고 끝난다 (모델 없이 버스트샷이 꺼진 채 도는 일을 막는다).
- `.env` 가 없어도 된다. 카메라 번호가 0번이 아니면 `--list-cameras` 로 확인해 `.env` 에 `CAMERA_INDEX` 를 적는다.
- 카운트다운은 4초. 사진 · 기록은 `booth/data-dev/` 에만 남는다 (실제 `data/` 의 페어링 · 사진은 건드리지 않고, 서버로 아무것도 보내지 않는다).
- 조작: `Enter` 시작 · 선택, `F2` 건너뛰기, `F5` 처음 화면, `ESC` 패널 → `Q` 두 번이면 종료.

베스트 컷 분석 화면 읽는 법 (`--dev-mode-all`):

- 윗줄: 셔터 -0.7초 ~ +0.3초 사이의 후보 전부 (0.08초 간격, 보통 10~13장). 아래 숫자는 셔터 기준 시각과 종합 점수.
  흐려진 컷은 탈락이고 사유가 적힌다 — `흔들림`(선명도 부족) · `눈 감음` · `얼굴 수 부족`.
- 가운데: **카운트다운 순간**(버스트샷이 없었다면 찍혔을 컷)과 **베스트 컷**(실제로 쓴 컷), 그리고 각각의 선명도 · 눈 뜸 · 정면 · 점수.
- 아래: 고른 이유 한 줄. `Enter` 로 다음 컷, 20초 동안 입력이 없으면 자동으로 넘어간다.
  모든 후보가 눈 감음으로 탈락하면 셔터에 가까운 컷이 아니라 눈을 가장 크게 뜬 컷을 고른다.
  사람 찾기로 머리를 더했으면 맨 아래 줄 앞에 `사람 위치로 구도를 잡았어요 (머리 N)` 이 붙는다.
- 썸네일은 필터 · 스티커를 입히지 않은 원본이다 (비교가 목적).

## `.env` (이 기기에만 해당하는 값)

| 키 | 기본값 | 뜻 |
|---|---|---|
| `SERVER_URL` | (없음) | 서버 주소, 끝 `/` 없이. 비우면 페어링 화면에 안내만 뜬다 |
| `CAMERA_INDEX` | `0` | 카메라 번호 (`--list-cameras` 로 확인) |
| `CAMERA_WIDTH` · `CAMERA_HEIGHT` | `1920` · `1080` | 카메라 해상도 |
| `REMOTE_PORT` | (빈 값) | 리모컨 시리얼 포트. 빈 값 = 자동 탐색, `off` = 끔, `COM3` 처럼 직접 지정 |
| `PRINTER_PORT` | (빈 값) | 영수증 프린터(CPP-3000) 포트. 빈 값 = USB 번호(1CBE:0002)로 자동 탐색 — 노트북마다 COM 번호가 달라도 설정이 필요 없다, `off` = 인쇄 끔, `COM5` 처럼 직접 지정, `dummy` = `data/print_spool/` 에 PNG 로만 저장(개발용). 아래 '영수증 프린터' |
| `BOOTH_FULLSCREEN` | `true` | 전체 화면 |
| `SYNC_INTERVAL` | (빈 값) | 동기화 주기(초). 있으면 번들 값보다 우선 |
| `BOOTH_BURST` | `1` | 버스트 베스트 컷 — 셔터 앞뒤 후보 가운데 눈 감음 · 흔들림이 없는 컷을 고른다 |
| `BOOTH_SMART_CROP` | `1` | 구도 보정 (위 '개발자 모드' 의 설명). `BOOTH_BURST` 와 함께 쓴다 (구도 보정만 켠 조합은 확인 전) |
| `BOOTH_CAPTURE_LOG` | `0` | 촬영 기록(수치만, 이미지 없음)을 `data/logs/capture_metrics.jsonl` 에 남긴다 — 아래 '현장 시험' |
| `BOOTH_FIELD_SAMPLES` · `BOOTH_FIELD_CONSENT` | `0` · (빈 값) | 둘 다 있어야 샘플 모드 (버스트 후보 원본 저장). **동의한 지인 시험만, 행사에서는 쓰지 않는다** |

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

- 기본 번들 = 기본 설정값 + 프레임. 프레임은 **시험용 프레임 폴더 `booth/assets/frame/` 의 PNG 전부**이고 (`--dev-mode` 도 같다),
  폴더가 없거나 쓸 PNG 가 없으면 기본 프레임 하나 (4컷 2×2, 원본 `shared/booth-design/default-frame/`).
  - 슬롯은 PNG 의 투명 구멍(알파 128 미만, 그림의 1% 이상)에서 찾는다. 구멍의 경계 상자가 슬롯이고, 위 줄 왼쪽부터 1컷, 2컷 … 이다.
  - 구멍으로 안 맞으면 같은 이름의 `.json` 에 `{"slots": [...]}` (형식은 `walnut/default_frame/frame.json`) 를 두면 그것을 쓴다.
  - 프레임 이름은 파일 이름이다. 프레임이 여럿이면 촬영 전에 고르는 화면이 나온다.
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
| `F9` | 지금(또는 방금 끝난) 촬영에 문제 표시 — 촬영 기록에 `mark` 줄, 화면 아래에 잠깐 알림. 손님 화면은 그대로 |
| 패널 안에서 `Q` 두 번 (3초 안) | 앱 종료 |

- 관리자 PIN 은 관리자 웹 → 행사 → **부스** 탭 → "동기화·관리자 PIN" 에서 보고 바꾼다. 바꾼 뒤 **게시**해야 부스에 반영된다.
  5번 틀리면 60초 잠긴다.
- 패널: 상태(서버 연결·번들 버전·대기 사진 수) + [지금 동기화] [번들 파일 가져오기] [연결 해제(재페어링)].
  연결 해제는 한 번 더 눌러야 실행된다.
- 페어링은 됐지만 번들을 아직 못 받은 상태(PIN 없음)에서는 ESC 가 PIN 없이 [번들 파일 가져오기] 만 있는 패널을 연다.
  페어링 전에는 종료 안내만 나온다.

## 영수증 프린터 (CPP-3000)

80mm 감열 · 가로 576점. USB 가상 시리얼로 ESC/POS 를 직접 보내므로 **드라이버 설치가 필요 없다**.
공유 화면 다음의 매수 고르기에서 [인쇄] 하면 장마다 사진(흑백 점묘) + QR(컬러 원본) · 호두네사진관 · 날짜 한 장을 뽑고 자른다.
인쇄는 뒤에서 순서대로 보내므로 화면은 기다리지 않는다. 실패하면 로그(`[printer] 인쇄하지 못했습니다`)만 남고 부스는 계속 돈다.

- **포트**: `.env` 의 `PRINTER_PORT` 를 비워 두면 USB 번호(1CBE:0002)로 스스로 찾는다 — 다른 노트북에 꽂아도 그대로 된다.
  안 잡히면 장치 관리자 "포트(COM & LPT)" 의 번호를 `PRINTER_PORT=COM5` 처럼 적는다. 장마다 다시 찾으므로 켠 뒤에 꽂아도 된다.
- **프린터를 못 찾으면** 매수 고르기 화면을 건너뛴다 (인쇄 없이 대기 화면).
  `COM5` 처럼 직접 적은 포트도 지금 꽂혀 있을 때만 쓴다 (안 꽂혀 있으면 패널에 `연결 안 됨`).
- **사진 밝기**: `walnut/printer.py` 맨 위 `PHOTO_GAMMA`(작을수록 중간 톤이 밝게) · `PHOTO_BRIGHTNESS` · `PHOTO_CONTRAST`. 고르기는
  `.\.venv\Scripts\python tools\print_tune.py` — 가장 최근 합성 사진을 다섯 가지 값으로 한 장에 띠로 뽑는다 (`--set 0.6,1.15,1.0` 로 값 지정, `--preview out.png` 는 인쇄 없이).
- **인쇄 도중에 부스를 끄거나 용지가 걸리면** 다음 장이 깨져 나올 수 있다 — 프린터 전원을 껐다 켜고 [시험 인쇄] 로 확인한다.
- **행사 전 확인**: ① 관리자 웹 행사 → '공유' 탭에서 인쇄 켜기 · 최대 매수 → ② 부스 관리자 패널(ESC) '지금 동기화'
  → ③ 패널 상태 줄 `프린터  COM? 연결됨` 확인 → ④ [시험 인쇄] — 회색 띠가 고르게 나오면 정상.

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

## 현장 시험 (기록 · 내보내기 · 분석)

지인 시험 · 행사에서 돌린 기록을 첨부해 알고리즘을 고칠 때 쓴다. 기록은 세 단계다.

| 단계 | 켜는 법 | 남는 것 | 쓰는 곳 |
|---|---|---|---|
| 1 진단 로그 | 항상 | `data/logs/booth-YYYY-MM-DD.log` (오류 · 경고 · 흐름, 파일당 5MB, 14일 보관) | 어디서나 |
| 2 촬영 기록 | `BOOTH_CAPTURE_LOG=1` | `data/logs/capture_metrics.jsonl` — 수치만, 이미지 없음 | 행사 포함 어디서나 |
| 3 샘플 | `BOOTH_FIELD_SAMPLES=1` + `BOOTH_FIELD_CONSENT=<테스트 이름>` | `eval_data/field_<날짜>_<테스트 이름>/` 에 버스트 후보 원본 시퀀스 | 동의한 지인 시험만. **행사는 2단계까지** |

촬영 기록은 한 줄에 하나씩 `type` 으로 나뉜다: `session`(촬영 시작 — 앱 판 · 플래그 · 평가 상수 · 카메라 · 행사 · 프레임),
`cut`(컷마다 후보별 수치 · 고른 번호 · reason · 지연), `crop`(슬롯마다 크롭), `result`(완료 — 재촬영 횟수 · 합성 시간 · 합성본 해시),
`mark`(F9). 모든 줄에 `shoot_id`(손님 촬영 하나의 무작위 id)와 기록 시각 `at` 이 있다. QR 토큰 · 합성본 파일 이름은 남기지 않는다.
예전 `baseline` 줄(합성 시간)은 분석 도구가 합성 지연으로 바꿔 센다.

1. **켜기**: `booth/.env` 에 `BOOTH_CAPTURE_LOG=1` 을 넣는다 (버스트 · 구도 보정은 기본으로 켜져 있다).
   동의를 받은 지인 시험이면 `BOOTH_FIELD_SAMPLES=1` 과 `BOOTH_FIELD_CONSENT=지인테스트` 처럼 테스트 이름도 넣는다.
   샘플 모드면 대기 화면 맨 위에 "테스트 촬영 중 — 사진이 분석용으로 저장됩니다" 가 작게 뜨고, 관리자 패널 상태에 저장한 개수가 보인다
   (2GB 를 넘으면 저장을 멈추고, 저장이 밀리면 그 컷은 버린다 — 촬영은 기다리지 않는다).
2. **촬영**: 평소처럼 찍는다.
3. **문제가 있으면 `F9`**: 그 촬영(대기 화면이면 방금 끝난 촬영)에 표시가 남는다. 어떤 문제였는지는 따로 메모해 둔다.
4. **내보내기**: 부스를 끈 뒤 (기본은 사진 없이 기록만)
   ```powershell
   .\.venv\Scripts\python tools\export_field_log.py --since 2026-11-20 --out field.zip
   # 합성본(이름은 shoot_id 로 바뀜) · 샘플까지:  --with-collage --with-samples
   # 개발자 모드로 찍었으면:  --data data-dev
   ```
   요약 보기: `.\.venv\Scripts\python tools\analyze_field_log.py field.zip` (촬영 수 · reason 분포 · 폴백률 · 단계별 평균/95% 지연 · AI 채택률 · 사람 찾기로 구도를 잡은 · 머리를 더한 컷 수 · 표시한 촬영).
   샘플은 `tools\compare_best.py --root eval_data\field_<날짜>_<테스트 이름>` 으로 그대로 다시 돌려 볼 수 있다.
   얼굴 검출 전략 비교 (광각 · 단체에서 얼굴을 놓칠 때): 녹화(`tools\record_burst.py`)나 샘플 폴더를
   `.\.venv\Scripts\python tools\compare_detect.py --root eval_data\field_<날짜>_<테스트 이름>` 으로 돌리면
   전략(`full` 전체 한 번 · `halves` 겹치는 좌우 반쪽 · `full+halves` 둘 다)별로 시퀀스마다 · 전체로
   '얼굴 찾음 %'(얼굴을 하나 이상 찾은 프레임 비율) · '평균 얼굴'(프레임당 얼굴 수) · 프레임당 분석 ms(평균 · 최대)를 찍고
   `<root>\compare_detect.csv` 에 쓴다. 찾음 % 와 평균 얼굴이 실제 인원에 가깝고 ms 가 감당할 만한 전략을
   `walnut/analysis.py` 의 `DETECT_MODE` 로 고른다 (기본 `full+halves`, cut 줄의 `detect_mode` 에 남는다).
   `--debug-dir <폴더>` 를 주면 프레임마다 전략별 얼굴 박스를 그린 JPEG 를 쓴다 — **원본 얼굴 사진이므로 확인 뒤 바로 지우고,
   저장소에 넣거나 밖으로 보내지 않는다** (기본은 끔).
   **4조건 비교 (보고서 수치)**: `.\.venv\Scripts\python tools\eval_capture.py [--root eval_data] [--frame assets\frame\sticker_party.png] [--seed 1]`
   은 `eval_data\*` · `eval_data\field_*\*` 시퀀스를 baseline(셔터 프레임 + 가운데 크롭) · A(베스트 컷 + 가운데) ·
   B(셔터 프레임 + 센터 스테이지 구도) · AB(둘 다)로 돌려 `eval_data\_eval\` 에 `results.csv`(시퀀스 × 조건 × 슬롯) ·
   `summary.csv`(조건별 all_in 비율 · 잘림 · 장식 가림 · 얼굴 채움 · 눈 뜸 · ms · 표본 수 · 실패 수)를 쓴다. 지표 정의는 도구 맨 위 설명.
   summary 는 시퀀스마다 슬롯 평균을 먼저 내고 시퀀스끼리 평균한다 (표본 수 n = 시퀀스 수 — 슬롯끼리는 같은 컷이라 표본으로 세지 않는다).
   부스처럼 시퀀스 `meta.json` 의 `mirror`(없으면 켬)를 따라 컷과 얼굴 박스를 좌우로 뒤집은 뒤 크롭한다.
   **보고서에 쓸 때 주의**: all_in · face_cut · occluded 는 검출기 박스 기준이라 B · AB 에게는 자기 채점이다 (같은 박스로 크롭을 고르고,
   occluded 는 구도 비용 항목 그대로). 검출기가 놓친 얼굴은 어느 조건에서도 안 보이고, `*_all` 이 아닌 열은 뒤쪽 작은 얼굴(가장 큰 얼굴 높이 40% 미만)을 뺀다
   (`all_in_all` · `face_cut_max_all` 은 검출한 얼굴 전부 기준). 독립 확인은 사람 평가의 '잘림' · '구도선호' 다.
   face_fill 은 얼굴 합집합 박스의 가로 · 세로 중 큰 쪽 비율(넓이 아님)이고, B · AB 는 기본 구도가 1.3배라 설계상 약 1.3배 크게 나온다.
   ms 는 계산 비용만이다 — 셔터 뒤 수집(약 0.3초) · 장식 격자 · 모델 불러오기가 빠진, 손님이 기다리는 전체 지연이 아닌 값.
   가린 비교 시트 `_eval\blind\<시퀀스>.jpg` (조건 이름 없이 1~4 번호) 와 답안 `blind_key.csv` 도 만든다 — 평가자가
   `eval_data\labels.csv` (열 `시퀀스,번호,눈감음,흐림,잘림,구도선호`, 빈칸 허용)를 채운 뒤 다시 돌리면 조건별 평균이 `summary.csv` 에 합쳐진다.
   **평가자에게는 `blind\` 폴더만 준다 — `blind_key.csv` 는 절대 주지 않는다** (답안을 보면 가린 평가가 아니게 된다).
   답안이 이미 있으면 번호를 그대로 두므로 평가가 어긋나지 않는다 (새로 섞기 `--reshuffle`). `--debug` 는 얼굴 박스 · 크롭을 그린 그림.
   시트 · 디버그 그림 모두 **원본 얼굴 사진이므로 평가 뒤 지운다.**
5. **zip 첨부**: 도구는 아무것도 업로드하지 않는다. 만든 zip 을 직접 첨부한다.
6. **삭제**: 보낸 뒤 zip 을 지우고, 샘플을 찍었으면 `eval_data\field_<날짜>_<테스트 이름>\` 폴더를 지운다 (요청이 있으면 바로).
   `.env` 의 `BOOTH_FIELD_SAMPLES` 는 다시 `0` 으로 돌린다.

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

설치는 위 '의존성 설치' 를 따른다.

```
cd booth
.venv\Scripts\python -m pytest -q            # 전체 (화면은 SDL dummy 드라이버)
.venv\Scripts\python -m pytest -n 8 -q       # 나눠 돌리기 (pytest-xdist 를 따로 깔았을 때)
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
