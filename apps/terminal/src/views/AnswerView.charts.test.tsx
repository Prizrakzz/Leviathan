import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ getSeries: vi.fn() }));
vi.mock('@/api/client', () => ({
  getThreadTurns: () => Promise.resolve({ turns: [] }),
  suggest: () => Promise.resolve({ suggestions: [] }),
  getSeries: h.getSeries,
}));

import { MOCK_RESULT } from '@/api/mock';
import { emptyTurn, type TurnState } from '@/api/useTurn';
import { useUI } from '@/store/ui';
import { AnswerView } from './AnswerView';

const T = { timeout: 4000 }; // useTypewriter's drain timer gates `settled` in jsdom

const CURVE_SERIES = {
  table: 'silver_futures_eod',
  metric: 'settle',
  commodity: 'corn_cbot',
  asof: '2021-07-20',
  unit: 'US cents/bushel',
  points: [
    { contract_month: '2026-07', value: '417.5', knowledge_date: '2021-07-19' },
    { contract_month: '2026-12', value: '446.0', knowledge_date: '2021-07-19' },
  ],
};

/** MOCK_RESULT with a curve read and the spread stat computed over it -- the D-UX-3 curve trigger. */
const withCurve = {
  ...MOCK_RESULT,
  number_calls: [
    ...(MOCK_RESULT.number_calls ?? []),
    {
      ref: 'N4',
      handle: 'L1',
      status: 'ok',
      query: {
        table: 'silver_futures_eod',
        metric: 'settle',
        commodity: 'corn_cbot',
        contract_month: '2026-07,2026-12',
        agg: 'latest',
      },
      rows: [
        { value: '417.5', contract_month: '2026-07' },
        { value: '446.0', contract_month: '2026-12' },
      ],
    },
    {
      query: { table: 'compute_stat', metric: 'spread' },
      rows: [{ value: '28.5', unit: 'spread' }],
      status: 'ok',
      stat_provenance: { stat: 'spread', params: {}, input_handles: ['L1'] },
    },
  ],
};

function doneTurn(result: TurnState['result']): TurnState {
  return { ...emptyTurn('done'), citationsLive: true, result };
}

function mount(result: TurnState['result'], question: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AnswerView turn={doneTurn(result)} question={question} onAsk={() => {}} />
    </QueryClientProvider>,
  );
}

describe('AnswerView chart cards (D-UX-3)', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(CURVE_SERIES);
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('NO trigger -> zero cards, and the answer view is byte-identical to itself without them', async () => {
    // MOCK_RESULT computes no stat, reads no curve and fires no co-move leg. The guarantee is stronger than
    // "no cards are shown": ChartCards returns null, so it contributes NO DOM node at all -- which is what
    // makes the surrounding answer byte-for-byte what it rendered before this wave. The complementary pin
    // (an empty ChartCards renders the empty string) lives in numbers/ChartCards.test.tsx.
    const { container } = mount(MOCK_RESULT, 'KC frost 2021');
    await screen.findByTestId('sections', undefined, T);
    expect(screen.queryByTestId('chart-cards')).toBeNull();
    expect(screen.queryByTestId('chart-card')).toBeNull();
    expect(container.innerHTML).not.toContain('chart-card');
  });

  it('a spread over a curve read -> exactly one curve card under the answer', async () => {
    mount(withCurve, 'KC frost 2021');
    expect(await screen.findByTestId('chart-cards', undefined, T)).toBeInTheDocument();
    const cards = screen.getAllByTestId('chart-card');
    expect(cards).toHaveLength(1);
    expect(cards[0]!.getAttribute('data-kind')).toBe('curve');
    expect(await screen.findByRole('img', { name: /settle curve/i })).toBeInTheDocument();
  });

  it('the card is the ONLY thing the trigger adds -- the rest of the answer is unchanged', async () => {
    // Rendered side by side, the two answers differ ONLY inside the chart-cards subtree (and in the extra
    // NUMBERS rows the trigger calls are, which is the engine's own data, not this wave's chrome). This is
    // the surgical claim: the cards are appended, they do not rewrite the answer around them.
    const bare = mount(MOCK_RESULT, 'KC frost 2021');
    await screen.findByTestId('sections', undefined, T);
    const noteBefore = bare.container.querySelector('[data-testid="sections"]')!.innerHTML;
    bare.unmount();

    const withIt = mount(withCurve, 'KC frost 2021');
    await screen.findByTestId('chart-cards', undefined, T);
    const noteAfter = withIt.container.querySelector('[data-testid="sections"]')!.innerHTML;
    expect(noteAfter).toBe(noteBefore);
  });

  it('the card fetches at the TURN\'s as-of, not at today', async () => {
    mount(withCurve, 'KC frost 2021');
    await screen.findByTestId('chart-cards', undefined, T);
    expect(h.getSeries.mock.calls[0]![2]).toMatchObject({
      asof: MOCK_RESULT.asof,
      contractMonth: '2026-07,2026-12',
      agg: 'latest',
    });
  });
});
