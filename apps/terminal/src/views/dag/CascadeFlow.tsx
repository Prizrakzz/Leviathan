import {
  Background,
  Controls,
  Handle,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useCallback, useEffect, useMemo, useState } from 'react';

/** P2 attach-from-graph: the current selection driving the ONE floating action bar (node or edge). */
type Selected =
  | { kind: 'node'; id: string; label: string }
  | { kind: 'edge'; source: string; target: string; sourceLabel: string; targetLabel: string; blurb: string | null };
import type { components } from '@/api/types.gen';
import {
  type CascadeEdgeData,
  type CascadeRFNode,
  expandNode,
  firingActiveSet,
  seedVisible,
  seedWithFocus,
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
    <div
      className={`relative rounded border ${cls} ${data.selected ? 'ring-1 ring-cyan ' : ''}bg-bg-1 px-2 py-1 font-mono text-11 leading-none`}
    >
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
  onSwap,
  height,
  fullSurface,
  focus,
  onNodeAttach,
  onEdgeAttach,
}: {
  topo: Topo;
  firedRegimes?: { matched?: string[] }[];
  drivers?: string[];
  onSwap?: (id: string) => void;
  height: number;
  fullSurface?: boolean;
  focus?: string;
  onNodeAttach?: (a: { driver_id: string; label: string }) => void;
  onEdgeAttach?: (a: { source: string; target: string; sourceLabel: string; targetLabel: string; blurb: string | null }) => void;
}) {
  const active = useMemo(() => firingActiveSet(topo, firedRegimes, drivers), [topo, firedRegimes, drivers]);
  const [visible, setVisible] = useState<Set<string>>(() => seedWithFocus(topo, seedVisible(topo, active), focus));
  // re-seed when the answer (topo/firing) OR the focus target changes
  useEffect(() => setVisible(seedWithFocus(topo, seedVisible(topo, active), focus)), [topo, active, focus]);

  const expand = useCallback((id: string) => setVisible((v) => expandNode(topo, id, v)), [topo]);
  const { nodes, edges } = useMemo(() => toFlow(topo, active, visible), [topo, active, visible]);

  // P2 attach-from-graph: one selection (node OR edge) drives one floating action bar. Opt-in — nothing
  // changes for a caller that passes neither callback. The chip WRITE lives in GraphTab (this component
  // stays presentational). Toggle-click, pane-click, or Esc deselects.
  const attachEnabled = !!(onNodeAttach || onEdgeAttach);
  const [sel, setSel] = useState<Selected | null>(null);
  const labelOf = useCallback(
    (id: string) => String(nodes.find((n) => n.id === id)?.data.label ?? id),
    [nodes],
  );
  useEffect(() => {
    if (!sel) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSel(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sel]);

  const withHandlers = useMemo(
    () => nodes.map((n) => ({
      ...n,
      data: {
        ...n.data,
        selected: sel?.kind === 'node' && sel.id === n.id,
        onExpand: () => expand(n.id),
        onSwap: () => onSwap?.(n.id),
      },
    })),
    [nodes, expand, onSwap, sel],
  );

  const rf = useReactFlow();
  // Whole-graph fit — the default. SUPPRESSED while a focus node is pinned (focus mode owns the viewport;
  // without this gate every expand would yank the camera off the focused node).
  useEffect(() => {
    if (focus) return;
    const t = setTimeout(() => rf.fitView({ padding: 0.2, duration: 200 }), 0);
    return () => clearTimeout(t);
  }, [visible, rf, focus]);
  // Focus mode — center on the pinned node (forced into `visible` by seedWithFocus). Deps are [focus, rf]
  // only, so expanding upstream in focus mode doesn't re-yank; the Controls fit button re-frames on demand.
  useEffect(() => {
    if (!focus) return;
    const t = setTimeout(() => rf.fitView({ nodes: [{ id: focus }], padding: 0.4, duration: 250 }), 0);
    return () => clearTimeout(t);
  }, [focus, rf]);

  const [hover, setHover] = useState<CascadeEdgeData | null>(null);

  return (
    <div
      className={`relative bg-bg-1 ${fullSurface ? 'h-full w-full' : 'rounded-panel border border-line'}`}
      style={fullSurface ? undefined : { height }}
      data-testid="dag"
    >
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
        onNodeClick={(_, n) => {
          if (!attachEnabled) return;
          setSel((cur) =>
            cur?.kind === 'node' && cur.id === n.id
              ? null
              : { kind: 'node', id: n.id, label: String(n.data.label) },
          );
        }}
        onEdgeClick={(_, e) => {
          if (!attachEnabled) return;
          const d = e.data as CascadeEdgeData | undefined;
          setSel((cur) =>
            cur?.kind === 'edge' && cur.source === e.source && cur.target === e.target
              ? null
              : { kind: 'edge', source: e.source, target: e.target, sourceLabel: labelOf(e.source),
                  targetLabel: labelOf(e.target), blurb: (d?.blurb ?? d?.mechanism ?? null) as string | null },
          );
        }}
        onPaneClick={() => setSel(null)}
        onEdgeMouseEnter={(_, e) => setHover((e.data as CascadeEdgeData) ?? null)}
        onEdgeMouseLeave={() => setHover(null)}
      >
        <Background gap={16} color="var(--line)" />
        {fullSurface && <Controls showInteractive={false} className="border border-line" />}
      </ReactFlow>
      {(hover?.blurb ?? hover?.mechanism) && (
        <div className="pointer-events-none absolute left-2 top-2 z-10 max-w-sm rounded-chip border border-line bg-bg-0/90 p-2 font-sans text-12 text-text-dim">
          {hover?.blurb ?? hover?.mechanism}
        </div>
      )}
      {/* P2: the ONE floating attach bar (top-right; the hover tooltip owns top-left, Controls bottom-left) */}
      {attachEnabled && sel && (
        <div
          className="absolute right-2 top-2 z-20 flex items-center gap-2 rounded-panel border border-cyan bg-bg-0/95 px-2 py-1 font-mono text-11 text-text-dim"
          data-testid="attach-bar"
        >
          <span className="max-w-[220px] truncate">
            {sel.kind === 'node' ? sel.label : `${sel.sourceLabel} → ${sel.targetLabel}`}
          </span>
          <button
            onClick={() => {
              if (sel.kind === 'node') onNodeAttach?.({ driver_id: sel.id, label: sel.label });
              else onEdgeAttach?.({ source: sel.source, target: sel.target, sourceLabel: sel.sourceLabel,
                                    targetLabel: sel.targetLabel, blurb: sel.blurb });
              setSel(null);
            }}
            className="rounded-chip border border-line px-2 py-0.5 text-cyan hover:border-cyan hover:bg-bg-2"
            data-testid="attach-btn"
            aria-label="attach as context"
          >
            + attach as context
          </button>
          <button aria-label="dismiss selection" onClick={() => setSel(null)} className="text-text-faint hover:text-neg">
            ✕
          </button>
        </div>
      )}
    </div>
  );
}

/** The interactive causal map (6.3) — React Flow, seeded with this answer's cited drivers, click to expand
 *  upstream. LAZY-loaded (this module pulls @xyflow/react + dagre + its CSS into an async chunk).
 *  D-TW-16 deleted two never-reached props: `onNodeClick` (a legacy hook — no call site passed it since the
 *  attach bar took over node clicks) and `showMinimap` (default false, never set, so the MiniMap import was
 *  pure chunk weight). `focus` is the survivor of that audit and now has a real caller: the receipts
 *  drawer's driver chips (ReceiptsDrawer -> openTab). */
export default function CascadeFlow({
  topo,
  firedRegimes,
  drivers,
  onSwap,
  height = 300,
  fullSurface = false,
  focus,
  onNodeAttach,
  onEdgeAttach,
}: {
  topo: Topo;
  firedRegimes?: { matched?: string[] }[];
  drivers?: string[];
  onSwap?: (id: string) => void;
  height?: number;
  /** W1.3 full-surface mode (P1.5 GraphTab / deep-link): h-full container + zoom Controls + focus centering.
   *  The ANCESTOR must provide a resolved height — a bare mount collapses to 0. */
  fullSurface?: boolean;
  /** Node id to centre on (full-surface only). Unknown/absent ids degrade to the whole-graph fit — see
   *  seedWithFocus, which no-ops rather than inventing a node. */
  focus?: string;
  /** P2 attach-from-graph (opt-in): fired by the floating action bar; the store write lives in the caller. */
  onNodeAttach?: (a: { driver_id: string; label: string }) => void;
  onEdgeAttach?: (a: { source: string; target: string; sourceLabel: string; targetLabel: string; blurb: string | null }) => void;
}) {
  return (
    <ReactFlowProvider>
      <CascadeInner
        topo={topo}
        firedRegimes={firedRegimes}
        drivers={drivers}
        onSwap={onSwap}
        height={height}
        fullSurface={fullSurface}
        focus={focus}
        onNodeAttach={onNodeAttach}
        onEdgeAttach={onEdgeAttach}
      />
    </ReactFlowProvider>
  );
}
