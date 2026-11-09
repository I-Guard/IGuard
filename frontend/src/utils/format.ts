/** Formatting helpers. Missing data is ALWAYS rendered as an em dash - never as 0. */
export const DASH = "—";

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso); // backend sends UTC; Intl renders in the viewer's local timezone
  return Number.isNaN(d.getTime()) ? DASH : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium" }).format(d);
}

export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return DASH;
  const diff = Math.round((now - new Date(iso).getTime()) / 1000);
  if (Number.isNaN(diff)) return DASH;
  const abs = Math.abs(diff);
  const unit = abs < 60 ? [abs, "s"] : abs < 3600 ? [Math.floor(abs / 60), "m"] : abs < 86400 ? [Math.floor(abs / 3600), "h"] : [Math.floor(abs / 86400), "d"];
  return diff >= 0 ? `${unit[0]}${unit[1]} ago` : `in ${unit[0]}${unit[1]}`;
}

export function formatPercent(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined || Number.isNaN(v) ? DASH : `${v.toFixed(digits)}%`;
}

export function formatNumber(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined || Number.isNaN(v) ? DASH : v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function formatMs(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
}

export function formatBytes(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n = Math.abs(v), i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${(v < 0 ? -n : n).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatRate(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : `${formatBytes(v)}/s`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return DASH;
  const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m ${Math.floor(seconds % 60)}s`;
}

export function titleCase(s: string): string {
  return s.toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
