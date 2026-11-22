#!/usr/bin/env node
// 기준 시안(mockups/)에 토큰 밖의 색 · 크기 값이 직접 적혀 있지 않은지 검사한다 (스펙 1.3-1, 4.1).
//
//   node shared/booth-design/tools/check-mockups.mjs              # mockups/ 검사 — 하나라도 있으면 종료 코드 1
//   node shared/booth-design/tools/check-mockups.mjs <폴더>       # 다른 폴더 검사 (예: booth-web/src — 웹 부스 화면)
//   node shared/booth-design/tools/check-mockups.mjs --self-test  # 검사기 자체 확인
//
// 대상: .html · .css · .js · .ts · .tsx (주석 포함 — 주석에도 값을 적지 않는다. '1920 단위' 처럼 단위 없이 쓴다).
// 폴더를 주면 그 폴더를 같은 규칙(같은 예외 폴더 · 예외 파일)으로 검사한다. 기본은 mockups/.
// 찾는 것:
//   - 16진 색 `#rgb` ~ `#rrggbbaa`
//   - 색 함수 rgb( rgba( hsl( hsla( hwb( lab( lch( oklab( oklch( color(
//   - CSS 이름 색 (white, black, red …) — 색 속성 값 자리(`color:` `background:` `border:` …)에 올 때만
//   - 절대 길이 `<숫자>px` (pt · pc · cm · mm · in · Q 도 같이)
//
// 허용 (근거를 같이 적는다):
//   - `samples/` · `fonts/` 폴더: 샘플 이미지 · 글꼴 파일과 그 메타데이터. 디자인 값이 아니다.
//   - `presets.js`: 행사 색 프리셋. 번들에서 오는 '행사 입력 데이터'(primary · accent · bg_top · bg_bottom)를
//     흉내 낸 것이지 디자인 값이 아니다 — 이 파일 하나만 색 검사에서 빼고, 크기 검사는 그대로 한다.
//   - 시험 파일(`*.test.ts` · `*.test.tsx` …): 시험 입력(픽셀 · 색 기대값)이지 화면 값이 아니다 (웹 부스 src/ 에만 있다).
//   - 웹 부스(booth-web/src) 의 두 파일 — 검사 폴더 기준 상대 경로라 mockups/ 검사에는 걸리지 않는다:
//     `engine/settings.ts` 는 색만 뺀다 — 번들 행사 색의 기본값(파이썬 settings.py 와 같은 입력 데이터, presets.js 와 같은 이유).
//     `platform/web/camera.ts` 는 길이만 뺀다 — 화면에 보이지 않게 문서에 붙이는 영상 요소의 1 픽셀 크기 (iOS 가 0 크기 영상을 멈춘다).
//   - `calc()` 안의 `0px` (예: `calc(0px + var(--space-1))`). 그 밖의 0 은 단위 없이 `0` 으로 쓴다.
//   - 단위 없는 숫자는 잡지 않는다: `calc(var(--space-2) * 2)` 의 배수, JS 의 배치 계산(토큰 값 · 1920 단위 기준폭),
//     `opacity: 0`, `scale(.9)` 같은 비율. 길이는 토큰 변수나 토큰에서 읽은 숫자에 단위를 붙여(`${n}px`) 만든다 —
//     이렇게 붙이는 `px` 앞에는 숫자 글자가 없으므로 걸리지 않는다.
//   - `var(--x, 12px)` 같은 대체값은 허용하지 않는다 (토큰 밖 값이 숨어드는 구멍이 된다).

import { readdirSync, readFileSync, statSync, existsSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative, dirname, extname, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = join(HERE, "..", "mockups");
const EXTS = new Set([".html", ".css", ".js", ".ts", ".tsx"]);
const SKIP_DIRS = new Set(["samples", "fonts"]);
const TEST_FILE = /\.test\.[cm]?[jt]sx?$/;
// 검사 폴더 기준 상대 경로 → 빼는 검사 (근거는 머리 주석)
const EXEMPT_FILES = {
  "presets.js": { color: true },
  "engine/settings.ts": { color: true },
  "platform/web/camera.ts": { length: true },
};

const NAMED_COLORS = [
  "white", "black", "red", "green", "blue", "yellow", "orange", "purple", "pink", "gray", "grey",
  "silver", "navy", "teal", "maroon", "olive", "lime", "aqua", "fuchsia", "brown", "gold", "ivory",
  "beige", "coral", "salmon", "crimson", "indigo", "violet", "tomato", "khaki", "lavender", "cyan", "magenta",
];

const RULES = [
  { name: "16진 색", color: true, re: /#[0-9a-fA-F]{3,8}\b/g },
  { name: "색 함수", color: true, re: /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/g },
  {
    name: "이름 색",
    color: true,
    re: new RegExp(
      String.raw`(?:color|background|border|outline|fill|stroke|shadow|caret|accent)[\w-]*\s*:[^;{}"'\n]*?\b(?:` +
        NAMED_COLORS.join("|") + String.raw`)\b`,
      "gi",
    ),
  },
  { name: "절대 길이", color: false, re: /(?<![\w.-])(\d*\.?\d+)(?:px|pt|pc|cm|mm|in|Q)\b/g },
];

/** 줄에서 위치 i 가 아직 닫히지 않은 calc( 안에 있는지. */
function insideCalc(line, i) {
  const before = line.slice(0, i);
  let depth = 0;
  let calcDepth = -1;
  const re = /calc\(|\(|\)/g;
  let m;
  while ((m = re.exec(before))) {
    if (m[0] === "calc(") {
      depth += 1;
      if (calcDepth < 0) calcDepth = depth;
    } else if (m[0] === "(") depth += 1;
    else {
      if (depth === calcDepth) calcDepth = -1;
      depth -= 1;
    }
  }
  return calcDepth > 0;
}

/** 텍스트 한 덩어리에서 위반을 찾는다. → [{line, rule, text}] */
export function scanText(text, { colorExempt = false, lengthExempt = false } = {}) {
  const found = [];
  text.split(/\r?\n/).forEach((line, idx) => {
    for (const rule of RULES) {
      if (rule.color && colorExempt) continue;
      if (!rule.color && lengthExempt) continue;
      rule.re.lastIndex = 0;
      let m;
      while ((m = rule.re.exec(line))) {
        if (rule.name === "절대 길이" && Number(m[1]) === 0 && insideCalc(line, m.index)) continue;
        found.push({ line: idx + 1, rule: rule.name, text: m[0] });
      }
    }
  });
  return found;
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (!SKIP_DIRS.has(name)) walk(p, out);
    } else if (EXTS.has(extname(name)) && !TEST_FILE.test(name)) out.push(p);
  }
  return out;
}

export function checkDir(root) {
  if (!existsSync(root)) return [];
  const results = [];
  for (const file of walk(root)) {
    const rel = relative(root, file).split(sep).join("/");
    const ex = EXEMPT_FILES[rel] ?? {};
    for (const f of scanText(readFileSync(file, "utf8"), { colorExempt: !!ex.color, lengthExempt: !!ex.length })) {
      results.push({ file: rel, ...f });
    }
  }
  return results;
}

function selfTest() {
  // [입력, 걸려야 하는 개수, 설명]
  const cases = [
    ["color: #1b2550;", 1, "16진 색"],
    ["background: #fff", 1, "짧은 16진 색"],
    ["box-shadow: 0 2px 6px rgba(0,0,0,.2)", 3, "px 두 개 + rgba"],
    ["color: hsl(10 20% 30%)", 1, "hsl"],
    ["border: 2px solid white", 2, "px + 이름 색"],
    ["width: 1240px;", 1, "절대 길이"],
    ["el.style.left = '18px'", 1, "JS 문자열 속 px"],
    ["margin: .5px", 1, "소수 px"],
    ["top: 1cm", 1, "다른 절대 단위"],
    ["width: var(--x, 12px)", 1, "var 대체값은 허용하지 않는다"],
    ["padding: 0px", 1, "calc 밖 0px"],
    ["width: calc(0px + var(--space-1))", 0, "calc 안 0px 허용"],
    ["width: calc(var(--space-2) * 2)", 0, "토큰 배수"],
    ["el.style.width = `${w}px`", 0, "토큰에서 읽은 숫자에 단위 붙이기"],
    ["color: var(--role-title); opacity: 0;", 0, "역할 변수"],
    ["#stage .print { transform: scale(.9) }", 0, "id 선택자 · 비율"],
    ["// 1920 단위 기준", 0, "단위 없는 주석"],
    ["<div class=\"white-space\">", 0, "속성 값 자리가 아닌 이름"],
    ["--space-0: 8px", 1, "토큰 정의도 시안 안에서는 금지"],
  ];
  let ok = true;
  for (const [src, want, why] of cases) {
    const got = scanText(src).length;
    const pass = got === want;
    if (!pass) ok = false;
    console.log(`${pass ? "통과" : "실패"}  ${why}: 기대 ${want} · 결과 ${got}  | ${src}`);
  }
  const exempt = scanText("primary: \"#1b2550\", width: 4px", { colorExempt: true }).length;
  const exemptPass = exempt === 1;
  if (!exemptPass) ok = false;
  console.log(`${exemptPass ? "통과" : "실패"}  presets.js 는 색만 빼고 크기는 검사: 기대 1 · 결과 ${exempt}`);
  if (!dirTest()) ok = false;
  console.log(ok ? "자체 확인 통과" : "자체 확인 실패");
  return ok;
}

/** 폴더 인자 — 임시 폴더를 만들어 checkDir 이 같은 규칙(확장자 · 예외 폴더 · 시험 파일 · 예외 파일)으로 도는지 본다. */
function dirTest() {
  const dir = mkdtempSync(join(tmpdir(), "check-mockups-"));
  try {
    const put = (rel, body) => {
      mkdirSync(dirname(join(dir, rel)), { recursive: true });
      writeFileSync(join(dir, rel), body);
    };
    put("ui/Stage.tsx", "const s = { width: '12px' };");      // 걸린다 (tsx)
    put("ui/motion.ts", "el.style.color = '#fff';");           // 걸린다 (ts)
    put("ui/ui.css", ".x { width: var(--space-1); }");         // 통과
    put("ui/Stage.test.tsx", "expect(w).toBe('1920px');");     // 시험 파일은 뺀다
    put("samples/a.css", ".x { width: 4px; }");                // 예외 폴더
    put("engine/settings.ts", "primary: '#1b2550', w: '2px'"); // 색만 빼고 길이는 걸린다
    put("platform/web/camera.ts", "width: '1px', color: '#000'"); // 길이만 빼고 색은 걸린다
    put("README.md", "width: 10px");                           // 대상 확장자가 아니다
    const found = checkDir(dir);
    const files = found.map((f) => f.file).sort();
    const want = ["engine/settings.ts", "platform/web/camera.ts", "ui/Stage.tsx", "ui/motion.ts"];
    const pass = JSON.stringify(files) === JSON.stringify(want);
    console.log(`${pass ? "통과" : "실패"}  폴더 인자: 기대 ${want.join(", ")} · 결과 ${files.join(", ")}`);
    return pass;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const args = process.argv.slice(2);
if (args.includes("--self-test")) {
  process.exit(selfTest() ? 0 : 1);
}
const root = args[0] ? args[0] : DEFAULT_ROOT;
const found = checkDir(root);
for (const f of found) console.log(`${f.file}:${f.line}  [${f.rule}]  ${f.text}`);
if (found.length) {
  console.log(`\n직접 적은 값 ${found.length}개 — 토큰 변수(var(--…))나 토큰에서 읽은 값으로 바꿔 주세요.`);
  process.exit(1);
}
console.log(existsSync(root) ? "시안 검사 통과" : "시안 폴더가 아직 없습니다 — 통과");
