import { useQuery } from '@tanstack/react-query';
import { getGraph } from '@/api/client';
import type { TurnState } from '@/api/useTurn';
import { Pipeline } from '@/shell/Pipeline';
import { useUI } from '@/store/ui';
import { CascadeDAG } from './dag/CascadeDAG';
import { Banners } from './note/Banners';
import { IntegrityStrip } from './note/IntegrityStrip';
import { Note } from './note/Note';
import { Numbers } from './numbers/Numbers';
import { ReceiptsDrawer } from './receipts/ReceiptsDrawer';

/** The Answer view (design §4.1) — the streamed pipeline → the assembled note (TL;DR/WHY) + live cascade
 *  DAG + vintage-marked numbers + integrity strip, with the receipts drawer docked and the §5 state
 *  banners on top. The trust loop. */
export function AnswerView({ turn }: { turn: TurnState }) {
  const r = turn.result;
  const receiptsOpen = useUI((s) => s.receiptsOpen);
  const setReceipts = useUI((s) => s.setReceipts);
  const contract = r?.contract ?? r?.contracts?.[0] ?? null;
  const asof = r?.asof ?? '';
  const graphQ = useQuery({
    queryKey: ['graph', contract, asof],
    queryFn: () => getGraph(contract as string, asof),
    enabled: !!contract && !!r?.structured,
    staleTime: 300_000,
  });

  if (turn.status === 'idle')
    return <div className="font-mono text-12 text-text-faint">ask a convexity question to begin.</div>;
  if (turn.status === 'streaming')
    return (
      <div className="rounded-panel border border-line bg-bg-1 p-3">
        <Pipeline stages={turn.stages} done={false} />
      </div>
    );
  if (turn.status === 'error') return <div className="font-mono text-12 text-neg">error: {turn.error}</div>;
  if (!r) return null;

  const trace = (r.trace ?? {}) as { fired_regimes?: { matched?: string[] }[]; drivers?: string[] };

  return (
    <div className="space-y-4">
      <Banners result={r} />

      {r.structured ? (
        <>
          <Note result={r} onOpenReceipts={() => setReceipts(true)} />
          {graphQ.data ? (
            <CascadeDAG
              topo={graphQ.data}
              firedRegimes={trace.fired_regimes}
              drivers={trace.drivers}
              onNodeClick={() => setReceipts(true)}
            />
          ) : r.structured.diagram_mermaid ? (
            <pre className="overflow-auto rounded-panel border border-line bg-bg-1 p-2 font-mono text-11 text-text-dim">
              {r.structured.diagram_mermaid}
            </pre>
          ) : null}
          <Numbers calls={r.number_calls ?? []} asof={asof} />
          <IntegrityStrip result={r} />
        </>
      ) : (
        (r.evidence?.length ?? 0) > 0 && (
          <button
            className="rounded-chip border border-line px-2 py-1 font-mono text-11 text-cyan hover:bg-bg-1"
            onClick={() => setReceipts(true)}
          >
            open receipts (e)
          </button>
        )
      )}

      <ReceiptsDrawer result={r} open={receiptsOpen} onClose={() => setReceipts(false)} />
    </div>
  );
}
