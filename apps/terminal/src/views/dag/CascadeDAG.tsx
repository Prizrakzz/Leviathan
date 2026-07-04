import { curveBasis, line as d3line } from 'd3-shape';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { components } from '@/api/types.gen';
import { firingActiveSet, layoutDag, type LaidEdge } from './layout';

type Topo = components['schemas']['GraphTopology'];

const pathGen = d3line<{ x: number; y: number }>()
  .x((p) => p.x)
  .y((p) => p.y)
  .curve(curveBasis);

const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA');
};

/** The live cascade DAG (design §4.2) — a hand-built directed graph (dagre layout + SVG), NOT a diagram
 *  lib. Nodes light amber when their regime fires at the as-of; edge thickness = confidence; hover an edge
 *  for its mechanism; click a node → Receipts + gauge; wheel/drag to pan-zoom; `f` to fit. */
export function CascadeDAG({
  topo,
  firedRegimes,
  drivers,
  onNodeClick,
  height = 320,
}: {
  topo: Topo;
  firedRegimes?: { matched?: string[] }[];
  drivers?: string[];
  onNodeClick?: (id: string) => void;
  height?: number;
}) {
  const active = useMemo(() => firingActiveSet(topo, firedRegimes, drivers), [topo, firedRegimes, drivers]);
  const layout = useMemo(() => layoutDag(topo, active), [topo, active]);
  const [t, setT] = useState({ k: 1, x: 0, y: 0 });
  const [hover, setHover] = useState<LaidEdge | null>(null);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const fit = () => setT({ k: 1, x: 0, y: 0 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'f' && !isTyping(e.target)) fit();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="relative rounded-panel border border-line bg-bg-1" data-testid="dag">
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        style={{ cursor: drag.current ? 'grabbing' : 'grab' }}
        onWheel={(e) => {
          const s = e.deltaY < 0 ? 1.1 : 0.9;
          setT((p) => ({ ...p, k: Math.max(0.4, Math.min(3, p.k * s)) }));
        }}
        onMouseDown={(e) => (drag.current = { x: e.clientX, y: e.clientY, ox: t.x, oy: t.y })}
        onMouseMove={(e) =>
          drag.current &&
          setT((p) => ({ ...p, x: drag.current!.ox + (e.clientX - drag.current!.x), y: drag.current!.oy + (e.clientY - drag.current!.y) }))
        }
        onMouseUp={() => (drag.current = null)}
        onMouseLeave={() => (drag.current = null)}
      >
        <defs>
          <marker id="arr" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" className="fill-line" />
          </marker>
          <marker id="arrOn" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" className="fill-amber" />
          </marker>
        </defs>
        <g transform={`translate(${t.x} ${t.y}) scale(${t.k})`}>
          {layout.edges.map((e, i) => (
            <path
              key={i}
              d={pathGen(e.points) ?? ''}
              fill="none"
              className={e.active ? 'stroke-amber' : 'stroke-line'}
              strokeWidth={e.width}
              opacity={e.active ? 1 : 0.7}
              markerEnd={`url(#${e.active ? 'arrOn' : 'arr'})`}
              onMouseEnter={() => setHover(e)}
              onMouseLeave={() => setHover(null)}
            />
          ))}
          {layout.nodes.map((n) => (
            <g
              key={n.id}
              transform={`translate(${n.x - n.w / 2} ${n.y - n.h / 2})`}
              style={{ cursor: 'pointer' }}
              onClick={() => onNodeClick?.(n.id)}
            >
              <rect
                width={n.w}
                height={n.h}
                rx={2}
                className={n.terminal || n.active ? 'fill-bg-2 stroke-amber' : 'fill-bg-1 stroke-line'}
                strokeWidth={n.terminal ? 1.6 : 1}
              />
              <text
                x={n.w / 2}
                y={n.h / 2 + 3.5}
                textAnchor="middle"
                className={
                  n.terminal || n.active ? 'fill-amber' : n.node.kind === 'commodity' ? 'fill-cyan' : 'fill-text-dim'
                }
                style={{ font: '11px "IBM Plex Mono", monospace' }}
              >
                {n.id}
              </text>
            </g>
          ))}
        </g>
      </svg>

      {hover && (
        <div className="pointer-events-none absolute left-2 top-2 max-w-sm rounded-chip border border-line bg-bg-0/90 p-2 font-mono text-11 text-text-dim">
          <span className="text-text">
            {hover.source} → {hover.target}
          </span>{' '}
          · {String(hover.edge.confidence ?? '?')} conf
          {hover.edge.mechanism ? <div className="mt-1 font-sans text-12">{String(hover.edge.mechanism)}</div> : null}
        </div>
      )}
      <button
        onClick={fit}
        aria-label="fit graph"
        className="absolute right-2 top-2 rounded-chip border border-line px-1.5 font-mono text-11 text-text-faint hover:text-cyan"
      >
        f
      </button>
    </div>
  );
}
