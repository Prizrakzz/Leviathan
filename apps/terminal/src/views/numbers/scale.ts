export interface SeriesPoint {
  period: string;
  value: number;
  knowledge_date: string;
}

/** Coerce raw silver rows (string values) into numeric series points, dropping non-numeric rows. */
export function parsePoints(raw: Record<string, unknown>[]): SeriesPoint[] {
  return raw
    .map((p) => ({
      period: String(p.period ?? p.date ?? ''),
      value: Number(p.value),
      knowledge_date: String(p.knowledge_date ?? ''),
    }))
    .filter((p) => Number.isFinite(p.value));
}

/** x of the i-th of n points in a [pad, w-pad] band. */
export function xOf(i: number, n: number, w: number, pad = 1): number {
  return n <= 1 ? w / 2 : pad + i * ((w - 2 * pad) / (n - 1));
}

/** A min→max normalized sparkline path over the values. */
export function sparkPath(vals: number[], w: number, h: number, pad = 1): string {
  if (vals.length < 2) return '';
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  return vals
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i, vals.length, w, pad)} ${h - pad - ((v - min) / range) * (h - 2 * pad)}`)
    .join(' ');
}

/** Index of the last point KNOWN at/before the as-of — the vintage marker (design §4.5: what was known
 *  then). Falls back to the last point when knowledge dates are absent. */
export function vintageIndex(points: SeriesPoint[], asof: string): number {
  let idx = -1;
  points.forEach((p, i) => {
    if (p.knowledge_date && p.knowledge_date <= asof) idx = i;
  });
  return idx < 0 ? points.length - 1 : idx;
}

/** |z| over threshold → an anomaly (flagged amber). */
export function isAnomaly(z: unknown, thr = 1.5): boolean {
  const n = Number(z);
  return Number.isFinite(n) && Math.abs(n) >= thr;
}
