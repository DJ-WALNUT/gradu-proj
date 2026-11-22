// 컷 필터. booth/walnut/filters.py 와 같은 값을 낸다 (기대값: ../filter_fixtures.json).
// 채널별 floor(gain*v + bias + 0.5) 를 0~255 로 자른다 (float64 — Python 과 같음).

export const FILTERS = ["original", "mono", "bright", "warm", "cool", "vintage"] as const;
export type FilterName = (typeof FILTERS)[number];

type ChannelParam = [gain: number, bias: number];
export type FilterParams = [ChannelParam, ChannelParam, ChannelParam];

// filters.py 의 _PARAMS 와 같은 값.
const PARAMS: Record<Exclude<FilterName, "mono">, FilterParams> = {
  original: [[1.0, 0], [1.0, 0], [1.0, 0]],
  bright: [[1.12, 12], [1.12, 12], [1.12, 12]],
  warm: [[1.0, 18], [1.0, 4], [1.0, -14]],
  cool: [[1.0, -14], [1.0, 2], [1.0, 18]],
  vintage: [[0.85, 38], [0.85, 28], [0.8, 22]],
};

/** 채널별 [기울기, 더하는 값]. mono 는 "mono". 모르는 이름은 original. (WebGL 셰이더도 이 값을 쓴다) */
export function filterParams(name: string): FilterParams | "mono" {
  if (name === "mono") return "mono";
  return Object.prototype.hasOwnProperty.call(PARAMS, name) ? PARAMS[name as keyof typeof PARAMS] : PARAMS.original;
}

/** RGBA 픽셀을 제자리에서 바꾼다. 알파는 그대로. */
export function applyFilter(data: Uint8ClampedArray, name: string): void {
  const p = filterParams(name);
  if (p === "mono") {
    for (let i = 0; i + 3 < data.length; i += 4) {
      const y = Math.floor(0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2] + 0.5);
      data[i] = data[i + 1] = data[i + 2] = y; // Uint8ClampedArray 가 0~255 로 자른다
    }
    return;
  }
  if (name === "original" || p === PARAMS.original) return;
  // 반올림을 직접 한다: Uint8ClampedArray 의 대입은 .5 를 짝수로 보내므로 floor 된 정수만 넣는다.
  const luts = p.map(([g, b]) => {
    const lut = new Uint8ClampedArray(256);
    for (let v = 0; v < 256; v++) lut[v] = Math.floor(g * v + b + 0.5);
    return lut;
  });
  for (let i = 0; i + 3 < data.length; i += 4) {
    data[i] = luts[0][data[i]];
    data[i + 1] = luts[1][data[i + 1]];
    data[i + 2] = luts[2][data[i + 2]];
  }
}
