import { describe, expect, it } from 'vitest';
import graphArabica from '@/api/fixtures/graph.arabica.json';
import type { components } from '@/api/types.gen';
import { firingActiveSet } from './layout';
import { expandNode, hiddenParentCount, nodeLabel, parentsOf, seedVisible, seedWithFocus, toFlow } from './toFlow';

type Topo = components['schemas']['GraphTopology'];
const topo = graphArabica as unknown as Topo;

describe('toFlow (6.3 progressive disclosure)', () => {
  it('nodeLabel prefers the backend label, never emits a raw slug', () => {
    const contract = topo.nodes.find((n) => n.kind === 'contract')!;
    expect(nodeLabel(contract)).toBe('ICE arabica coffee');
    expect(nodeLabel({ id: 'crude_oil', kind: 'demand', contract: 'x' })).toBe('crude oil'); // no backend label → de-underscore
  });

  it('seeds to the contract + fired drivers only (a small readable set)', () => {
    const active = firingActiveSet(topo, [{ matched: ['frost', 'drought'] }], ['frost', 'drought']);
    const seed = seedVisible(topo, active);
    expect(seed.has('arabica_coffee')).toBe(true);
    expect(seed.has('frost')).toBe(true);
    expect(seed.has('drought')).toBe(true);
    expect(seed.size).toBeLessThan(topo.nodes.length); // NOT everything
  });

  it('with no firing, seeds the contract + capped top-confidence direct drivers (never a lone node)', () => {
    const seed = seedVisible(topo, new Set(), 8);
    expect(seed.has('arabica_coffee')).toBe(true);
    expect(seed.size).toBeGreaterThan(1);
    expect(seed.size).toBeLessThanOrEqual(9); // contract + <=8
  });

  it('seedWithFocus forces an out-of-cap node into the set, CONNECTED to the visible sub-graph', () => {
    const base = seedVisible(topo, new Set(), 8);
    // pick a node that seedVisible left out (a deep upstream driver)
    const hidden = topo.nodes.find((n) => !base.has(n.id) && n.kind !== 'commodity');
    if (!hidden) return; // fixture too small to hide anything; nothing to prove
    const withFocus = seedWithFocus(topo, base, hidden.id);
    expect(withFocus.has(hidden.id)).toBe(true);
    // connectivity: the focus node has at least one edge into the final visible set (never floats)
    const connected = topo.edges.some(
      (e) => (e.source === hidden.id && withFocus.has(e.target)) ||
             (e.target === hidden.id && withFocus.has(e.source)),
    );
    expect(connected).toBe(true);
  });

  it('seedWithFocus is a no-op (same ref) for empty, unknown, or already-visible focus', () => {
    const base = seedVisible(topo, new Set(), 8);
    expect(seedWithFocus(topo, base, undefined)).toBe(base);
    expect(seedWithFocus(topo, base, 'not_a_node')).toBe(base);
    expect(seedWithFocus(topo, base, topo.contract)).toBe(base);
  });

  it('expandNode reveals exactly a node\'s direct parents', () => {
    const target = topo.edges.find((e) => e.target !== topo.contract && e.source !== e.target);
    if (!target) return; // graph may be flat; skip
    const before = new Set([topo.contract, target.target]);
    const after = expandNode(topo, target.target, before);
    for (const p of parentsOf(topo, target.target)) expect(after.has(p)).toBe(true);
  });

  it('hiddenParentCount drops to 0 after expanding', () => {
    const withParents = topo.nodes.find((n) => parentsOf(topo, n.id).length > 0);
    if (!withParents) return;
    const vis = new Set([withParents.id]);
    expect(hiddenParentCount(topo, withParents.id, vis)).toBe(parentsOf(topo, withParents.id).length);
    expect(hiddenParentCount(topo, withParents.id, expandNode(topo, withParents.id, vis))).toBe(0);
  });

  it('toFlow filters to the visible set, colors signed edges, weights by confidence', () => {
    const active = firingActiveSet(topo, [{ matched: ['frost'] }], ['frost']);
    const vis = seedVisible(topo, active);
    const { nodes, edges } = toFlow(topo, active, vis);
    expect(nodes.length).toBe(vis.size);
    expect(nodes.every((n) => n.type === 'cascade' && typeof n.data.label === 'string')).toBe(true);
    // every edge is between two visible nodes
    expect(edges.every((e) => vis.has(e.source) && vis.has(e.target))).toBe(true);
    // the frost→contract edge is bullish (+) and high-confidence (thick); not "active" (an edge is active
    // only when BOTH endpoints are lit, and the contract node is never in the active set — matches layout.ts)
    const frostEdge = edges.find((e) => e.source === 'frost' && e.target === 'arabica_coffee');
    expect(frostEdge).toBeTruthy();
    expect(frostEdge!.className).toBe('stroke-pos'); // bullish sign color
    expect((frostEdge!.style as { strokeWidth: number }).strokeWidth).toBeGreaterThan(2);
  });

  it('a non-active bullish edge gets the positive color, bearish gets negative', () => {
    const vis = new Set(topo.nodes.map((n) => n.id)); // everything visible, nothing active
    const { edges } = toFlow(topo, new Set(), vis);
    const pos = edges.find((e) => e.data?.sign === '+');
    const neg = edges.find((e) => e.data?.sign === '-');
    if (pos) expect(pos.className).toBe('stroke-pos');
    if (neg) expect(neg.className).toBe('stroke-neg');
  });

  // S2.1: 5 oilseed contracts fan PARALLEL edges into soybean_oil/soybeans; `${src}->${tgt}` collided,
  // dropping a duplicate + warning in React Flow. The `#i` suffix makes every edge id unique.
  it('gives parallel edges unique ids (no React Flow key collision)', () => {
    const parallel = {
      contract: 'c',
      nodes: [
        { id: 'c', kind: 'contract', contract: 'c' },
        { id: 'a', kind: 'demand', contract: 'c' },
      ],
      edges: [
        { source: 'a', target: 'c', sign: '+', confidence: 'high' },
        { source: 'a', target: 'c', sign: '-', confidence: 'low' }, // parallel edge, same endpoints
      ],
    } as unknown as Topo;
    const { edges } = toFlow(parallel, new Set(), new Set(['c', 'a']));
    const ids = edges.map((e) => e.id);
    expect(edges.length).toBe(2);
    expect(new Set(ids).size).toBe(ids.length); // all unique
  });
});
