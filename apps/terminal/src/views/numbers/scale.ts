export interface SeriesPoint {
  period: string;
  value: number;
  knowledge_date: string;
  /** D-AM-21: the row's DELIVERY MONTH ('YYYY-MM'), '' on every card that has no expiry axis. */
  contract_month: string;
}

/** Coerce raw silver rows (string values) into numeric series points, dropping non-numeric rows.
 *
 *  D-AM-21 `knowledge_date` FALLBACK. `period` is the alias query.py surfaces only for a card whose
 *  `period_col` is a label distinct from its date column (PSD marketing years, WASDE), so a DATE-grained
 *  card -- every futures read, and the weather/COT cards beside them -- carried NEITHER `period` NOR `date`
 *  and every point collapsed onto one x. `knowledge_date` is on those rows (silver_futures_eod's
 *  `knowledge_date_col` IS its session date) and it is ISO, so it sorts lexically == chronologically like
 *  the labels it stands in for. LAST in the chain, so a card that has a period keeps drawing exactly the
 *  axis it drew before. */
export function parsePoints(raw: Record<string, unknown>[]): SeriesPoint[] {
  return raw
    .map((p) => ({
      period: String(p.period ?? p.date ?? p.knowledge_date ?? ''),
      value: Number(p.value),
      knowledge_date: String(p.knowledge_date ?? ''),
      contract_month: String(p.contract_month ?? ''),
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

// ── D-AM-21: the curve (term-structure) axis ───────────────────────────────────────────────────────
// A curve read is `agg=latest` with several delivery months named: ONE row per expiry at ONE as-of. Its
// x is the DELIVERY MONTH, not time — which is the whole difference between a carry/backwardation picture
// and the interleaved multi-expiry blob a plain futures series read returns (`query.curve_as_calendar`
// exists to refuse computing a time-axis stat over exactly that blob).

/** The x axis a chart is drawn on: `time` is the pre-wave axis (the point's period), `curve` is the
 *  delivery-month term structure. */
export type SeriesAxis = 'time' | 'curve';

/** The x key of one point under an axis mode. */
export function axisKey(p: SeriesPoint, axis: SeriesAxis): string {
  return axis === 'curve' ? p.contract_month : p.period;
}

/** Points ordered nearest → deferred for the curve axis, dropping any row with no delivery month.
 *  'YYYY-MM' sorts lexically == chronologically, which is the same equivalence query.py's own re-sort
 *  key rests on — so this is the server's order restated, never a second ordering rule. */
export function curvePoints(points: SeriesPoint[]): SeriesPoint[] {
  return points
    .filter((p) => p.contract_month !== '')
    .slice()
    .sort((a, b) => (a.contract_month < b.contract_month ? -1 : a.contract_month > b.contract_month ? 1 : 0));
}

/** The ONE session a curve was read at, or '' when the rows do not agree on one. A curve is a single-as-of
 *  object by construction; rows spanning several sessions are a different (interleaved) read and the header
 *  must say so rather than label the picture with a date that is only true of some of it. */
export function curveSession(points: SeriesPoint[]): string {
  const days = new Set(points.map((p) => p.knowledge_date).filter((d) => d !== ''));
  return days.size === 1 ? [...days][0]! : '';
}

/** The delivery months a NUMBERS call already tracks, ascending and de-duplicated.
 *
 *  Two sources, in order: the call's own `query.contract_month` (the comma list the engine asked for — the
 *  authoritative scope, present whenever the answer itself read a curve) and, failing that, the distinct
 *  `contract_month` cells on the rows it came back with. Nothing else: the view never INVENTS an expiry, so
 *  the curve it fetches is the one the answer was already standing on (D-AM-21 PIT rule — same as-of, same
 *  months, no new date logic client-side).
 *
 *  This doubles as the futures-card test. Only a card declaring `contract_month_col` can put a non-empty
 *  delivery month on a row or in a query, so a card that has no expiry axis can never reach two distinct
 *  months — the affordance is futures-only BY CONSTRUCTION rather than by a table-name list that goes stale
 *  the day the next per-expiry card is registered. */
export function trackedMonths(
  query: { contract_month?: unknown } | undefined,
  rows: Record<string, unknown>[] | undefined,
): string[] {
  const fromQuery = String(query?.contract_month ?? '')
    .split(',')
    .map((m) => m.trim())
    .filter((m) => m !== '');
  const fromRows = (rows ?? []).map((r) => String(r?.contract_month ?? '').trim()).filter((m) => m !== '');
  return [...new Set(fromQuery.length ? fromQuery : fromRows)].sort();
}

/** |z| over threshold → an anomaly (flagged amber). */
export function isAnomaly(z: unknown, thr = 1.5): boolean {
  const n = Number(z);
  return Number.isFinite(n) && Math.abs(n) >= thr;
}
