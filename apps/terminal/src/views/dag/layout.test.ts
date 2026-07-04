import { describe, expect, it } from 'vitest';
import { MOCK_GRAPH } from '@/api/mock';
import { firingActiveSet, layoutDag } from './layout';

describe('DAG layout', () => {
  it('positions every node and routes edges with confidence-based width', () => {
    const active = firingActiveSet(MOCK_GRAPH, [{ matched: ['frost', 'low_stocks'] }], ['frost']);
    const laid = layoutDag(MOCK_GRAPH, active);
    expect(laid.nodes.length).toBe(MOCK_GRAPH.nodes.length);
    expect(laid.width).toBeGreaterThan(0);
    for (const n of laid.nodes) expect(Number.isFinite(n.x) && Number.isFinite(n.y)).toBe(true);
    // the contract node is the emphasized terminal
    expect(laid.nodes.find((n) => n.id === 'arabica_coffee')?.terminal).toBe(true);
    // a high-confidence edge is thicker than a low one
    const w = (id: string) => laid.edges.find((e) => e.source === id)?.width ?? 0;
    expect(w('frost')).toBeGreaterThan(0.8);
    // firing overlay lit the matched drivers
    expect(laid.nodes.find((n) => n.id === 'frost')?.active).toBe(true);
  });

  it('firingActiveSet unions fired-regime matched + trace drivers + node overlay', () => {
    const s = firingActiveSet(MOCK_GRAPH, [{ matched: ['a'] }], ['b']);
    expect(s.has('a') && s.has('b')).toBe(true);
  });
});
