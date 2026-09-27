import type { ReviewLabel } from "./api-types";

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export function formatUtc(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : `${dateFormatter.format(date)} UTC`;
}

export function formatSeconds(value: number, precision = 3): string {
  if (!Number.isFinite(value)) return "—";
  if (value >= 60) {
    const minutes = Math.floor(value / 60);
    return `${minutes}m ${(value % 60).toFixed(1)}s`;
  }
  return `${value.toFixed(precision)} s`;
}

export function formatAmplitude(value: number): string {
  return Number.isFinite(value) ? value.toFixed(4) : "—";
}

export function shortId(value: string, length = 18): string {
  if (value.length <= length) return value;
  const side = Math.max(4, Math.floor((length - 1) / 2));
  return `${value.slice(0, side)}…${value.slice(-side)}`;
}

export function reviewLabel(value: ReviewLabel | "unreviewed"): string {
  switch (value) {
    case "confirmed_feeding":
      return "Confirmed feeding observation";
    case "non_feeding":
      return "Non-feeding observation";
    case "uncertain":
      return "Uncertain";
    default:
      return "Unreviewed";
  }
}
