// 시안 스크린샷 · 기준 비교 도구 (Task 9).
//   node shared/booth-design/tools/shoot-mockups.mjs [--out DIR] [--only 화면이름]
// 하는 일: python http.server 를 띄우고 headless Chrome 으로 시안을 찍은 뒤, 기준 PNG 와 나란히 보는 compare.html 을 만든다.
//   - 모든 화면(demo-flow 제외) × 기본 상태 × 화면비 6종
//   - 모든 화면 × 모든 상태 × 16x9 (기준과 비교)
// 브라우저는 ~/Library/Caches/ms-playwright 의 chrome-headless-shell, 없으면 환경 변수 CHROME.
// 화면 목록은 mockups/screens/index.js 를 import 해서 읽는다 (순수 데이터라 Node 에서 import 된다).
// 이 도구와 출력은 시안이 아니라 check-mockups 의 검사 대상(mockups/)이 아니다.

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, writeFileSync, copyFileSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");                       // shared/booth-design
const REPO = resolve(ROOT, "..", "..");
const BASELINE_DIR = join(REPO, "docs", "design", "booth-baseline");

// 화면비 → 창 크기 (적당히 작게)
const RATIOS = {
  "16x9": [1600, 900], "16x10": [1440, 900], "4x3": [1200, 900],
  "3x4": [675, 900], "9x16": [506, 900], "9x19.5": [415, 900],
};
const CONCURRENCY = 4;
const SKIP_RATIO_SWEEP = new Set(["demo-flow"]);        // 움직임 데모는 화면비 훑기에서 뺀다 (기본 상태 16x9 한 장만 찍는다)

// 기준 PNG ↔ 시안 (화면, 상태). 이름 규칙: 번호 접두 제거, '-' → '_', 아래는 예외 짝.
// 10-share 는 share/uploading 과 짝: share.js 머리말이 uploading 을 기준 장면으로 적어 둔다.
const BASELINE_MAP = [
  ["01-pairing", "pairing", "code"],
  ["02-dial", "dial", "pin"],
  ["03-idle", "idle", "default"],
  ["04-choose-filter", "choose", "filter"],
  ["05-choose-frame", "choose", "frame"],
  ["06-capture", "capture", "countdown"],
  ["07-pick", "pick", "picking"],
  ["08-review", "review", "default"],
  ["09-retake", "retake", "default"],
  ["10-share", "share", "uploading"],
  ["11-print-copies", "print_copies", "default"],
  ["12-admin", "admin", "panel"],
  ["12b-import", "import_zip", "list"],
  ["13-waiting", "waiting", "not-published"],
];

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

function findChrome() {
  if (process.env.CHROME) return process.env.CHROME;
  const base = join(homedir(), "Library", "Caches", "ms-playwright");
  if (existsSync(base)) {
    for (const d of readdirSync(base).filter((n) => n.startsWith("chromium_headless_shell-")).sort().reverse()) {
      for (const s of readdirSync(join(base, d)).filter((n) => n.startsWith("chrome-headless-shell-"))) {
        const p = join(base, d, s, "chrome-headless-shell");
        if (existsSync(p)) return p;
      }
    }
  }
  throw new Error("chrome-headless-shell 를 찾지 못했다. CHROME 환경 변수로 경로를 알려 주세요.");
}

function freePort() {
  return new Promise((ok, fail) => {
    const s = createServer();
    s.once("error", fail);
    s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => ok(port)); });
  });
}

async function waitServer(url) {
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(url)).ok) return; } catch { /* 아직 */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("http.server 가 뜨지 않았다");
}

const children = new Set();   // 진행 중인 chrome — 중단 때 함께 끈다
const MARKER = ".mockup-shots";   // 이 도구가 만든 출력 폴더 표시

function shoot(chrome, url, out, [w, h]) {
  return new Promise((ok) => {
    const p = spawn(chrome, ["--headless", "--no-sandbox", "--hide-scrollbars", `--screenshot=${out}`,
      `--window-size=${w},${h}`, "--virtual-time-budget=3000", url], { stdio: "ignore" });
    children.add(p);
    const t = setTimeout(() => p.kill("SIGKILL"), 60000);
    p.on("exit", (code) => { clearTimeout(t); children.delete(p); ok(code === 0 && existsSync(out)); });
  });
}

async function pool(items, n, fn) {
  let i = 0;
  await Promise.all(Array.from({ length: n }, async () => { while (i < items.length) await fn(items[i++]); }));
}

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

async function main() {
  const outDir = resolve(arg("--out") ?? join(REPO, ".superpowers", "mockup-shots"));
  const only = arg("--only");
  const { SCREENS } = await import(pathToFileURL(join(ROOT, "mockups", "screens", "index.js")).href);
  const chrome = findChrome();
  // 표시 파일이 없는 비어 있지 않은 폴더는 지우지 않는다 (--out . 같은 실수 방지)
  if (existsSync(outDir) && readdirSync(outDir).length > 0 && !existsSync(join(outDir, MARKER)) && !existsSync(join(outDir, "compare.html"))) {   // compare.html: 표시 파일 도입 전 출력
    console.error(`출력 폴더가 비어 있지 않고 이 도구가 만든 폴더도 아니라서 지우지 않는다: ${outDir}\n빈 폴더나 새 폴더를 --out 으로 주세요.`);
    process.exit(1);
  }
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(join(outDir, "baseline"), { recursive: true });
  writeFileSync(join(outDir, MARKER), "walnut mockup shots — shoot-mockups.mjs 가 지우고 다시 만드는 폴더\n");

  // 찍을 목록
  const jobs = new Map();
  const add = (screen, state, ratio) => jobs.set(`${screen}__${state}__${ratio}`, { screen, state, ratio });
  for (const s of SCREENS) {
    if (only && s.name !== only) continue;
    for (const st of s.states) add(s.name, st, "16x9");
    if (!SKIP_RATIO_SWEEP.has(s.name)) for (const r of Object.keys(RATIOS)) add(s.name, s.states[0], r);
  }

  const port = await freePort();
  const server = spawn("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1", "--directory", ROOT], { stdio: "ignore" });
  const stop = () => {
    try { server.kill(); } catch { /* 이미 끝남 */ }
    for (const c of children) { try { c.kill("SIGKILL"); } catch { /* 이미 끝남 */ } }
  };
  process.on("exit", stop);
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { stop(); process.exit(130); });

  const t0 = Date.now();
  const failed = [];
  try {
    await waitServer(`http://127.0.0.1:${port}/mockups/`);
    console.log(`찍는 중: ${jobs.size}장 (동시 ${CONCURRENCY}) → ${outDir}`);
    await pool([...jobs.entries()], CONCURRENCY, async ([key, j]) => {
      const url = `http://127.0.0.1:${port}/mockups/?screen=${j.screen}&state=${j.state}&ratio=${j.ratio}&bar=off`;
      const ok = await shoot(chrome, url, join(outDir, `${key}.png`), RATIOS[j.ratio]);
      if (!ok) failed.push(key);
    });
  } finally {
    stop();
  }

  // 기준 PNG 복사 + compare.html
  const baselines = BASELINE_MAP.filter(([, sc]) => !only || sc === only);
  for (const [b] of baselines) {
    const src = join(BASELINE_DIR, `${b}.png`);
    if (existsSync(src)) copyFileSync(src, join(outDir, "baseline", `${b}.png`));
  }
  const has = (k) => existsSync(join(outDir, `${k}.png`));
  const pairs = baselines.map(([b, sc, st]) => `
  <section><h2>${esc(b)} <small>↔ ${esc(sc)} / ${esc(st)}</small></h2>
    <div class="pair">
      <figure>${has(`${sc}__${st}__16x9`) ? `<img src="${sc}__${st}__16x9.png">` : "<p>(찍지 못함)</p>"}<figcaption>시안 ${esc(sc)} / ${esc(st)} · 16x9</figcaption></figure>
      <figure><img src="baseline/${b}.png"><figcaption>기준 ${esc(b)}.png</figcaption></figure>
    </div></section>`).join("");
  const grids = SCREENS.filter((s) => !(only && s.name !== only) && !SKIP_RATIO_SWEEP.has(s.name)).map((s) => `
  <section><h2>${esc(s.name)} <small>${esc(s.label)} · ${esc(s.states[0])}</small></h2>
    <div class="grid">${Object.keys(RATIOS).map((r) => `<figure>${has(`${s.name}__${s.states[0]}__${r}`) ? `<img src="${s.name}__${s.states[0]}__${r}.png">` : "<p>(찍지 못함)</p>"}<figcaption>${r}</figcaption></figure>`).join("")}</div></section>`).join("");
  const states = SCREENS.filter((s) => !(only && s.name !== only)).map((s) => `
  <section><h2>${esc(s.name)} <small>모든 상태 · 16x9</small></h2>
    <div class="grid">${s.states.map((st) => `<figure>${has(`${s.name}__${st}__16x9`) ? `<img src="${s.name}__${st}__16x9.png">` : "<p>(찍지 못함)</p>"}<figcaption>${esc(st)}</figcaption></figure>`).join("")}</div></section>`).join("");
  writeFileSync(join(outDir, "compare.html"), `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>시안 · 기준 비교</title>
<style>
body{font:14px/1.5 system-ui,sans-serif;margin:16px;background:#eee;color:#222}
h1{font-size:20px} h2{font-size:15px;margin:24px 0 6px} small{font-weight:400;color:#666}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.grid{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start}
.grid figure{flex:0 0 auto;width:300px}
figure{margin:0} img{width:100%;display:block;border:1px solid #999;background:#fff}
figcaption{font-size:12px;color:#555;margin-top:2px}
</style></head><body>
<h1>시안 · 기준 비교 <small>${new Date().toISOString()}</small></h1>
<h1>1. 기준(Python 부스) ↔ 시안 16:9</h1>${pairs}
<h1>2. 화면별 화면비 6종 (기본 상태)</h1>${grids}
<h1>3. 화면별 모든 상태 (16:9)</h1>${states}
</body></html>
`);
  console.log(`끝: ${jobs.size - failed.length}/${jobs.size}장, ${((Date.now() - t0) / 1000).toFixed(1)}초`);
  if (failed.length) console.log("실패:", failed.join(", "));
  console.log(`비교 페이지: ${join(outDir, "compare.html")}`);
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => { console.error(e.message); process.exit(1); });
