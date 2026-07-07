import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TurnState } from '@/api/useTurn';
import { useSession } from '@/store/session';
import { useThread } from '@/store/thread';
import { useUI } from '@/store/ui';

// P1.3 map-render precondition: the causal map mounts only when a turn resolves BOTH a contract AND a
// `structured` payload (AnswerView.tsx: graphQ enabled on `!!shownContract && !!r.structured`, and the map
// renders inside `r.structured ? (... graphQ.data ? <CascadeFlow/> : null)`). Rerouting a regime-count
// question numbers_only -> reasoning/hybrid is exactly what makes structured non-null, so this test pins the
// invariant the reroute depends on. The heavy children are stubbed so the test targets ONLY the mount gate.
const { getGraph, getThreadTurns, suggest } = vi.hoisted(() => ({
  getGraph: vi.fn(),
  getThreadTurns: vi.fn(),
  suggest: vi.fn(),
}));
vi.mock('@/api/client', () => ({ getGraph, getThreadTurns, suggest }));
vi.mock('./note/useTypewriter', () => ({
  useTypewriter: (draft: string) => ({ shown: draft, settled: true }), // settle at once — timing isn't under test
}));
vi.mock('./dag/CascadeFlow', () => ({ default: () => <div data-testid="dag" /> })); // stub the @xyflow map
vi.mock('./note/Note', () => ({
  Note: ({ afterTldr }: { afterTldr?: ReactNode }) => <div data-testid="note">{afterTldr}</div>,
}));
vi.mock('./numbers/Numbers', () => ({ Numbers: () => null }));
vi.mock('./note/Banners', () => ({ Banners: () => null }));
vi.mock('./note/IntegrityStrip', () => ({ IntegrityStrip: () => null }));
vi.mock('./receipts/ReceiptsDrawer', () => ({ ReceiptsDrawer: () => null }));
vi.mock('./answer/SuggestionChips', () => ({ SuggestionChips: () => null }));
vi.mock('@/shell/Composer', () => ({ Composer: () => null }));

import { AnswerView } from './AnswerView';

function turnWith(structured: unknown): TurnState {
  return {
    status: 'done',
    draft: 'Coffee reads bullish.',
    stages: [],
    error: null,
    result: {
      contract: 'arabica_coffee',
      contracts: ['arabica_coffee'],
      structured,
      asof: '2026-07-06',
      evidence: [],
      number_calls: [],
      trace: { fired_regimes: [], drivers: [] },
      intent: 'reasoning',
    },
  } as unknown as TurnState;
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('AnswerView causal-map mount gate (P1.3)', () => {
  beforeEach(() => {
    getGraph.mockReset().mockResolvedValue({ nodes: [], edges: [] });
    getThreadTurns.mockReset().mockResolvedValue({ turns: [] });
    suggest.mockReset().mockResolvedValue({ suggestions: [] });
    useSession.setState({ ready: true });
    useThread.setState({ threadId: 't1' });
    useUI.setState({ receiptsOpen: false });
  });

  it('mounts the map when the turn resolves a contract AND structured', async () => {
    const turn = turnWith({ tldr: 'Bullish into 2021.', mechanism: 'Frost.', sources: [] });
    wrap(<AnswerView turn={turn} question="how many weeks before the squeeze fires?" onAsk={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('dag')).toBeTruthy()); // graphQ resolved -> CascadeFlow mounted
    expect(getGraph).toHaveBeenCalledWith('arabica_coffee', '2026-07-06');
  });

  it('does NOT mount the map for a contract with no structured (the numbers_only shape)', async () => {
    const turn = turnWith(null); // contract present, structured null -> graphQ disabled, map gated off
    wrap(<AnswerView turn={turn} question="corn exports in 2023?" onAsk={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('conversation')).toBeTruthy());
    expect(screen.queryByTestId('dag')).toBeNull();
    expect(getGraph).not.toHaveBeenCalled(); // enabled: !!shownContract && !!r.structured
  });
});
