import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MOCK_RESULT, numbersOnlyResult } from '@/api/mock';
import type { TurnState } from '@/api/useTurn';
import { useUI } from '@/store/ui';
import { AnswerView } from './AnswerView';

vi.mock('@/api/client', () => ({
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

// settled flips via useTypewriter's 800ms drain timer in jsdom — give findBy headroom past DRAIN_MS.
const T = { timeout: 4000 };

describe('AnswerView graph chip + numbers rendering (P1.5: graph is TAB-ONLY, never inline)', () => {
  beforeEach(() => {
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('reasoning turn: NO inline map; the chip pushes a graph tab with the firing snapshot', async () => {
    mount(doneTurn(MOCK_RESULT), 'KC frost 2021');
    const chip = await screen.findByTestId('open-full-graph', undefined, T);
    expect(screen.queryByTestId('dag')).toBeNull(); // the graph never renders in the chat
    await userEvent.click(chip);
    const tabs = useUI.getState().tabs;
    expect(tabs).toHaveLength(1);
    expect(tabs[0]!.kind).toBe('graph');
    expect((tabs[0]!.params as { contract: string }).contract).toBe('arabica_coffee');
    expect((tabs[0]!.params as { drivers?: string[] }).drivers).toEqual(['frost', 'low_stocks']);
  });

  it('numbers_only turn: r.answer renders, chip renders, and NO no-match banner (W1.1.2/3)', async () => {
    const r = numbersOnlyResult('what were ending stocks', '2024-06-01');
    mount(doneTurn(r), 'what were ending stocks');
    expect(await screen.findByTestId('numbers-answer', undefined, T)).toBeTruthy();
    expect(await screen.findByTestId('open-full-graph', undefined, T)).toBeTruthy();
    expect(screen.queryByText(/No tracked contract matched/i)).toBeNull();
  });

  it('P9-C: a sections-bearing result renders the per-kind view, disagreement as the amber callout', async () => {
    mount(doneTurn(MOCK_RESULT), 'KC frost 2021');
    expect(await screen.findByTestId('sections', undefined, T)).toBeTruthy();
    expect(screen.getByTestId('section-disagreement').className).toContain('border-amber');
    expect(screen.queryByTestId('dag')).toBeNull(); // sections never re-open an inline graph
  });

  it('P9-C fallback: a structured-null result keeps the banners path (no sections, no note)', async () => {
    const r = numbersOnlyResult('what were ending stocks', '2024-06-01');
    mount(doneTurn(r), 'what were ending stocks');
    await screen.findByTestId('numbers-answer', undefined, T);
    expect(screen.queryByTestId('sections')).toBeNull();
    expect(screen.queryByTestId('note')).toBeNull();
  });
});
