import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MOCK_RESULT, numbersOnlyResult } from '@/api/mock';
import type { TurnState } from '@/api/useTurn';
import { AnswerView } from './AnswerView';

// The lazy CascadeFlow chunk pulls @xyflow/react (ResizeObserver etc.) — stub it: these tests assert the
// MOUNT CONDITION CHAIN (graphQ → mapSlot → branch), not the DAG's own rendering (toFlow/layout unit tests
// cover that). The stub preserves the lazy-import seam.
vi.mock('./dag/CascadeFlow', () => ({
  default: () => <div data-testid="dag-stub" />,
}));

const getGraph = vi.fn();
vi.mock('@/api/client', () => ({
  getGraph: (...a: unknown[]) => getGraph(...a),
  getThreadTurns: () => Promise.resolve({ turns: [] }),
  suggest: () => Promise.resolve({ suggestions: [] }),
}));

function doneTurn(result: TurnState['result']): TurnState {
  return { status: 'done', stages: [], draft: '', result } as TurnState;
}

function mount(turn: TurnState, question: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AnswerView turn={turn} question={question} onAsk={() => {}} />
    </QueryClientProvider>,
  );
}

// settled flips via useTypewriter's 800ms drain timer in jsdom (rAF path may be throttled) — give findBy
// headroom past DRAIN_MS.
const T = { timeout: 4000 };

describe('AnswerView map-mount chain (W1.1/W1.2-FE)', () => {
  beforeEach(() => {
    getGraph.mockReset();
  });

  it('reasoning turn: graphQ resolves → CascadeFlow mounts inside the note', async () => {
    getGraph.mockResolvedValue({ contract: 'arabica_coffee', graph_version: 'v', nodes: [], edges: [] });
    mount(doneTurn(MOCK_RESULT), 'KC frost 2021');
    expect(await screen.findByTestId('dag-stub', undefined, T)).toBeTruthy();
    expect(getGraph).toHaveBeenCalledWith('arabica_coffee', MOCK_RESULT.asof);
  });

  it('graph fetch failure is VISIBLE, never a silent vanish (W1.1.1)', async () => {
    getGraph.mockRejectedValue(new Error('boom'));
    mount(doneTurn(MOCK_RESULT), 'KC frost 2021');
    // Before W1.1 the error surface lived INSIDE the data guard → a dead /v1/graph rendered nothing at all.
    expect(await screen.findByText(/causal map unavailable/i, undefined, T)).toBeTruthy();
    expect(screen.queryByTestId('dag-stub')).toBeNull();
  });

  it('numbers_only turn: map mounts, r.answer renders, and NO no-match banner (W1.1.2/3 + W1.2-FE)', async () => {
    getGraph.mockResolvedValue({ contract: 'arabica_coffee', graph_version: 'v', nodes: [], edges: [] });
    const r = numbersOnlyResult('what were ending stocks', '2024-06-01');
    mount(doneTurn(r), 'what were ending stocks');
    // the numbers markdown body — before W1.1.3 it rendered NOWHERE once the turn settled
    expect(await screen.findByTestId('numbers-answer', undefined, T)).toBeTruthy();
    // the map, keyed on the backend-resolved contract despite structured=null
    expect(await screen.findByTestId('dag-stub', undefined, T)).toBeTruthy();
    // and the wrong banner is gone
    expect(screen.queryByText(/No tracked contract matched/i)).toBeNull();
  });
});
