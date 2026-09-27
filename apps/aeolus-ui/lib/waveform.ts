import type { WaveformBucket } from "./api-types";

export type PlotBox = {
  left: number;
  top: number;
  width: number;
  height: number;
};

function clampAmplitude(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(-1, Math.min(1, value));
}

export function bucketX(bucket: WaveformBucket, duration: number, box: PlotBox): number {
  const midpoint = (bucket.start_s + bucket.end_s) / 2;
  if (!Number.isFinite(duration) || duration <= 0) return box.left;
  return box.left + (Math.max(0, Math.min(duration, midpoint)) / duration) * box.width;
}

export function amplitudeY(value: number, box: PlotBox): number {
  return box.top + ((1 - clampAmplitude(value)) / 2) * box.height;
}

export function envelopePath(
  buckets: readonly WaveformBucket[],
  duration: number,
  box: PlotBox,
): string {
  if (buckets.length === 0) return "";
  const top = buckets.map((bucket) => `${bucketX(bucket, duration, box).toFixed(2)},${amplitudeY(bucket.max, box).toFixed(2)}`);
  const bottom = [...buckets]
    .reverse()
    .map((bucket) => `${bucketX(bucket, duration, box).toFixed(2)},${amplitudeY(bucket.min, box).toFixed(2)}`);
  const points = [...top, ...bottom];
  return `M${points[0]} ${points.slice(1).map((point) => `L${point}`).join(" ")} Z`;
}

export function intervalRect(
  start: number,
  end: number,
  duration: number,
  box: PlotBox,
): { x: number; width: number } {
  if (!Number.isFinite(duration) || duration <= 0) return { x: box.left, width: 0 };
  const safeStart = Math.max(0, Math.min(duration, start));
  const safeEnd = Math.max(safeStart, Math.min(duration, end));
  const x = box.left + (safeStart / duration) * box.width;
  const width = Math.max(2, ((safeEnd - safeStart) / duration) * box.width);
  return { x, width: Math.min(width, box.left + box.width - x) };
}
