import { useQuery } from '@tanstack/react-query';
import { getConvergence } from '@/api/client';
import { useAsOf } from '@/store/asof';
import { useUI } from '@/store/ui';
import { ConvergenceGrid } from './convergence/ConvergenceGrid';

/** Convergence heatmap landing (design §4.8) — the 31-contract × regime grid from GET /v1/convergence,
 *  colored by proximity-to-firing and pinned to the global as-of. Click a contract/cell to deep-dive. */
export function ConvergenceView() {
  const asof = useAsOf((s) => s.asof);
  const setContract = useUI((s) => s.setContract);
  const setView = useUI((s) => s.setView);

  const q = useQuery({
    queryKey: ['convergence', asof],
    queryFn: () => getConvergence(asof),
    staleTime: 60_000,
  });

  function pick(contract: string) {
    setContract(contract);
    setView('deep');
  }

  if (q.isLoading)
    return <div className="font-mono text-12 text-text-faint">loading convergence…</div>;
  if (q.isError || !q.data)
    return <div className="font-mono text-12 text-neg">could not load convergence.</div>;

  return <ConvergenceGrid rows={q.data.rows} asof={q.data.asof} onPick={pick} />;
}
