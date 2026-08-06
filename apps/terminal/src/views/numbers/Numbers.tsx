import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { getSeries } from '@/api/client';
import { SeriesChart } from './SeriesChart';
import {
  type SeriesAxis,
  curvePoints,
  isAnomaly,
  parsePoints,
  sparkPath,
  trackedMonths,
  vintageIndex,
  xOf,
} from './scale';

interface NumCall {
  ref?: string;
  query?: { table?: string; metric?: string; commodity?: string; country?: string; contract_month?: string };
  rows?: { value?: unknown; z?: unknown; contract_month?: unknown }[];
  status?: string;
}

function NumberRow({ call, asof }: { call: NumCall; asof: string }) {
  const [open, setOpen] = useState(false);
  const [axis, setAxis] = useState<SeriesAxis>('time');
  const table = call.query?.table;
  const metric = call.query?.metric;
  const country = call.query?.country;
  const notYet = call.status === 'not_yet_pub';
  // D-TW-9: `country` rides in BOTH halves and must ride in both. In the request, because the row's value
  // came from a country-scoped read and an unscoped series is a different series under the same [N#]. In
  // the KEY, because two calls differing only by country (Brazil vs Argentina soybean exports -- the shape
  // every trade question takes) otherwise share one cache entry and the second row draws the first's line.
  const q = useQuery({
    queryKey: ['series', table, metric, call.query?.commodity, country, asof],
    queryFn: () => getSeries(table!, metric!, { commodity: call.query?.commodity, country, asof }),
    enabled: !!table && !!metric && !notYet && open,
    staleTime: 60_000,
  });

  // D-AM-21 CURVE VIEW. A SECOND query rather than a parameterized first one, deliberately: the time-series
  // fetch above drives the row's own sparkline and is pinned (D-TW-9) down to its argument object, so the
  // curve is added BESIDE it and the pre-wave path stays byte-identical -- on a non-futures card `months` is
  // empty, the affordance never renders, and this query is never enabled.
  // The months are the ones the CALL already tracked (its own `contract_month` scope, else the expiries its
  // rows came back on), and the as-of is the row's own -- so the curve is the term structure the answer was
  // already standing on. No client-side date logic, and nothing invented.
  const months = trackedMonths(call.query, call.rows);
  const canCurve = months.length >= 2;
  const cq = useQuery({
    queryKey: ['curve', table, metric, call.query?.commodity, country, asof, months.join(',')],
    queryFn: () =>
      getSeries(table!, metric!, {
        commodity: call.query?.commodity,
        country,
        asof,
        contractMonth: months.join(','),
        agg: 'latest',
      }),
    enabled: !!table && !!metric && !notYet && canCurve && open && axis === 'curve',
    staleTime: 60_000,
  });
  const cpts = cq.data ? curvePoints(parsePoints(cq.data.points as Record<string, unknown>[])) : [];

  if (notYet) {
    return (
      <div className="flex items-center gap-2 py-0.5 font-mono text-12">
        <span className="text-cyan">[{call.ref}]</span>
        <span className="w-24 text-text-dim">{metric}</span>
        <span className="text-text-faint">not known at {asof}</span>
      </div>
    );
  }

  const row0 = call.rows?.[0];
  const val = row0?.value != null ? String(row0.value) : '—';
  const z = row0?.z;
  const anom = isAnomaly(z);
  const pts = q.data ? parsePoints(q.data.points as Record<string, unknown>[]) : [];
  const vidx = pts.length ? vintageIndex(pts, asof) : -1;

  return (
    <div>
      <button
        className="flex w-full items-center gap-3 py-0.5 text-left font-mono text-12 hover:bg-bg-2"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-cyan">[{call.ref}]</span>
        <span className="w-24 shrink-0 text-text-dim">{metric}</span>
        <span className={`w-14 shrink-0 tabular-nums ${anom ? 'text-amber' : 'text-text'}`}>{val}</span>
        {pts.length >= 2 && (
          <svg width={90} height={18} className="shrink-0" aria-hidden>
            <path d={sparkPath(pts.map((p) => p.value), 90, 18)} fill="none" className="stroke-text-dim" strokeWidth={1} />
            {vidx >= 0 && (
              <line x1={xOf(vidx, pts.length, 90)} y1={0} x2={xOf(vidx, pts.length, 90)} y2={18} className="stroke-cyan" strokeWidth={0.8} />
            )}
          </svg>
        )}
        {z != null && String(z) !== '' && (
          <span className={`text-11 ${anom ? 'text-amber' : 'text-text-dim'}`}>
            z={String(z)}
            {anom ? ' ⚠' : ''}
          </span>
        )}
      </button>
      {/* D-AM-21: the axis switch renders ONLY on a call that tracks two or more delivery months -- i.e.
          only on a per-expiry futures card -- so every other row's expansion is exactly what it was. The
          curve pane mirrors the time pane's state ladder below (loading / failed+retry / too-short), for
          the same D-TW-9 reason: an expansion that can render nothing is indistinguishable from a dead one. */}
      {open && canCurve && (
        <div className="flex gap-2 py-0.5 font-mono text-11" role="group" aria-label="chart axis">
          {(['time', 'curve'] as SeriesAxis[]).map((a) => (
            <button
              key={a}
              onClick={() => setAxis(a)}
              aria-pressed={axis === a}
              className={axis === a ? 'text-cyan' : 'text-text-faint hover:text-text-dim'}
            >
              {a}
            </button>
          ))}
        </div>
      )}
      {open && axis === 'curve' && canCurve &&
        (cq.isError ? (
          <div className="py-0.5 font-mono text-11 text-text-faint">
            couldn't load this curve —{' '}
            <button onClick={() => void cq.refetch()} className="text-cyan hover:text-amber">
              retry
            </button>
          </div>
        ) : cq.isLoading ? (
          <div className="py-0.5 font-mono text-11 text-text-faint">loading curve…</div>
        ) : !cq.data || cpts.length < 2 ? (
          <div className="py-0.5 font-mono text-11 text-text-faint">no curve to plot at this as-of</div>
        ) : (
          <SeriesChart series={cq.data} asof={asof} axis="curve" />
        ))}
      {/* D-TW-9: the expansion is state-complete. It used to render the chart or NOTHING, so an in-flight
          fetch and a dead one were the same thing on screen -- the row opened and nothing happened, with no
          way to tell waiting from broken and no way to retry. The last branch covers the third silent case:
          a fetch that SUCCEEDED with too few points, since SeriesChart draws nothing below two (the same
          threshold that gates the row's own sparkline above). `isLoading` rather than `!q.data` so a call
          the query is DISABLED for can never sit on "loading…" that will never arrive. */}
      {open && axis === 'time' &&
        (q.isError ? (
          <div className="py-0.5 font-mono text-11 text-text-faint">
            couldn't load this series —{' '}
            <button onClick={() => void q.refetch()} className="text-cyan hover:text-amber">
              retry
            </button>
          </div>
        ) : q.isLoading ? (
          <div className="py-0.5 font-mono text-11 text-text-faint">loading series…</div>
        ) : !q.data || pts.length < 2 ? (
          <div className="py-0.5 font-mono text-11 text-text-faint">no series to plot at this as-of</div>
        ) : (
          <SeriesChart series={q.data} asof={asof} />
        ))}
    </div>
  );
}

/** The NUMBERS panel (design §4.5): every metric with its vintage-marked sparkline + `[N#]`, never a bare
 *  value; click a row to expand the full series. */
export function Numbers({ calls, asof }: { calls: unknown[]; asof: string }) {
  const cs = (calls ?? []) as NumCall[];
  if (!cs.length) return null;
  return (
    <div className="rounded-panel border border-line bg-bg-1 p-2" data-testid="numbers">
      <div className="mb-1 font-mono text-11 uppercase tracking-wider text-text-dim">Numbers</div>
      {cs.map((c, i) => (
        <NumberRow key={i} call={c} asof={asof} />
      ))}
    </div>
  );
}
