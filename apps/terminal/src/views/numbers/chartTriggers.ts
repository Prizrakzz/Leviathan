import { getSeries } from '@/api/client';
import type { components } from '@/api/types.gen';
import type { ChartTabParams } from '@/store/tabs';
import { parsePoints, type SeriesPoint, trackedMonths } from './scale';

type Series = components['schemas']['Series'];

// FILE NAME: `chartTriggers`, NOT `chartCards`. The renderer beside it is ChartCards.tsx, and Windows'
// filesystem is case-INSENSITIVE: `import ... from './chartCards'` inside ChartCards.tsx resolves to
// ChartCards.tsx itself there (and to this module on Linux), so the two names would mean different files
// on different machines. Measured, not theorized -- it failed exactly that way on the first run.

// ── D-UX-2/3: ONE definition of "a series read" ────────────────────────────────────────────────────
// The row affordance, the answer's chart cards and the chart TAB must all describe the same fetch, or the
// three surfaces silently split the react-query cache three ways and the same picture is fetched three
// times (and, worse, can disagree). A chart locator IS the tab's params -- there is no second type -- so
// "open in tab" is a pass-through of the object the card was already drawing from, never a re-derivation.
export type ChartLocator = ChartTabParams;

/** The react-query key for a locator. DELIBERATELY IDENTICAL to the two key families Numbers.tsx already
 *  uses for its own expansions (['series', table, metric, commodity, country, asof] and ['curve', ...,
 *  months]) so opening a chart from a row the reader already expanded is a CACHE HIT, not a second
 *  /v1/series round trip. numbersQueryKeyParity in the tests pins the two shapes against each other; if
 *  Numbers.tsx ever changes its key, that test fails rather than the cache quietly splitting. */
export function seriesQueryKey(loc: ChartLocator): unknown[] {
  return loc.axis === 'curve'
    ? ['curve', loc.table, loc.metric, loc.commodity, loc.country, loc.asof, loc.contract_month ?? '']
    : ['series', loc.table, loc.metric, loc.commodity, loc.country, loc.asof];
}

/** The /v1/series fetch for a locator, pinned to the locator's OWN as-of -- never `today`, never the
 *  session's live as-of. A chart opened off a turn shows the rows that turn cited (PIT by construction). */
export function fetchSeries(loc: ChartLocator): Promise<Series> {
  return getSeries(
    loc.table,
    loc.metric,
    loc.axis === 'curve'
      ? {
          commodity: loc.commodity,
          country: loc.country,
          asof: loc.asof,
          contractMonth: loc.contract_month,
          agg: 'latest',
        }
      : { commodity: loc.commodity, country: loc.country, asof: loc.asof },
  );
}

/** A reader-facing tab/card title from a locator. Slugs are underscore-joined on the wire. */
export function chartTitle(loc: ChartLocator): string {
  const head = loc.commodity || loc.country || loc.table;
  return `${head} ${loc.metric}${loc.axis === 'curve' ? ' curve' : ''}`.replace(/_/g, ' ');
}

// ── D-UX-3: the deterministic triggers ─────────────────────────────────────────────────────────────
// THE LAW (UX_WAVE_PLAN): no model decides whether a chart appears -- the TURN does. Everything below reads
// only what the FE already holds (`number_calls` + `trace`), and every card names the deterministic leg that
// minted it. A turn whose legs computed nothing chartable produces ZERO cards, and ChartCards then renders
// zero bytes.

/** The synthetic table name the stats tool belt stamps on an injected [N] row (numbers/agent.py
 *  STATS_TOOL_NAME). A call wearing it is a COMPUTED figure, not a lookup: it has no table/commodity of its
 *  own, which is exactly why the source lookup has to be recovered through the handle below. */
const STATS_TABLE = 'compute_stat';

/** The two time-axis stats that make a series worth drawing with its as-of marker: a positional walk
 *  (window_change) and a rank inside its own history (zscore). Both are claims ABOUT a period series, so the
 *  honest picture is that series. */
const WINDOW_STATS = new Set(['window_change', 'zscore']);

/** The one CURVE-axis stat (D-AM-17): a difference between two NAMED delivery months. Its source read is a
 *  term structure by construction -- stats.spread refuses rows that carry no delivery month at all. */
const CURVE_STAT = 'spread';

/** The synthetic metric the co-move engine stamps on its injected World stocks-to-use rows
 *  (numbers/cascade.py `_xc_call`). */
const COMOVE_METRIC = 'su_ratio_world';

/** One `number_calls` entry as the engine emits it. `handle` is the turn-scoped lookup id the agent mints
 *  at the tool-result seam and mutates onto the SAME dict it already appended to `calls`, which is what
 *  makes a stat's `stat_provenance.input_handles` resolvable client-side. */
interface RawCall {
  ref?: string;
  handle?: string;
  status?: string;
  query?: Record<string, unknown>;
  rows?: Record<string, unknown>[];
  stat_provenance?: { stat?: string; input_handles?: string[] };
}

/** Two labelled legs drawn in ONE svg. `points` are scale.ts points so the overlay shares the numbers
 *  view's coercion rules (string values -> numbers, non-numeric rows dropped) rather than inventing a
 *  second parser. */
export interface OverlayLeg {
  label: string;
  unit: string;
  points: SeriesPoint[];
}

export type ChartCard =
  | { kind: 'curve' | 'series'; id: string; title: string; reason: string; locator: ChartLocator }
  | { kind: 'overlay'; id: string; title: string; reason: string; legs: [OverlayLeg, OverlayLeg]; window: string };

function asCalls(raw: unknown): RawCall[] {
  return Array.isArray(raw) ? (raw.filter((c) => !!c && typeof c === 'object') as RawCall[]) : [];
}

function str(v: unknown): string {
  return v == null ? '' : String(v);
}

/** A CURVE read: several delivery months named, collapsed to one row per month at ONE as-of.
 *
 *  `agg === 'latest'` is load-bearing, not belt-and-braces. `agg='series'` over the same card returns the
 *  INTERLEAVED blob -- many expiries times many sessions -- which is not a term structure and is precisely
 *  the shape query.curve_as_calendar exists to refuse. Drawing it on a delivery-month x would stack a dozen
 *  sessions on each tick and read as a curve. The agent's spec always carries `agg` (it defaults to
 *  'latest' and model_dump keeps non-None fields), so an absent one reads as the default. */
function isCurveRead(c: RawCall): boolean {
  const q = c.query ?? {};
  if (!q.table || !q.metric) return false;
  const agg = str(q.agg ?? 'latest');
  return agg === 'latest' && trackedMonths(q, c.rows).length >= 2;
}

function locatorOf(c: RawCall, axis: 'time' | 'curve', asof: string): ChartLocator | null {
  const q = c.query ?? {};
  const table = str(q.table);
  const metric = str(q.metric);
  if (!table || !metric || table === STATS_TABLE) return null;
  const loc: ChartLocator = { table, metric, axis, asof };
  if (q.commodity) loc.commodity = str(q.commodity);
  if (q.country) loc.country = str(q.country);
  if (axis === 'curve') {
    const months = trackedMonths(q, c.rows);
    if (months.length < 2) return null;
    loc.contract_month = months.join(',');
  }
  return loc;
}

/** The LOOKUP a stat was computed over, recovered through its first input handle.
 *
 *  Fails CLOSED and that matters: a stat chained off another stat's result references a handle no lookup
 *  call carries (the chaining handle is minted onto the tool-result payload, never onto the injected [N]
 *  rows), so it resolves to nothing and mints no card -- rather than guessing which read underneath it was
 *  "the real one" and drawing a series the answer never stood on. */
function sourceLookup(stat: RawCall, calls: RawCall[]): RawCall | null {
  const h = stat.stat_provenance?.input_handles?.[0];
  if (!h) return null;
  return calls.find((c) => c.handle === h && str(c.query?.table) !== STATS_TABLE) ?? null;
}

function statMetric(c: RawCall): string {
  return str(c.query?.table) === STATS_TABLE ? str(c.query?.metric) : '';
}

/** The two co-move legs, rebuilt from the rows the engine INJECTED for them.
 *
 *  Why no fetch: World stocks-to-use is SYNTHESIZED (cascade.py `_world_su_ratio` -- "no literal
 *  country='World' row exists"; it is a sum over each country's own latest vintage <= as-of, with an EU
 *  membership dedup). There is no /v1/series read that returns it, and asking for silver_psd su_ratio
 *  without a country would return a per-country blob that is NOT the number the answer quoted. So the
 *  overlay draws the exact rows the leg minted -- the strongest PIT posture available, since there is no
 *  second fetch that could drift from the answer at all.
 *
 *  The unit filter is the mint restated: `_xc_leg_lines` injects THREE rows per leg -- the endpoint and the
 *  baseline in '%', and the within-window delta in 'pp'. Only the two '%' rows are points on a
 *  stocks-to-use axis; the 'pp' row is a difference between them and would draw as a third, false point. */
function comoveLegs(calls: RawCall[], trace: Record<string, unknown>): [OverlayLeg, OverlayLeg] | null {
  const cm = trace.quantify_comove as Record<string, unknown> | undefined;
  if (!cm || typeof cm !== 'object') return null;
  const a = str(cm.commodityA);
  const b = str(cm.commodityB);
  if (!a || !b || a === b) return null;

  const leg = (slug: string): OverlayLeg | null => {
    const rows = calls
      .filter((c) => str(c.query?.metric) === COMOVE_METRIC && str(c.query?.commodity) === slug)
      .flatMap((c) =>
        (c.rows ?? [])
          .filter((r) => str(r.unit) === '%')
          .map((r) => ({ ...r, period: str(c.query?.period) })),
      );
    const points = parsePoints(rows)
      .filter((p) => p.period !== '')
      .sort((x, y) => (x.period < y.period ? -1 : x.period > y.period ? 1 : 0));
    if (points.length < 2) return null;
    return { label: slug.replace(/_/g, ' '), unit: '%', points };
  };

  const la = leg(a);
  const lb = leg(b);
  return la && lb ? [la, lb] : null;
}

/**
 * The chart cards a completed turn earns, most informative first, capped at two.
 *
 * Priority (plan D-UX-3): curve/carry > overlay > series. It is a ranking of SPECIFICITY -- a term structure
 * and a fired pair leg each say something the prose cannot, while a period series is the picture a reader
 * can already reach by expanding the row it came from.
 */
export function deriveChartCards(
  result: { number_calls?: unknown; trace?: unknown } | null | undefined,
  asof: string,
): ChartCard[] {
  const calls = asCalls(result?.number_calls);
  const trace = (result?.trace ?? {}) as Record<string, unknown>;

  const curves: ChartCard[] = [];
  const seen = new Set<string>();
  const push = (into: ChartCard[], kind: 'curve' | 'series', loc: ChartLocator, reason: string) => {
    const id = `${kind}:${JSON.stringify(loc)}`;
    if (seen.has(id)) return;
    seen.add(id);
    into.push({ kind, id, title: chartTitle(loc), reason, locator: loc });
  };

  // (1) a spread stat -- the carry the answer actually computed, over the curve it computed it on.
  for (const c of calls) {
    if (statMetric(c) !== CURVE_STAT || (c.status && c.status !== 'ok')) continue;
    const src = sourceLookup(c, calls);
    if (!src || !isCurveRead(src)) continue;
    const loc = locatorOf(src, 'curve', asof);
    if (loc) push(curves, 'curve', loc, 'a spread was computed across these delivery months');
  }
  // (2) a curve read that stands on its own (the answer read a term structure without differencing it).
  for (const c of calls) {
    if (!isCurveRead(c)) continue;
    const loc = locatorOf(c, 'curve', asof);
    if (loc) push(curves, 'curve', loc, 'this answer read the term structure across these months');
  }

  const overlays: ChartCard[] = [];
  const legs = comoveLegs(calls, trace);
  if (legs) {
    const cm = trace.quantify_comove as Record<string, unknown>;
    overlays.push({
      kind: 'overlay',
      id: `overlay:${legs[0].label}:${legs[1].label}`,
      title: `${legs[0].label} vs ${legs[1].label}`,
      reason: 'the co-move leg fired on these two stocks-to-use series',
      legs,
      window: str(cm.window),
    });
  }

  const series: ChartCard[] = [];
  for (const c of calls) {
    const m = statMetric(c);
    if (!WINDOW_STATS.has(m) || (c.status && c.status !== 'ok')) continue;
    const src = sourceLookup(c, calls);
    // A window stat whose source is a CURVE read is not a period-series claim -- it is the curve-as-calendar
    // shape the engine's own S4 guard declines -- so it gets no series card.
    if (!src || isCurveRead(src)) continue;
    const loc = locatorOf(src, 'time', asof);
    if (loc) push(series, 'series', loc, `a ${m} was computed over this series`);
  }

  return [...curves, ...overlays, ...series].slice(0, 2);
}
