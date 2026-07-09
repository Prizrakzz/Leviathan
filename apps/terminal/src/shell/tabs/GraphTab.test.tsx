import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from '@/shell/ErrorBoundary';
import GraphTab from './GraphTab';

// Stub the heavy map — this test asserts the tab's data plumbing (query key parity, error/loading states),
// not the DAG rendering (toFlow/layout unit tests own that).
vi.mock('@/views/dag/CascadeFlow', () => ({
  default: (p: { fullSurface?: boolean }) => (
    <div data-testid="cascade-stub" data-fullsurface={String(p.fullSurface)} />
  ),
}));

const getGraph = vi.fn();
vi.mock('@/api/client', () => ({ getGraph: (...a: unknown[]) => getGraph(...a) }));

function mount(params: { contract: string; asof?: string }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // The boundary mirrors production: GraphTab always renders inside TabDocument's per-tab ErrorBoundary.
  return render(
    <QueryClientProvider client={qc}>
      <ErrorBoundary fallback={<div data-testid="boundary-fallback" />}>
        <GraphTab params={params} />
      </ErrorBoundary>
    </QueryClientProvider>,
  );
}

// NB the dead-contract error-path case lives in GraphTab.error.test.tsx (own file): a rejected getGraph
// leaves a late-detected rejection that vitest attributes to whichever test is running when it lands —
// a single-test file provably completes before detection (probe-verified); co-located it flakes.

describe('GraphTab (P1.5 T2)', () => {
  beforeEach(() => getGraph.mockReset());

  it('fetches with the AnswerView-identical key shape (asof normalized to "") and mounts fullSurface', async () => {
    getGraph.mockResolvedValue({ contract: 'corn', graph_version: 'v', nodes: [], edges: [] });
    mount({ contract: 'corn' }); // no asof -> ''
    const stub = await screen.findByTestId('cascade-stub', undefined, { timeout: 4000 });
    expect(stub.getAttribute('data-fullsurface')).toBe('true');
    expect(getGraph).toHaveBeenCalledWith('corn', '');
  });
});
