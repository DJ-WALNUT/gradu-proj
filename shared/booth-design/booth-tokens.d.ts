// booth-tokens.js 의 타입. tokens.json 전체를 다 적지 않고, 로더가 읽는 부분만 적는다.

export interface EventColors {
  primary: string;
  accent: string;
  bg_top: string;
  bg_bottom: string;
}

export interface Tokens {
  color: {
    roles: Record<string, string>;
    fixed: Record<string, string>;
    alpha: Record<string, number>;
    min_contrast: { text: number; non_text: number };
  };
  [group: string]: unknown;
}

/** 키는 tokens.color.roles 의 키. action_edge 는 강조색 대비가 충분하면 null. */
export type Roles = Record<string, string | null>;

export function contrast(a: string, b: string): number;
export function inkOn(bgs: string[], darkInk?: string, lightInk?: string): string;
export function mix(fg: string, bg: string, a: number): string;
export function resolveRoles(tokens: Tokens, event: EventColors): Roles;
export function creditVisible(eventSettings?: unknown): boolean;
export function applyEventColors(el: HTMLElement, tokens: Tokens, event: EventColors): void;
