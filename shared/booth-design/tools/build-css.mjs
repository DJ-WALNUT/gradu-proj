// tokens.json → tokens.css 생성기. 직접 실행하면 tokens.css 를 쓴다:
//   node shared/booth-design/tools/build-css.mjs
// 행사 색(--role-*)은 런타임에 applyEventColors 가 넣으므로 여기서 만들지 않는다.
// 화면 배치(layout)는 내보내지 않는다 (Python · JS 로더가 tokens.json 을 직접 읽는다).
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HEADER = "/* 생성물 — tokens.json 을 고치고 build-css.mjs 를 돌린다 */";
const kebab = (s) => s.replace(/_/g, "-");
const px = (n) => `${n}px`;

export function buildCss(tokens) {
  const v = [];
  const add = (name, value) => v.push(`  --${name}: ${value};`);

  for (const [k, n] of Object.entries(tokens.type.size)) add(`type-${kebab(k)}`, px(n));
  add("type-portrait-scale", tokens.type.portrait_scale);
  for (const [k, n] of Object.entries(tokens.type.weight)) add(`type-weight-${kebab(k)}`, n);

  tokens.space.step.forEach((n, i) => add(`space-${i}`, px(n)));
  for (const [k, r] of Object.entries(tokens.space.radius)) {
    add(`radius-${kebab(k)}`, r === "pill" ? "9999px" : r === "circle" ? "50%" : px(r));
  }

  const p = tokens.print;
  add("print-border", px(p.border));
  add("print-border-bottom", px(p.border_bottom));
  for (const [k, n] of Object.entries(p.perforation)) add(`print-perforation-${kebab(k)}`, px(n));
  // 필름 넘김 전환의 필름 칸 구멍 (인화지 구멍과 따로 — 화면 전체를 지나가는 큰 필름)
  for (const [k, n] of Object.entries(p.film_strip)) add(`print-film-strip-${kebab(k)}`, px(n));
  add("print-shadow-y", px(p.shadow.y));
  add("print-shadow-blur", px(p.shadow.blur));
  add("print-tilt", `${p.tilt_deg}deg`);

  add("credit-text", JSON.stringify(tokens.credit.text));
  add("credit-bottom", px(tokens.credit.bottom));
  add("credit-hidden-bottom", px(tokens.credit.hidden_bottom));

  add("motion-ease", tokens.motion.ease);
  for (const [k, n] of Object.entries(tokens.motion.duration_ms)) add(`motion-${kebab(k)}`, `${n}ms`);
  // 시작 버튼 숨쉬기 — 양 끝에서 멈췄다 도는 곡선. motion-ease(감속)를 되감으면 작아지는 끝에서 꺾인다
  add("motion-breath-half", `${tokens.motion.breath.half_ms}ms`);
  add("motion-breath-ease", tokens.motion.breath.ease);
  add("motion-breath-scale", tokens.motion.breath.scale);

  for (const [k, n] of Object.entries(tokens.color.alpha)) add(`alpha-${kebab(k)}`, n);
  for (const [k, c] of Object.entries(tokens.color.fixed)) add(`fixed-${kebab(k)}`, c);

  add("touch-min-button-landscape", px(tokens.touch.min_button_px.landscape));
  add("touch-min-button-phone", px(tokens.touch.min_button_px.phone));
  add("touch-focus-ring", px(tokens.touch.focus_ring_px));
  add("touch-line", px(tokens.touch.line_px));
  add("touch-long-press", `${tokens.touch.long_press_ms}ms`);

  return `${HEADER}\n:root {\n${v.join("\n")}\n}\n`;
}

// 직접 실행했을 때만 파일을 쓴다 (테스트가 import 할 때는 쓰지 않는다).
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const dir = join(dirname(fileURLToPath(import.meta.url)), "..");
  const tokens = JSON.parse(readFileSync(join(dir, "tokens.json"), "utf8"));
  writeFileSync(join(dir, "tokens.css"), buildCss(tokens));
}
