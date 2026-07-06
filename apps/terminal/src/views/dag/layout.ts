import dagre from '@dagrejs/dagre';
import type { components } from '@/api/types.gen';

type Topo = components['schemas']['GraphTopology'];
type GNode = components['schemas']['GraphNode'];
type GEdge = components['schemas']['GraphEdge'];

export interface LaidNode {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  node: GNode;
  active: boolean;
  terminal: boolean;
}
export interface LaidEdge {
  source: string;
  target: string;
  points: { x: number; y: number }[];
  edge: GEdge;
  active: boolean;
  width: number;
}
export interface DagLayout {
  nodes: LaidNode[];
  edges: LaidEdge[];
  width: number;
  height: number;
}

/** Edge stroke width by the causal YAML confidence (design §4.2: thickness = confidence). */
export const CONF_W: Record<string, number> = { high: 2.6, medium: 1.5, low: 0.8 };

/** The set of driver/node ids lit at the as-of: those in a fired regime's `matched`, the trace `drivers`,
 *  or a node's `?asof=` firing overlay flag. */
export function firingActiveSet(
  topo: Topo,
  firedRegimes: { matched?: string[] }[] | undefined,
  drivers: string[] | undefined,
): Set<string> {
  const s = new Set<string>();
  for (const r of firedRegimes ?? []) for (const d of r.matched ?? []) s.add(d);
  for (const d of drivers ?? []) s.add(d);
  for (const n of topo.nodes) if ((n as { active?: boolean }).active) s.add(n.id);
  return s;
}

/** Lay out the cascade DAG left→right with dagre (crossing minimization), returning positioned nodes +
 *  routed edges. Pure — no DOM — so it unit-tests and memoizes per (contract, as-of). */
export function layoutDag(topo: Topo, active: Set<string>): DagLayout {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({ rankdir: 'LR', nodesep: 22, ranksep: 64, marginx: 14, marginy: 14 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const n of topo.nodes) {
    g.setNode(n.id, { width: Math.max(56, n.id.length * 7 + 16), height: 22 });
  }
  topo.edges.forEach((e, i) => {
    if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target, {}, `e${i}`);
  });
  dagre.layout(g);

  const nodes: LaidNode[] = topo.nodes.map((n) => {
    const gn = g.node(n.id);
    return {
      id: n.id,
      x: gn.x,
      y: gn.y,
      w: gn.width,
      h: gn.height,
      node: n,
      active: active.has(n.id),
      terminal: n.kind === 'contract',
    };
  });

  const edges: LaidEdge[] = [];
  topo.edges.forEach((e, i) => {
    if (!g.hasNode(e.source) || !g.hasNode(e.target)) return;
    const ge = g.edge(e.source, e.target, `e${i}`);
    edges.push({
      source: e.source,
      target: e.target,
      points: ge.points,
      edge: e,
      active: active.has(e.source) && active.has(e.target),
      width: CONF_W[(e.confidence ?? '') as string] ?? 1.1,
    });
  });

  const gg = g.graph();
  return { nodes, edges, width: gg.width ?? 400, height: gg.height ?? 300 };
}
