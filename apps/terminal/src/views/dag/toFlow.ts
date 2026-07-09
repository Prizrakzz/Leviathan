import type { Edge, Node } from '@xyflow/react';
import type { components } from '@/api/types.gen';
import { CONF_W, firingActiveSet, layoutDag } from './layout';

type Topo = components['schemas']['GraphTopology'];
type GNode = components['schemas']['GraphNode'];

/** Data carried by a custom React Flow node (rendered by CascadeNode). */
export interface CascadeNodeData {
  label: string;
  kind: string;
  active: boolean;
  terminal: boolean;      // the contract node
  tracked: boolean;       // a cross-commodity hop into another loaded contract (clickable to swap)
  hiddenParents: number;  // upstream drivers not yet revealed → the `+n` expand badge
  [key: string]: unknown; // RF Node<Data> requires an index signature
}
export type CascadeRFNode = Node<CascadeNodeData>;
export interface CascadeEdgeData {
  sign: string | null;
  mechanism: string | null;
  confidence: string | null;
  active: boolean;
  [key: string]: unknown;
}
export type CascadeRFEdge = Edge<CascadeEdgeData>;

/** Human node text: the backend `label` (6.3) if present, else a safe de-underscore — a raw slug never
 *  renders as node text. */
export const nodeLabel = (n: GNode): string => (n.label as string | undefined) || n.id.replace(/_/g, ' ');

/** Parents (direct upstream drivers) of `id` from the fan-in edges. */
export function parentsOf(topo: Topo, id: string): string[] {
  return topo.edges.filter((e) => e.target === id && e.source !== id).map((e) => e.source);
}

/** The SEED visible set — the contract node + the drivers this answer actually lit (fired-regime matched
 *  ∪ trace drivers ∪ asof overlay). Empty firing → the contract + its top-confidence direct drivers
 *  (capped) so the map is never a lone node. */
export function seedVisible(topo: Topo, active: Set<string>, cap = 8): Set<string> {
  const s = new Set<string>([topo.contract]);
  for (const n of topo.nodes) if (active.has(n.id)) s.add(n.id);
  if (s.size <= 1) {
    const direct = topo.edges
      .filter((e) => e.target === topo.contract)
      .map((e) => topo.nodes.find((n) => n.id === e.source))
      .filter((n): n is GNode => !!n)
      .sort((a, b) => (CONF_W[b.confidence ?? ''] ?? 0) - (CONF_W[a.confidence ?? ''] ?? 0));
    for (const n of direct.slice(0, cap)) s.add(n.id);
  }
  return s;
}

/** Force `focus` into a visible set for full-surface / deep-link focus mode (W1.3). seedVisible caps at
 *  contract + firing + top-8, so a driver selected from OUTSIDE that cap (a deep upstream driver) is absent
 *  and can't be centered on. Adds the focus node and — so it renders CONNECTED, not floating — BFS-walks its
 *  OUTGOING edges toward the contract, stopping each branch at the first already-visible node. No-op
 *  (returns the SAME base ref) when focus is empty, unknown to the topo, or already visible. */
export function seedWithFocus(topo: Topo, base: Set<string>, focus?: string): Set<string> {
  if (!focus || base.has(focus) || !topo.nodes.some((n) => n.id === focus)) return base;
  const next = new Set(base);
  next.add(focus);
  const queue = [focus];
  const seen = new Set<string>([focus]);
  while (queue.length) {
    const cur = queue.shift()!;
    for (const e of topo.edges) {
      if (e.source !== cur || seen.has(e.target)) continue;
      seen.add(e.target);
      if (next.has(e.target)) continue;                     // reached the visible sub-graph — branch done
      next.add(e.target);
      queue.push(e.target);
    }
  }
  return next;
}

/** Expand: add a node's direct parents to the visible set (returns a NEW set). */
export function expandNode(topo: Topo, id: string, visible: Set<string>): Set<string> {
  const next = new Set(visible);
  for (const p of parentsOf(topo, id)) next.add(p);
  return next;
}

/** How many of a node's parents are still hidden → the `+n` badge (0 = fully expanded / no upstream). */
export function hiddenParentCount(topo: Topo, id: string, visible: Set<string>): number {
  return parentsOf(topo, id).filter((p) => !visible.has(p)).length;
}

const signClass = (s: string | null | undefined): string =>
  s === '+' ? 'stroke-pos' : s === '-' ? 'stroke-neg' : 'stroke-line';

/** Project a topology + firing + visible-set into React Flow nodes/edges, positioned by the existing dagre
 *  layout over the FILTERED sub-graph. Pure — unit-tested; the component only renders the result. */
export function toFlow(topo: Topo, active: Set<string>, visible: Set<string>): {
  nodes: CascadeRFNode[];
  edges: CascadeRFEdge[];
} {
  const sub: Topo = {
    ...topo,
    nodes: topo.nodes.filter((n) => visible.has(n.id)),
    edges: topo.edges.filter((e) => visible.has(e.source) && visible.has(e.target)),
  };
  const laid = layoutDag(sub, active);
  const nodes: CascadeRFNode[] = laid.nodes.map((ln) => ({
    id: ln.id,
    type: 'cascade',
    position: { x: ln.x - ln.w / 2, y: ln.y - ln.h / 2 },
    data: {
      label: nodeLabel(ln.node),
      kind: ln.node.kind,
      active: ln.active,
      terminal: ln.terminal,
      tracked: ln.node.kind === 'commodity' && !!(ln.node as { tracked?: boolean }).tracked,
      hiddenParents: hiddenParentCount(topo, ln.id, visible),
    },
  }));
  const edges: CascadeRFEdge[] = laid.edges.map((le, i) => ({
    // `#i` disambiguates PARALLEL edges (5 oilseed contracts fan two edges into soybean_oil/soybeans) —
    // React Flow requires unique edge ids or it drops a duplicate + warns (S2.1 fix).
    id: `${le.source}->${le.target}#${i}`,
    source: le.source,
    target: le.target,
    markerEnd: { type: 'arrowclosed' } as Edge['markerEnd'],
    className: le.active ? 'stroke-amber' : signClass(le.edge.sign as string | null),
    style: { strokeWidth: le.width },
    data: {
      sign: (le.edge.sign as string | null) ?? null,
      mechanism: (le.edge.mechanism as string | null) ?? null,
      confidence: (le.edge.confidence as string | null) ?? null,
      active: le.active,
    },
  }));
  return { nodes, edges };
}

export { firingActiveSet };
