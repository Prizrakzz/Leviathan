import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from '@/shell/ErrorBoundary';
import GraphTab from './GraphTab';

vi.mock('@/views/dag/CascadeFlow', () => ({ default: () => <div /> }));
const getGraph = vi.fn();
vi.mock('@/api/client', () => ({ getGraph: (...a: unknown[]) => getGraph(...a) }));

// OWN FILE on purpose: a rejected getGraph leaves a late-detected rejection that vitest attributes to
// whichever test is running when detection lands. As the only test here, the file completes first
// (probe-verified deterministic); merged into GraphTab.test.tsx it kills a sibling test instead.
describe('GraphTab error path (P1.5 T2)', () => {
  it('a dead contract shows the retry state, never a crash (stale persisted tab)', async () => {
    getGraph.mockRejectedValue(new Error('404'));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ErrorBoundary fallback={<div data-testid="boundary-fallback" />}>
          <GraphTab params={{ contract: 'renamed_away', asof: '2026-07-01' }} />
        </ErrorBoundary>
      </QueryClientProvider>,
    );
    // isError branch renders (never the boundary, never a crash)
    expect(await screen.findByText(/could/i)).toBeTruthy();
    expect(screen.queryByTestId('boundary-fallback')).toBeNull();
  });
});
