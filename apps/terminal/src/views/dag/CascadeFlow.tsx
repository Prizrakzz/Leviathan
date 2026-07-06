import {
  Background,
  Handle,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { components } from '@/api/types.gen';
import {
  type CascadeEdgeData,
  type CascadeRFNode,
  expandNode,
  firingActiveSet,
  seedVisible,
  toFlow,
} from './toFlow';

type Topo = components['schemas']['GraphTopology'];

/** Custom node — OUR Tailwind styling (not React Flow defaults), matching the terminal palette. The whole
 *  body opens receipts; the `+n` badge reveals upstream drivers; a tracked hop's ↗ swaps to that contract. */
function CascadeNode({ data }: NodeProps<CascadeRFNode>) {
  const cls = data.terminal
    ? 'border-cyan text-cyan'
    : data.active
      ? 'border-amber bg-bg-2 text-amber'
      : 'border-line text-text-dim';
  return (
    <div className={`relative rounded border ${cls} bg-bg-1 px-2 py-1 font-mono text-11 leading-none`}>
      <Handle type="target" position={Position.Left} className="!h-1 !w-1 !border-0 !bg-transparent" />
      <span>{data.label}</span>
      {data.hiddenParents > 0 && (
        <button
          aria-label={`expand ${data.hiddenParents} upstream`}
          onClick={(e) => {
            e.stopPropagation();
            (data.onExpand as () => void)?.();
          }}
          className="ml-1.5 rounded-chip border border-line px-1 text-text-faint hover:border-cyan hover:text-cyan"
        >
          +{data.hiddenParents}
        </button>
      )}
      {data.tracked && (
        <button
          aria-label="open this contract"
          onClick={(e) => {
            e.stopPropagation();
            (data.onSwap as () => void)?.();
          }}
          className="ml-1 text-cyan hover:text-amber"
        >
          ↗
        </button>
      )}
      <Handle type="source" position={Position.Right} className="!h-1 !w-1 !border-0 !bg-transparent" />
    </div>
  );
}

const NODE_TYPES = { cascade: CascadeNode };

function CascadeInner({
  topo,
  firedRegimes,
  drivers,
  onNodeClick,
  onSwap,
  height,
}: {
  topo: Topo;
  firedRegimes?: { matched?: string[] }[];
  drivers?: string[];
  onNodeClick?: (id: string) => void;
  onSwap?: (id: string) => void;
  height: number;
}) {
  const active = useMemo(() => firingActiveSet(topo, firedRegimes, drivers), [topo, firedRegimes, drivers]);
  const [visible, setVisible] = useState<Set<string>>(() => seedVisible(topo, active));
  // re-seed when the answer (topo/firing) changes
  useEffect(() => setVisible(seedVisible(topo, active)), [topo, active]);

  const expand = useCallback((id: string) => setVisible((v) => expandNode(topo, id, v)), [topo]);
  const { nodes, edges } = useMemo(() => toFlow(topo, active, visible), [topo, active, visible]);
  const withHandlers = useMemo(
    () => nodes.map((n) => ({ ...n, data: { ...n.data, onExpand: () => expand(n.id), onSwap: () => onSwap?.(n.id) } })),
    [nodes, expand, onSwap],
  );

  const rf = useReactFlow();
  useEffect(() => {
    const t = setTimeout(() => rf.fitView({ padding: 0.2, duration: 200 }), 0);
    return () => clearTimeout(t);
  }, [visible, rf]);

  const [hover, setHover] = useState<CascadeEdgeData | null>(null);

  return (
    <div className="relative rounded-panel border border-line bg-bg-1" style={{ height }} data-testid="dag">
      <ReactFlow
        nodes={withHandlers}
        edges={edges}
        nodeTypes={NODE_TYPES}
        colorMode="dark"
        fitView
        nodesDraggable={false}
        minZoom={0.3}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, n) => onNodeClick?.(n.id)}
        onEdgeMouseEnter={(_, e) => setHover((e.data as CascadeEdgeData) ?? null)}
        onEdgeMouseLeave={() => setHover(null)}
      >
        <Background gap={16} color="var(--line)" />
      </ReactFlow>
      {hover?.mechanism && (
        <div className="pointer-events-none absolute left-2 top-2 z-10 max-w-sm rounded-chip border border-line bg-bg-0/90 p-2 font-sans text-12 text-text-dim">
          {hover.mechanism}
        </div>
      )}
    </div>
  );
}

/** The interactive causal map (6.3) — React Flow, seeded with this answer's cited drivers, click to expand
 *  upstream. LAZY-loaded (this module pulls @xyflow/react + dagre + its CSS into an async chunk). */
export default function CascadeFlow({
  topo,
  firedRegimes,
  drivers,
  onNodeClick,
  onSwap,
  height = 300,
}: {
  topo: Topo;
  firedRegimes?: { matched?: string[] }[];
  drivers?: string[];
  onNodeClick?: (id: string) => void;
  onSwap?: (id: string) => void;
  height?: number;
}) {
  return (
    <ReactFlowProvider>
      <CascadeInner
        topo={topo}
        firedRegimes={firedRegimes}
        drivers={drivers}
        onNodeClick={onNodeClick}
        onSwap={onSwap}
        height={height}
      />
    </ReactFlowProvider>
  );
}
