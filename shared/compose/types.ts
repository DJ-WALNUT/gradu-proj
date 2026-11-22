// 합성 공용 타입. 의존성 없음 — 관리자 웹과 웹 부스가 함께 쓴다.

/** 슬롯 기하. 좌표는 프레임 PNG 원본 픽셀, rot 은 시계 방향 도(y 아래). */
export type Geom = { cx: number; cy: number; w: number; h: number; rot: number };

/** 합성에 필요한 슬롯 정보. 관리자 웹의 Slot 은 구조가 맞으므로 그대로 넘길 수 있다. */
export type ComposeSlot = Geom & { id: string; shot: number };

export type ComposePhoto = { source: CanvasImageSource; width: number; height: number };
/** 프레임 레이어. width/height 는 프레임 원본 좌표 크기(source 는 줄인 비트맵이어도 된다). */
export type FrameLayer = { source: CanvasImageSource | null; width: number; height: number };

export type PlanItem = {
  slotId: string;
  photoIndex: number;
  crop: { x: number; y: number; w: number; h: number };
  dest: { cx: number; cy: number; w: number; h: number; rot: number };
};

/** preview: shot % 컷 수 (편집기 미리보기). booth: shot 번호의 컷 그대로, 없으면 RangeError. */
export type ComposeMode = "preview" | "booth";
