import type { components } from '@/api/types.gen';

type RegimeCard = components['schemas']['RegimeCard'];
type ConvergenceRow = components['schemas']['ConvergenceRow'];

/** Proximity-to-firing bucket for a regime cell (design §4.8). `fired` always wins over proximity. */
export type HeatBucket = 'fired' | 'hot' | 'warm' | 'cool' | 'dormant';

export function heatBucket(proximity: number, fired: boolean): HeatBucket {
  if (fired) return 'fired';
  const p = Number.isFinite(proximity) ? proximity : 0;
  if (p >= 0.75) return 'hot';
  if (p >= 0.5) return 'warm';
  if (p >= 0.25) return 'cool';
  return 'dormant';
}

/** Token utility classes per bucket — hottest = solid amber, coolest = faint (no raw hex; design §2). */
export const HEAT_CLASS: Record<HeatBucket, string> = {
  fired: 'bg-amber text-bg-0',
  hot: 'bg-amber-dim text-bg-0',
  warm: 'bg-bg-2 text-amber',
  cool: 'bg-bg-2 text-text-dim',
  dormant: 'bg-bg-1 text-text-faint',
};

/** A row's hottest regime — the sort key that floats "where convexity is building" to the top. */
export function maxProximity(row: ConvergenceRow): number {
  return row.regimes.reduce((m, r) => Math.max(m, r.fired ? 1 : (r.proximity ?? 0)), 0);
}

export function firedCount(row: ConvergenceRow): number {
  return row.regimes.filter((r) => r.fired).length;
}

/** Rows sorted hottest-first (max proximity desc), stable tiebreak on contract name. */
export function rankRows(rows: ConvergenceRow[]): ConvergenceRow[] {
  return [...rows].sort(
    (a, b) => maxProximity(b) - maxProximity(a) || a.contract.localeCompare(b.contract),
  );
}

/** Short glyph for a regime cell: direction arrow + active/threshold count. */
export function cellLabel(r: RegimeCard): string {
  const dir = r.direction === '+' ? '▲' : r.direction === '-' ? '▼' : '•';
  return `${dir} ${r.n_active}/${r.threshold}`;
}
