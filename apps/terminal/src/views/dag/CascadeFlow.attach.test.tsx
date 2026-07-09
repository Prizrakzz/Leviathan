import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { components } from '@/api/types.gen';
import CascadeFlow from './CascadeFlow';

// Stub React Flow: jsdom has no canvas/ResizeObserver; this test proves the SELECTION -> ACTION BAR ->
// callback contract, not RF rendering. Nodes/edges render as buttons that fire the real handlers.
vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ nodes, edges, onNodeClick, onEdgeClick, onPaneClick, children }: never) => (
    <div data-testid="rf">
      {(nodes as { id: string; data: { label: string } }[]).map((n) => (
        <button key={n.id} data-testid={`node-${n.id}`} onClick={(e) => (onNodeClick as CallableFunction)(e, n)}>
          {n.data.label}
        </button>
      ))}
      {(edges as { id: string; source: string; target: string; data: unknown }[]).map((e) => (
        <button key={e.id} data-testid={`edge-${e.id}`} onClick={(ev) => (onEdgeClick as CallableFunction)(ev, e)}>
          {e.id}
        </button>
      ))}
      <div data-testid="pane" onClick={onPaneClick as never} />
      {children}
    </div>
  ),
  ReactFlowProvider: ({ children }: { children: unknown }) => <>{children}</>,
  Background: () => null,
  Controls: () => null,
  MiniMap: () => null,
  Handle: () => null,
  Position: { Left: 'left', Right: 'right' },
  useReactFlow: () => ({ fitView: () => {} }),
}));

type Topo = components['schemas']['GraphTopology'];
const topo = {
  contract: 'corn',
  graph_version: 'v',
  nodes: [
    { id: 'corn', kind: 'contract', contract: 'corn', label: 'CBOT corn' },
    { id: 'drought', kind: 'hazard', contract: 'corn', label: 'drought' },
  ],
  edges: [{ source: 'drought', target: 'corn', edge_type: 'causes', sign: '+', mechanism: 'dryness cuts yield' }],
} as unknown as Topo;

describe('CascadeFlow attach-from-graph (P2)', () => {
  it('node click -> bar -> attach fires onNodeAttach; bar clears', async () => {
    const onNodeAttach = vi.fn();
    render(<CascadeFlow topo={topo} fullSurface onNodeAttach={onNodeAttach} />);
    await userEvent.click(screen.getByTestId('node-drought'));
    expect(screen.getByTestId('attach-bar')).toBeTruthy();
    await userEvent.click(screen.getByTestId('attach-btn'));
    expect(onNodeAttach).toHaveBeenCalledWith({ driver_id: 'drought', label: 'drought' });
    expect(screen.queryByTestId('attach-bar')).toBeNull();
  });

  it('edge click -> attach fires onEdgeAttach with labels + blurb fallback', async () => {
    const onEdgeAttach = vi.fn();
    render(<CascadeFlow topo={topo} fullSurface onEdgeAttach={onEdgeAttach} />);
    const edgeBtn = screen.getByTestId(/^edge-/);
    await userEvent.click(edgeBtn);
    await userEvent.click(screen.getByTestId('attach-btn'));
    expect(onEdgeAttach).toHaveBeenCalledWith({
      source: 'drought', target: 'corn', sourceLabel: 'drought', targetLabel: 'CBOT corn',
      blurb: 'dryness cuts yield',
    });
  });

  it('second click and pane click deselect; no callbacks => no attach UI at all', async () => {
    const onNodeAttach = vi.fn();
    const { unmount } = render(<CascadeFlow topo={topo} fullSurface onNodeAttach={onNodeAttach} />);
    await userEvent.click(screen.getByTestId('node-drought'));
    await userEvent.click(screen.getByTestId('node-drought')); // toggle off
    expect(screen.queryByTestId('attach-bar')).toBeNull();
    await userEvent.click(screen.getByTestId('node-drought'));
    await userEvent.click(screen.getByTestId('pane'));
    expect(screen.queryByTestId('attach-bar')).toBeNull();
    unmount();
    render(<CascadeFlow topo={topo} fullSurface />); // attach disabled
    await userEvent.click(screen.getByTestId('node-drought'));
    expect(screen.queryByTestId('attach-bar')).toBeNull();
  });
});
