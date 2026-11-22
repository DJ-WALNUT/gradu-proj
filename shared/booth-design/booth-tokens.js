// 부스 · 사진 페이지 디자인 토큰 JS 로더 (의존성 없음 — 브라우저에서 바로 import 한다).
// booth_tokens.py 와 같은 이름 · 같은 결과여야 한다 (expected.json 으로 대조).

/** 대비 식은 booth_tokens.py 와 같다 (0.03928 문턱). */
function luminance(hex) {
  const ch = (i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5);
}

/** WCAG 2 상대 휘도 대비 (1~21). */
export function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function minContrast(fg, bgs) {
  return Math.min(...bgs.map((b) => contrast(fg, b)));
}

/** 모든 배경 위에서 최악 대비가 더 큰 글씨 색. 같으면 어두운 쪽. */
export function inkOn(bgs, darkInk = "#141821", lightInk = "#ffffff") {
  return minContrast(darkInk, bgs) >= minContrast(lightInk, bgs) ? darkInk : lightInk;
}

/** fg 를 비율 a 로 bg 와 섞는다. 반올림은 floor(v+0.5) (Python 과 같게). */
export function mix(fg, bg, a) {
  let out = "#";
  for (const i of [1, 3, 5]) {
    const v = parseInt(fg.slice(i, i + 2), 16) * a + parseInt(bg.slice(i, i + 2), 16) * (1 - a);
    out += Math.floor(v + 0.5).toString(16).padStart(2, "0");
  }
  return out;
}

/** 행사 색 네 개를 색 역할 전부로 풀어낸다. 위 · 아래 배경을 모두 보고 글씨 색을 정한다. */
export function resolveRoles(tokens, event) {
  const { fixed, alpha, min_contrast: mc, roles } = tokens.color;
  const bgs = [event.bg_top, event.bg_bottom];
  const { primary, accent } = event;

  const title = minContrast(primary, bgs) >= mc.text ? primary : inkOn(bgs, fixed.dark_ink, fixed.light_ink);
  const line = minContrast(primary, bgs) >= mc.non_text ? primary : title;
  const h = mix(title, event.bg_top, alpha.hint);
  const computed = {
    title,
    line,
    hint: minContrast(h, bgs) >= mc.text ? h : title,
    on_action: inkOn([accent], fixed.dark_ink, fixed.light_ink),
    // 인화지(흰색) 위 필름 구멍 — 연한 대표색이면 구멍이 사라지므로 어두운 글씨색으로
    perforation: contrast(primary, fixed.paper) >= mc.non_text ? primary : fixed.dark_ink,
    action_edge: minContrast(accent, bgs) >= mc.non_text ? null : line,
  };
  const out = {};
  for (const [role, src] of Object.entries(roles)) {
    if (src.startsWith("computed:")) out[role] = computed[src.slice("computed:".length)];
    else if (src in event) out[role] = event[src];
    else out[role] = fixed[src];
  }
  return out;
}

/** 제작 표기를 보일지. 지금은 항상 true — 나중에 branding.show_credit 를 읽을 자리. */
export function creditVisible(_eventSettings) {
  return true;
}

/** 요소에 --role-<이름> CSS 변수를 설정한다. action_edge 가 null 이면 transparent. */
export function applyEventColors(el, tokens, event) {
  for (const [role, value] of Object.entries(resolveRoles(tokens, event))) {
    el.style.setProperty(`--role-${role.replace(/_/g, "-")}`, value === null ? "transparent" : value);
  }
}
