import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MOCK_RESULT, mockThreadTurns } from '@/api/mock';
import type { RespondResult } from '@/api/schema';
import type { components } from '@/api/types.gen';
import { emptyTurn, type TurnState } from '@/api/useTurn';
import { useSession } from '@/store/session';
import { useUI } from '@/store/ui';
import { AnswerView } from './AnswerView';
import { NO_RECEIPTS_TITLE } from './note/CitationChip';

type TurnRecord = components['schemas']['TurnRecord'];

/**
 * D-TW-23 -- citation chips were noop ON THE LIVE TURN, measured in authed prod: a single click on an [E5]
 * in the watch section and on a mechanism-area chip never opened the receipts drawer, while `e` did.
 *
 * The mechanism these tests pin down: ThreadSidebar invalidates `thread-turns` the moment a turn reports
 * `done`, the refetch pulls the just-answered turn into `past`, `showLive` goes false -- and the answer the
 * reader is looking at, mid-session, is a PastTurn render. PastTurn handed every chip a `noop`. `e` kept
 * working because the drawer hangs off `turn.result`, which is still in hand.
 *
 * So the regression that would have caught this needs the SETTLED state (past-turn list already carrying
 * the live question), not just a finalReady live Note -- which is why every previous chip test passed.
 */

const turns = vi.hoisted(() => ({ value: [] as unknown[] }));
vi.mock('@/api/client', () => ({
  getThreadTurns: () => Promise.resolve({ turns: turns.value }),
  suggest: () => Promise.resolve({ suggestions: [] }),
}));

/** A completed turn: citations are LIVE and `result` is still held by AnswerView after the settle. */
function doneTurn(result: RespondResult): TurnState {
  return { ...emptyTurn('done'), citationsLive: true, result };
}

function mount(turn: TurnState, question: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AnswerView turn={turn} question={question} onAsk={() => {}} />
    </QueryClientProvider>,
  );
}

const chipNamed = (scope: HTMLElement, label: string) =>
  within(scope)
    .getAllByTestId('cite-chip')
    .find((b) => b.textContent === label) as HTMLElement;

/** The durable copy of the mock turn, exactly as `getThreadTurns` returns it after the settle. */
const DURABLE = mockThreadTurns('t-mock1').turns[0] as unknown as TurnRecord;
const LIVE_Q = DURABLE.question as string;

/** PROD wire shape, which the mock fixture does NOT reproduce: a typed `[E5]` handle in the prose, a
 *  `structured.sources` ref numbered as a BARE INTEGER (answer.py forces an integer ref), and a citation
 *  carrying only `id: 'E5'` -- the serving `Citation` model (citations.py) has no `ref` field at all. The
 *  drawer must pin across that mismatch, or the fix delivers an unpinned drawer for the measured chip. */
const TYPED_RESULT: RespondResult = {
  ...MOCK_RESULT,
  structured: {
    ...MOCK_RESULT.structured,
    tldr: 'Typed-handle turn. [E5]',
    mechanism: '## What to watch\n- Certified stocks through the frost window [E5]',
    sections: [
      { kind: 'watch', heading: 'What to watch', body: '- Certified stocks through the frost window [E5]' },
    ],
    sources: [{ ref: 5, source: 'USDA WASDE', date: '2021-07-12', source_key: 's3://wasde/2021-07' }],
  },
  citations: [
    {
      kind: 'evidence',
      id: 'E5',
      source: 'usda_wasde',
      date: '2021-07-12',
      locator: { kind: 'doc', source_key: 's3://wasde/2021-07', snippet: 'WASDE snippet' },
    },
  ],
} as unknown as RespondResult;

const TYPED_DURABLE = {
  question: 'typed handle turn?',
  structured: TYPED_RESULT.structured,
  sources: TYPED_RESULT.citations,
  asof: '2021-07-20',
  contract: 'arabica_coffee',
  contracts: ['arabica_coffee'],
  ts: '2026-08-05T09:00:00Z',
} as unknown as TurnRecord;

describe('D-TW-23: the LIVE turn keeps clickable citation chips after it settles into `past`', () => {
  beforeEach(() => {
    useSession.setState({ ready: true });
    useUI.setState({ receiptsOpen: false, tabs: [], activeTabId: null });
    turns.value = [DURABLE];
  });

  it('THE REGRESSION: a chip inside a Sections-rendered block opens receipts pinned to its ref', async () => {
    mount(doneTurn(MOCK_RESULT), LIVE_Q);
    await screen.findByTestId('past-turn');
    // Precondition -- this is the settled state, not the live-Note state: the live block is gone (no <Note>),
    // and the answer on screen is the PastTurn render. Every earlier chip test asserted the OTHER branch,
    // which is exactly why the dead chip shipped.
    expect(screen.queryByTestId('note')).toBeNull();

    const chip = chipNamed(screen.getByTestId('sections'), '[2]');
    expect(chip).toBeTruthy();
    expect(chip.getAttribute('aria-disabled')).toBeNull(); // live: a real handler, not the noop

    await userEvent.click(chip);

    const drawer = await screen.findByTestId('receipts');
    // Pinned to the CLICKED ref: the cited list filters to that source's document and offers "show all".
    expect(screen.getByRole('button', { name: /pinned \[2\]/ })).toBeTruthy();
    expect(drawer.textContent).toContain('1 cited');
  });

  it('the TL;DR path on the same settled turn is live too (renderInline, not just Sections)', async () => {
    mount(doneTurn(MOCK_RESULT), LIVE_Q);
    const past = await screen.findByTestId('past-turn');
    const tldr = past.querySelector('p') as HTMLElement;

    await userEvent.click(chipNamed(tldr, '[1]'));

    expect(await screen.findByTestId('receipts')).toBeTruthy();
    expect(screen.getByRole('button', { name: /pinned \[1\]/ })).toBeTruthy();
  });

  it('the MEASURED shape -- a typed [E5] in the watch section -- opens AND pins on the prod wire shape', async () => {
    turns.value = [TYPED_DURABLE];
    mount(doneTurn(TYPED_RESULT), TYPED_DURABLE.question as string);
    await screen.findByTestId('past-turn');

    await userEvent.click(chipNamed(screen.getByTestId('sections'), '[E5]'));

    expect(await screen.findByTestId('receipts')).toBeTruthy();
    // The chip fires 'E5'; the receipt row's ref is 'E5' (citation.id, no `ref` on the wire). Exact match.
    expect(screen.getByRole('button', { name: /pinned \[E5\]/ })).toBeTruthy();
  });

  it('only the SETTLED LIVE turn is wired -- an earlier turn in the same thread degrades', async () => {
    const older = { ...DURABLE, question: 'an earlier question?', ts: '2026-08-05T08:00:00Z' } as TurnRecord;
    turns.value = [older, DURABLE];
    mount(doneTurn(MOCK_RESULT), LIVE_Q);
    const [olderTurn, liveTurn] = await screen.findAllByTestId('past-turn');
    expect(chipNamed(olderTurn!, '[2]').getAttribute('aria-disabled')).toBe('true');
    expect(chipNamed(liveTurn!, '[2]').getAttribute('aria-disabled')).toBeNull();
  });
});

describe('D-TW-23: a reopened thread degrades GRACEFULLY -- never a silent noop', () => {
  beforeEach(() => {
    useSession.setState({ ready: true });
    useUI.setState({ receiptsOpen: false, tabs: [], activeTabId: null });
    turns.value = [DURABLE];
  });

  it('chips say WHY they are inert and swallow no click (TurnRecord is PIT-firewalled: no evidence)', async () => {
    // No live turn at all: the thread was reopened from the sidebar, so `turn.result` is null and there is
    // no drawer to open. The chip must announce that rather than look live and do nothing.
    mount(emptyTurn('idle'), '');
    await screen.findByTestId('past-turn');

    const chip = chipNamed(screen.getByTestId('sections'), '[2]');
    expect(chip.getAttribute('aria-disabled')).toBe('true');
    expect(chip.getAttribute('title')).toBe(NO_RECEIPTS_TITLE);

    await userEvent.click(chip);
    expect(screen.queryByTestId('receipts')).toBeNull();
    expect(useUI.getState().receiptsOpen).toBe(false); // the click never even flipped the store
  });

  it('the durable receipt a past chip DOES hold still renders: the hover card keeps source + snippet', async () => {
    mount(emptyTurn('idle'), '');
    await screen.findByTestId('past-turn');
    // aria-disabled, not the `disabled` attribute -- a disabled button stops firing pointer events, which
    // would take the tooltip (a past turn's only receipt) down with the click.
    expect(chipNamed(screen.getByTestId('sections'), '[2]').hasAttribute('disabled')).toBe(false);
  });
});
