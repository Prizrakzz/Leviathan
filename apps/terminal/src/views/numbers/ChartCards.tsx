import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useUI } from '@/store/ui';
import {
  type ChartCard,
  type ChartLocator,
  chartTitle,
  deriveChartCards,
  fetchSeries,
  seriesQueryKey,
} from './chartTriggers';
import { OverlayChart } from './OverlayChart';
import { curvePoints, parsePoints } from './scale';
import { SeriesChart } from './SeriesChart';

/** The card chrome: a title line that says WHY this chart is here, a collapse toggle, and (where a locator
 *  exists) the tab hand-off. The reason line is not decoration -- a chart that appears under an answer
 *  without saying which computation summoned it reads as the model having decided to draw something. */
function Card({
  card,
  action,
  children,
}: {
  card: ChartCard;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-panel border border-line bg-bg-1 p-2" data-testid="chart-card" data-kind={card.kind}>
      <div className="flex items-center gap-2">
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex-1 text-left font-mono text-11 text-text-dim hover:text-text"
        >
          {open ? '▾' : '▸'} {card.title}
          <span className="ml-2 text-text-faint">· {card.reason}</span>
        </button>
        {action}
      </div>
      {open && children}
    </div>
  );
}

function OpenInTab({ locator }: { locator: ChartLocator }) {
  return (
    <button
      data-testid="chart-card-open-tab"
      aria-label={`open ${chartTitle(locator)} in a tab`}
      onClick={() => useUI.getState().openTab({ kind: 'chart', title: chartTitle(locator), params: locator })}
      className="shrink-0 rounded-chip border border-line px-2 py-0.5 font-mono text-11 text-text-dim hover:border-cyan hover:text-cyan"
    >
      open in tab ↗
    </button>
  );
}

/** A card that FETCHES: curve and series cards are both a locator plus an axis, so they are one component.
 *  The fetch is pinned to the card's own as-of (the TURN's), and shares Numbers.tsx's key families, so the
 *  card draws the same rows the answer cited and costs nothing when the row was already expanded. */
function LocatorCard({ card }: { card: Extract<ChartCard, { locator: ChartLocator }> }) {
  const loc = card.locator;
  const q = useQuery({ queryKey: seriesQueryKey(loc), queryFn: () => fetchSeries(loc), staleTime: 60_000 });
  const pts = q.data ? parsePoints(q.data.points as Record<string, unknown>[]) : [];
  const drawable = loc.axis === 'curve' ? curvePoints(pts).length : pts.length;
  return (
    <Card card={card} action={<OpenInTab locator={loc} />}>
      {q.isError ? (
        <div className="py-0.5 font-mono text-11 text-text-faint">
          couldn’t load this chart —{' '}
          <button onClick={() => void q.refetch()} className="text-cyan hover:text-amber">
            retry
          </button>
        </div>
      ) : q.isLoading ? (
        <div className="py-0.5 font-mono text-11 text-text-faint">loading chart…</div>
      ) : !q.data || drawable < 2 ? (
        <div className="py-0.5 font-mono text-11 text-text-faint">nothing to plot at this as-of</div>
      ) : (
        <SeriesChart series={q.data} asof={loc.asof} axis={loc.axis} />
      )}
    </Card>
  );
}

/** The co-move pair card. It FETCHES NOTHING: its two legs are the rows the co-move engine injected into
 *  this very turn (see chartTriggers.comoveLegs -- World stocks-to-use is a cross-country synthesis with no
 *  stored row to read back), so the picture cannot drift from the answer even in principle.
 *
 *  That is also why it offers NO "open in tab": a chart tab is a LOCATOR, and these legs have none. Minting
 *  a plausible-looking one (silver_psd / su_ratio / country=World) would open a tab that either comes back
 *  empty or, worse, comes back with a per-country blob wearing the World label -- the exact mis-attribution
 *  the engine's own scope tag exists to prevent. The card says so in one line rather than offering a button
 *  that lies. */
function OverlayCard({ card }: { card: Extract<ChartCard, { kind: 'overlay' }> }) {
  return (
    <Card card={card}>
      <OverlayChart legs={card.legs} window={card.window} />
      <div className="font-mono text-11 text-text-faint" data-testid="overlay-no-tab">
        drawn from this turn’s own rows — a World stocks-to-use series is synthesized across countries, so
        there is no single series to open as a tab
      </div>
    </Card>
  );
}

/** D-UX-3: chart cards under a completed answer, triggered DETERMINISTICALLY from the turn itself.
 *
 *  Zero triggers -> `null`, i.e. ZERO bytes in the answer view: an answer whose legs computed nothing
 *  chartable renders exactly what it rendered before this wave. */
export function ChartCards({ result, asof }: { result: unknown; asof: string }) {
  const cards = useMemo(
    () => deriveChartCards(result as { number_calls?: unknown; trace?: unknown }, asof),
    [result, asof],
  );
  if (!cards.length) return null;
  return (
    <div className="space-y-2" data-testid="chart-cards">
      {cards.map((c) =>
        c.kind === 'overlay' ? <OverlayCard key={c.id} card={c} /> : <LocatorCard key={c.id} card={c} />,
      )}
    </div>
  );
}
