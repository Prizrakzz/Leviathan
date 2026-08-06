import { useQuery } from '@tanstack/react-query';
import type { ChartTabParams } from '@/store/tabs';
import { fetchSeries, seriesQueryKey } from '@/views/numbers/chartTriggers';
import { curvePoints, parsePoints } from '@/views/numbers/scale';
import { SeriesChart } from '@/views/numbers/SeriesChart';

/** D-UX-2: a series (or term structure) as a workspace tab -- the surface that finally makes the charts
 *  reachable instead of leaving them three levels deep inside one expanded numbers row.
 *
 *  LOCATOR-ONLY, like every other tab kind: the params are exactly /v1/series' arguments plus the axis and
 *  the as-of, so a rehydrated tab REFETCHES the same rows rather than replaying a frozen copy of them. The
 *  query key family is shared with Numbers.tsx via seriesQueryKey, so opening a chart off a row the reader
 *  already expanded resolves from cache with no second fetch.
 *
 *  The state ladder is the D-TW-9 one, and for the same reason: a tab that can render nothing is
 *  indistinguishable from a dead one, so in-flight, failed-with-retry and returned-but-too-short each say
 *  what they are. A stale locator (a renamed metric, a delivery month that no longer resolves) lands on the
 *  last two rungs -- degraded, never a crash. */
export default function ChartTab({ params }: { params: ChartTabParams }) {
  const q = useQuery({
    queryKey: seriesQueryKey(params),
    queryFn: () => fetchSeries(params),
    staleTime: 60_000,
  });

  const pts = q.data ? parsePoints(q.data.points as Record<string, unknown>[]) : [];
  const drawable = params.axis === 'curve' ? curvePoints(pts).length : pts.length;

  const head = (
    <div className="mb-2 font-mono text-11 uppercase tracking-wider text-text-dim" data-testid="chart-tab-head">
      chart · {params.table} · {params.metric}
      {params.commodity ? ` · ${params.commodity}` : ''}
      {params.country ? ` · ${params.country}` : ''}
      {params.asof ? ` · as of ${params.asof}` : ''}
    </div>
  );

  return (
    <div className="h-full overflow-auto p-4" data-testid="chart-tab">
      {head}
      {q.isError ? (
        <div className="font-mono text-12 text-text-faint">
          couldn’t load this chart ·{' '}
          <button onClick={() => void q.refetch()} className="text-cyan hover:text-amber">
            retry
          </button>
        </div>
      ) : q.isLoading ? (
        <div className="font-mono text-12 text-text-faint" data-testid="chart-tab-loading">
          loading chart…
        </div>
      ) : !q.data || drawable < 2 ? (
        <div className="font-mono text-12 text-text-faint" data-testid="chart-tab-empty">
          nothing to plot for this locator at {params.asof || 'this as-of'}
        </div>
      ) : (
        <SeriesChart series={q.data} asof={params.asof} axis={params.axis} />
      )}
    </div>
  );
}
