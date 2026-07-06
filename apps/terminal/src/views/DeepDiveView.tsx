import { useQuery } from '@tanstack/react-query';
import { getEvents, getGraph, getRegimes } from '@/api/client';
import { useAsOf } from '@/store/asof';
import { useSession } from '@/store/session';
import { useUI } from '@/store/ui';
import { CascadeDAG } from './dag/CascadeDAG';
import { ConvexityGauge } from './dag/ConvexityGauge';
import { DriverSignals } from './deep/DriverSignals';
import { EventsRail } from './deep/EventsRail';
import { activeDriverIds, firedRegimeOverlay, orderRegimes } from './deep/order';

/** Commodity deep-dive (design §3.2) — the full causal DAG (firing overlay), every regime gauge, driver
 *  coverage, and the live event rail for the active contract, all pinned to the global as-of. */
export function DeepDiveView() {
  const contract = useUI((s) => s.contract);
  const setView = useUI((s) => s.setView);
  const asof = useAsOf((s) => s.asof);
  // P7-P0.3: graph/regimes/events are auth-gated — gate on session readiness so nothing fires
  // before the OIDC token restores (silent-401-never-refetched class).
  const ready = useSession((s) => s.ready);

  const graphQ = useQuery({
    queryKey: ['graph', contract, asof],
    queryFn: () => getGraph(contract as string, asof),
    enabled: ready && !!contract,
    staleTime: 300_000,
  });
  const regQ = useQuery({
    queryKey: ['regimes', contract, asof],
    queryFn: () => getRegimes(contract as string, asof),
    enabled: ready && !!contract,
    staleTime: 60_000,
  });
  const evQ = useQuery({
    queryKey: ['events', contract, asof],
    queryFn: () => getEvents(contract as string, asof),
    enabled: ready && !!contract,
    staleTime: 60_000,
  });

  if (!contract)
    return (
      <div className="flex h-full flex-col items-center justify-center text-center" data-testid="deep-empty">
        <div className="font-mono text-11 uppercase tracking-wider text-text-dim">deep-dive</div>
        <p className="mt-2 max-w-md font-sans text-14 text-text-dim">
          No contract selected. Pick one from the{' '}
          <button className="font-mono text-cyan hover:underline" onClick={() => setView('convergence')}>
            convergence heatmap
          </button>
          .
        </p>
      </div>
    );

  const reg = regQ.data;
  const regimes = reg ? orderRegimes(reg.regimes) : [];

  return (
    <div className="space-y-4" data-testid="deep-dive">
      <div className="flex items-baseline justify-between">
        <div className="font-mono text-18 text-amber">{contract}</div>
        <div className="font-mono text-11 text-text-faint">as of {asof}</div>
      </div>

      {graphQ.data ? (
        <CascadeDAG
          topo={graphQ.data}
          firedRegimes={reg ? firedRegimeOverlay(reg.regimes) : undefined}
          drivers={reg ? activeDriverIds(reg.drivers) : undefined}
        />
      ) : graphQ.isLoading ? (
        <div className="font-mono text-12 text-text-faint">loading graph…</div>
      ) : (
        <div className="font-mono text-12 text-neg">no graph for {contract}.</div>
      )}

      {regimes.length > 0 && (
        <div className="flex flex-wrap gap-2" data-testid="gauges">
          {regimes.map((r) => (
            <ConvexityGauge key={r.name} regime={r} />
          ))}
        </div>
      )}

      {reg ? <DriverSignals drivers={reg.drivers} /> : null}
      {evQ.data ? <EventsRail feed={evQ.data} /> : null}
    </div>
  );
}
