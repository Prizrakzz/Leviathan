import { useQuery } from '@tanstack/react-query';
import { getGraph } from '@/api/client';
import type { GraphTabParams } from '@/store/tabs';
import { useUI } from '@/store/ui';
import CascadeFlow from '@/views/dag/CascadeFlow';

/** A workspace graph tab (P1.5): the full-surface causal map. The DOCUMENT AREA supplies the resolved
 *  height (`flex-1 min-h-0` — CascadeFlow's fullSurface mode collapses to 0 in an unsized ancestor).
 *  Query key is IDENTICAL to AnswerView's graphQ family (['graph', contract, asof??'']) so "open full
 *  graph" from an answer is an instant cache hit, never a second /v1/graph fetch. */
export default function GraphTab({ params }: { params: GraphTabParams }) {
  const asof = params.asof ?? '';
  const graphQ = useQuery({
    queryKey: ['graph', params.contract, asof],
    queryFn: () => getGraph(params.contract, asof),
    staleTime: 300_000,
  });

  if (graphQ.isError)
    return (
      <div className="p-4 font-mono text-12 text-text-faint">
        couldn’t load this graph — the contract may have been renamed ·{' '}
        <button onClick={() => graphQ.refetch()} className="text-cyan hover:text-amber">
          retry
        </button>
      </div>
    );
  if (!graphQ.data)
    return <div className="h-full animate-pulse bg-bg-1" data-testid="graph-tab-loading" />;

  return (
    <div className="h-full w-full" data-testid="graph-tab">
      <CascadeFlow
        topo={graphQ.data}
        fullSurface
        focus={params.focus}
        firedRegimes={params.firedRegimes}
        drivers={params.drivers}
        onSwap={(id) =>
          // a tracked cross-commodity hop opens as its OWN tab (tabs are the graph surface now)
          useUI.getState().openTab({ kind: 'graph', title: id.replace(/_/g, ' '), params: { contract: id, asof: params.asof } })
        }
        // P2 attach-from-graph: the STORE write lives here (CascadeFlow stays presentational). The
        // backend resolver re-validates every id against the graph — these are gestures, not truth.
        onNodeAttach={({ driver_id, label }) =>
          useUI.getState().addChip({ type: 'node', contract: params.contract, driver_id, label })
        }
        onEdgeAttach={({ source, target, sourceLabel, targetLabel }) =>
          useUI.getState().addChip({
            type: 'edge', contract: params.contract, source, target,
            label: `${sourceLabel} → ${targetLabel}`,
          })
        }
      />
    </div>
  );
}
