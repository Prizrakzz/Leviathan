/**
 * F7 SKEPTIC — the reveal, at the real AnswerView.
 *
 * The two things that can only be proven here, above the component boundary:
 *   1. THE CITATION RULE end to end. The streamed draft is PRE-VERIFIER (strips p50 1, p90 7, max 16), so
 *      while the turn is streaming every `[n]` must render inert — visible, not clickable. Nothing a user
 *      could click may ever disappear.
 *   2. THE FEED SURVIVES THE SETTLE. AnswerView renders the reveal in branches; if the findings feed sits
 *      at a different child slot in two of them, React unmounts and remounts it — replaying every row's
 *      enter animation at the exact moment the answer lands. Asserted on DOM node identity, not on markup.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MOCK_RESULT } from '@/api/mock';
import { parsePartial, reduceFindings, type Findings } from '@/api/partials';
import type { StageEvent } from '@/api/schema';
import { emptyTurn, type TurnState } from '@/api/useTurn';
import { AnswerView } from './AnswerView';

// the typewriter reveals at ~2 chars/frame and force-settles at 800ms — give findBy headroom past both
const T = { timeout: 4000 };

vi.mock('@/api/client', () => ({
  getThreadTurns: () => Promise.resolve({ turns: [] }),
  suggest: () => Promise.resolve({ suggestions: [] }),
}));

/** The synthesis streams partial TOOL-INPUT JSON, not prose — StreamingNote pulls tldr/mechanism out of it. */
const DRAFT = JSON.stringify({
  tldr: 'A July frost in an off-year compounds a thin buffer [1].',
  mechanism: 'Frost kills buds [2], and stocks were already low [N1].',
});

function withFindings(turn: TurnState, events: object[]): TurnState {
  let f: Findings = turn;
  for (const e of events) {
    const p = parsePartial(e as StageEvent);
    if (p) f = reduceFindings(f, p);
  }
  return f as TurnState;
}

const ENGINE_EVENTS = [
  { stage: 'plan', intent: 'hybrid', contracts: ['arabica_coffee'] },
  { stage: 'walk', nodes: 7, depth: 3 },
  { stage: 'evidence', node: 'driver:arabica_coffee:frost', kept: 12 },
  {
    stage: 'regime',
    contract: 'arabica_coffee',
    regime: 'frost_squeeze',
    direction: '+',
    basis: { frost: { date: '2021-07-20', source: 'usda_gain_coffee' } },
  },
  { stage: 'number', table: 'silver_psd', metric: 'su_ratio', value: '0.36', unit: null, asof: '2021-06-11' },
];

function mount(turn: TurnState) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = (t: TurnState) => (
    <QueryClientProvider client={qc}>
      <AnswerView turn={t} question="KC frost convexity 2021" onAsk={() => {}} />
    </QueryClientProvider>
  );
  const r = render(ui(turn));
  return { ...r, show: (t: TurnState) => r.rerender(ui(t)) };
}

describe('F7 reveal at AnswerView', () => {
  it('streaming: findings render, and every citation handle is INERT', async () => {
    const streaming = withFindings({ ...emptyTurn('streaming'), draft: DRAFT }, ENGINE_EVENTS);
    mount(streaming);

    // the engines' work is on screen while the writer is still writing
    expect(screen.getByTestId('findings-feed')).toBeInTheDocument();
    expect(screen.getAllByTestId('finding-row')).toHaveLength(5);
    expect(screen.getByTestId('findings-summary')).toHaveTextContent('1 regime');
    expect(screen.getByTestId('findings-summary')).toHaveTextContent('12 props kept');
    // the verifier has not run, so it has no number to show yet
    expect(screen.queryByTestId('findings-strips')).toBeNull();

    // ...and the draft's handles are markers, not receipts. The typewriter reveals the draft over ~1s
    // (rAF, ~2 chars/frame), so wait for the tail rather than asserting on an empty first paint.
    const draft = await screen.findByTestId('note-draft', undefined, T);
    // handles appear one at a time as the text reveals — wait for the whole draft, then assert on all three
    await waitFor(() => expect(screen.getAllByTestId('cite-inert')).toHaveLength(3), T);
    expect([...draft.querySelectorAll('[data-testid="cite-inert"]')].map((e) => e.textContent)).toEqual([
      '[1]',
      '[2]',
      '[N1]',
    ]);
    expect(draft.querySelectorAll('button')).toHaveLength(0); // NOTHING clickable pre-verify
  });

  it('a verified stage mid-stream shows the strip count but still activates NOTHING', async () => {
    // `verified` sets citationsLive before the terminal `result` arrives. Activation also needs a resolved
    // map, which only `result` can supply — this is what makes passing `live` through the reveal safe.
    const mid = withFindings({ ...emptyTurn('streaming'), draft: DRAFT }, [
      ...ENGINE_EVENTS,
      { stage: 'drafting' },
      { stage: 'verified', strips: 7 },
    ]);
    expect(mid.citationsLive).toBe(true);
    mount(mid);
    expect(screen.getByTestId('findings-strips')).toHaveTextContent('7 stripped');
    expect(screen.getByTestId('findings-feed')).toHaveAttribute('data-open', 'false'); // writer has the floor
    const draft = await screen.findByTestId('note-draft', undefined, T);
    await screen.findByText(/stocks were already low/, undefined, T);
    expect(draft.querySelectorAll('button')).toHaveLength(0);
    expect(screen.getAllByTestId('cite-inert').length).toBeGreaterThan(0);
  });

  it('the settle keeps the SAME feed node — no remount, no animation replay', async () => {
    const streaming = withFindings({ ...emptyTurn('streaming'), draft: DRAFT }, ENGINE_EVENTS);
    const { show } = mount(streaming);
    await screen.findByTestId('note-draft', undefined, T);
    const feed = screen.getByTestId('findings-feed');
    const firstRow = screen.getAllByTestId('finding-row')[0];

    // the terminal result lands: status done, citations live, the typewriter still draining
    const done = withFindings({ ...streaming, status: 'done', citationsLive: true, result: MOCK_RESULT }, [
      { stage: 'verified', strips: 2 },
    ]);
    show(done);

    expect(screen.getByTestId('findings-feed'), 'the feed REMOUNTED on settle').toBe(feed);
    expect(screen.getAllByTestId('finding-row')[0]).toBe(firstRow);
    expect(screen.getByTestId('findings-strips')).toHaveTextContent('2 stripped');
  });

  it('the final answer keeps the findings on screen, one click away', async () => {
    const done = withFindings(
      { ...emptyTurn('done'), draft: DRAFT, citationsLive: true, result: MOCK_RESULT },
      [...ENGINE_EVENTS, { stage: 'drafting' }, { stage: 'verified', strips: 2 }],
    );
    mount(done);
    // the typewriter drains (800ms) and the verified Note swaps in; the feed is still there, collapsed
    await screen.findByTestId('open-full-graph', undefined, T);
    expect(screen.getByTestId('findings-feed')).toBeInTheDocument();
    expect(screen.getByTestId('findings-feed')).toHaveAttribute('data-phase', 'verified');
    expect(screen.getAllByTestId('finding-row')).toHaveLength(5);
  });

  it('a server that emits NO partials leaves the view exactly as it was', async () => {
    mount({ ...emptyTurn('streaming'), draft: DRAFT });
    expect(screen.queryByTestId('findings-feed')).toBeNull();
    expect(await screen.findByTestId('note-draft', undefined, T)).toBeInTheDocument();
    expect(screen.queryByTestId('findings-feed')).toBeNull();
  });
});
