// 슬롯 기하. 좌표는 프레임 PNG 원본 픽셀, rot 은 시계 방향 도(y 아래, Konva rotation 과 같음).
// slotCorners·coverCrop 은 shared/compose_fixtures.json 의 규칙 그대로 — 부스(Python)도 같은 규칙을 쓴다.
import type { Geom } from "./types";

// 꼭짓점 순서(회전 전): 좌상 → 우상 → 우하 → 좌하
export const SIGNS: [number, number][] = [
  [-1, -1],
  [1, -1],
  [1, 1],
  [-1, 1],
];

export function rotate(x: number, y: number, rot: number): [number, number] {
  const t = (rot * Math.PI) / 180;
  const c = Math.cos(t);
  const s = Math.sin(t);
  return [x * c - y * s, x * s + y * c];
}

/** 슬롯 로컬 좌표(중심 기준, 회전 전) → 프레임 좌표. */
export function localToWorld(s: Geom, x: number, y: number): [number, number] {
  const [rx, ry] = rotate(x, y, s.rot);
  return [s.cx + rx, s.cy + ry];
}

export function slotCorners(s: Geom): [number, number][] {
  return SIGNS.map(([sx, sy]) => localToWorld(s, (sx * s.w) / 2, (sy * s.h) / 2));
}

/**
 * 사진(pw×ph)에서 w×h 슬롯을 덮도록 가운데를 잘라낼 영역(정수 픽셀). 반올림은 floor(v + 0.5), 크기 최소 1px.
 * ar = w / h 를 먼저 계산하고 ph·ar, pw / ar 순서를 지킨다 — 부스(Python)와 float 결과가 같아야 한다.
 */
export function coverCrop(pw: number, ph: number, w: number, h: number): { x: number; y: number; w: number; h: number } {
  const ar = w / h;
  if (pw / ph > ar) {
    const cw = Math.max(1, Math.floor(ph * ar + 0.5));
    return { x: Math.floor((pw - cw) / 2), y: 0, w: cw, h: ph };
  }
  const ch = Math.max(1, Math.floor(pw / ar + 0.5));
  return { x: 0, y: Math.floor((ph - ch) / 2), w: pw, h: ch };
}

export function slotAABB(s: Geom): { x0: number; y0: number; x1: number; y1: number } {
  const c = slotCorners(s);
  const xs = c.map((p) => p[0]);
  const ys = c.map((p) => p[1]);
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
}
