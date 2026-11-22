// 합성 계산·그리기. 규칙은 shared/compose_fixtures.json · shared/README.md (Python 부스와 동일).
import { coverCrop } from "./geometry";
import type { ComposeMode, ComposePhoto, ComposeSlot, FrameLayer, PlanItem } from "./types";

export function composePlan(
  _frame: { width: number; height: number },
  slots: ComposeSlot[],
  photos: { width: number; height: number }[],
  mode: ComposeMode = "preview",
): PlanItem[] {
  if (photos.length === 0 && mode === "preview") return [];
  return slots.map((s) => {
    if (mode === "booth" && !(s.shot >= 0 && s.shot < photos.length)) {
      throw new RangeError(`컷 ${s.shot} 이 없습니다`);
    }
    const photoIndex = mode === "booth" ? s.shot : s.shot % photos.length;
    const p = photos[photoIndex];
    return {
      slotId: s.id,
      photoIndex,
      crop: coverCrop(p.width, p.height, s.w, s.h),
      dest: { cx: s.cx, cy: s.cy, w: s.w, h: s.h, rot: s.rot },
    };
  });
}

/** 프레임 좌표계로 그린다: 흰 바탕 → 슬롯(plan 순서) → 프레임. scale 은 화면 배율. */
export function renderCompose(
  ctx: CanvasRenderingContext2D,
  frameImg: FrameLayer,
  slots: ComposeSlot[],
  photos: ComposePhoto[],
  scale: number,
  mode: ComposeMode = "preview",
): void {
  ctx.scale(scale, scale);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, frameImg.width, frameImg.height);
  if (photos.length === 0 && mode === "preview") {
    for (const s of slots) {
      ctx.save();
      ctx.translate(s.cx, s.cy);
      ctx.rotate((s.rot * Math.PI) / 180);
      ctx.fillStyle = "#cfcfcf";
      ctx.fillRect(-s.w / 2, -s.h / 2, s.w, s.h);
      ctx.fillStyle = "#555";
      ctx.font = `bold ${Math.round(Math.min(s.w, s.h) * 0.5)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(s.shot + 1), 0, 0);
      ctx.restore();
    }
  } else {
    for (const it of composePlan(frameImg, slots, photos, mode)) {
      const { crop: c, dest: d } = it;
      ctx.save();
      ctx.translate(d.cx, d.cy);
      ctx.rotate((d.rot * Math.PI) / 180);
      ctx.drawImage(photos[it.photoIndex].source, c.x, c.y, c.w, c.h, -d.w / 2, -d.h / 2, d.w, d.h);
      ctx.restore();
    }
  }
  if (frameImg.source) ctx.drawImage(frameImg.source, 0, 0, frameImg.width, frameImg.height);
}
