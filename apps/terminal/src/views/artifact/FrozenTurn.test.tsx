import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ getSeries: vi.fn() }));
vi.mock('@/api/client', () => ({ getSeries: h.getSeries }));

import type { FrozenSnapshot, RespondResult } from '@/api/schema';
import { NO_RECEIPTS_TITLE } from '@/views/note/CitationChip';
import { FrozenTurn } from './FrozenTurn';

// A fixture RespondResult shaped like the real thing: sections + a source ledger + the citation locators a
// [1]/[N1] handle resolves through (resolvedFor reads structured.sources joined to citations[].locator).
const RESULT: RespondResult = {
  answer: '',
  structured: {
    tldr: 'Frost into an off-year compounds a thin buffer. [1]',
    mechanism: '## Mechanism\nflat body',
    sections: [
      { kind: 'mechanism', heading: 'Mechanism', body: 'Frost cuts the next crop [1]' },
      { kind: 'record', heading: 'The record', body: 'Stocks-to-use 0.36 going in [N1]' },
    ],
    sources: [
      { ref: 1, source: 'USDA FAS GAIN Report', date: '2021-07-20', source_key: 's3://gain/kc' },
      { ref: 'N1', source: 'USDA PSD', date: '2021-06-11' },
    ],
  },
  citations: [
    { kind: 'evidence', id: 'E1', ref: 1, locator: { kind: 'doc', source_key: 's3://gain/kc', snippet: 'a damaging frost' } },
    { kind: 'number', id: 'N1', ref: 'N1', locator: { kind: 'number', table: 'silver_psd', metric: 'su_ratio' } },
  ],
  contract: 'arabica_coffee',
  trace: { graph_version: 'gdam15aa99cc' },
  asof: '2021-07-20',
};

const snap = (payload: RespondResult): FrozenSnapshot => ({
  id: 'frz-1',
  question: 'KC frost 2021 — what happened to the convexity setup?',
  asof: '2021-07-20',
  graph_version: 'gdam15aa99cc',
  created_at: '2026-08-06T09:00:00Z',
  payload,
});

describe('FrozenTurn (D-AM-15 read-only artifact/share reader)', () => {
  it('renders the frozen turn: question, sections, and the source ledger', () => {
    render(<FrozenTurn snapshot={snap(RESULT)} />);
    const el = screen.getByTestId('frozen-turn');
    expect(el.textContent).toContain('what happened to the convexity setup?');
    expect(screen.getByTestId('sections')).toBeTruthy();
    const heads = [...el.querySelectorAll('h5')].map((h) => h.textContent);
    expect(heads).toEqual(['Mechanism', 'The record']);
    expect(el.textContent).toContain('Frost cuts the next crop');
    expect(screen.getByTestId('frozen-sources').textContent).toContain('USDA FAS GAIN Report');
  });

  it('shows the pins that make it reproducible rather than merely old (asof + graph_version)', () => {
    render(<FrozenTurn snapshot={snap(RESULT)} />);
    const pins = screen.getByTestId('frozen-pins');
    expect(pins.textContent).toContain('as of 2021-07-20');
    expect(pins.textContent).toContain('gdam15aa99cc');
  });

  it('is READ-ONLY: every citation chip is visibly inert and says why (no receipts behind a freeze)', () => {
    render(<FrozenTurn snapshot={snap(RESULT)} />);
    const chips = screen.getAllByTestId('cite-chip');
    expect(chips.length).toBeGreaterThan(0);
    for (const c of chips) {
      expect(c).toHaveAttribute('aria-disabled', 'true');
      expect(c).toHaveAttribute('title', NO_RECEIPTS_TITLE);
    }
    // and the source ledger is not a receipts trigger either (the live Note's row is; this one is spans)
    expect(screen.getByTestId('frozen-sources').querySelector('button')).toBeNull();
  });

  it('falls back to the flat mechanism when a turn was frozen without sections', () => {
    const r: RespondResult = { ...RESULT, structured: { ...RESULT.structured, sections: [] } };
    render(<FrozenTurn snapshot={snap(r)} />);
    expect(screen.queryByTestId('sections')).toBeNull();
    expect(screen.getByTestId('frozen-turn').textContent).toContain('flat body');
  });

  it('a structured-null turn (floor / numbers-only) still renders its answer prose, never a blank note', () => {
    const r: RespondResult = { answer: '**Service notice.** evidence only', structured: null };
    render(<FrozenTurn snapshot={{ ...snap(r), graph_version: null, asof: null }} />);
    expect(screen.getByTestId('frozen-flat').textContent).toContain('Service notice.');
    expect(screen.getByTestId('frozen-pins').textContent).toContain('frozen 2026-08-06');
  });

  it('survives a payload-free snapshot instead of crashing the reader page', () => {
    const bare = { ...snap({ answer: '' } as RespondResult) };
    delete (bare as { payload?: unknown }).payload;
    render(<FrozenTurn snapshot={bare as FrozenSnapshot} />);
    expect(screen.getByTestId('frozen-turn').textContent).toContain('convexity setup');
  });
});

// ── D-UX-5: the artifact carried its numbers all along ─────────────────────────────────────────────
// `_freeze_artifact` stores the WHOLE RespondResult (no field filtering), so `number_calls` and `trace`
// have been in every saved item since D-AM-15 -- the reader simply never mounted them. These pin the two
// panels ON, the as-of they are pinned to, and the two states in which they must render nothing at all.

const ASOF = '2021-07-20';
const SESSION = '2021-07-19';

/** A curve read + the spread the answer computed over it: the highest-priority chart card (D-UX-3). */
const CURVE_LOOKUP = {
  ref: 'N1',
  handle: 'L1',
  status: 'ok',
  query: {
    table: 'silver_futures_eod',
    metric: 'settle',
    commodity: 'arabica_coffee',
    contract_month: '2021-09,2021-12',
    agg: 'latest',
  },
  rows: [
    { value: '178.5', contract_month: '2021-09' },
    { value: '181.2', contract_month: '2021-12' },
  ],
};
const SPREAD = {
  query: { table: 'compute_stat', metric: 'spread' },
  rows: [{ value: '2.7' }],
  status: 'ok',
  stat_provenance: { stat: 'spread', input_handles: ['L1'] },
};
/** A plain country-scoped lookup -- one NUMBERS row, no chart trigger of its own. */
const PSD_LOOKUP = {
  ref: 'N2',
  handle: 'L2',
  status: 'ok',
  query: { table: 'silver_psd', metric: 'su_ratio', commodity: 'arabica_coffee', country: 'Brazil' },
  rows: [{ value: '0.36', z: '-1.4' }],
};
const CURVE_SERIES = {
  table: 'silver_futures_eod',
  metric: 'settle',
  commodity: 'arabica_coffee',
  asof: ASOF,
  unit: 'US cents/lb',
  points: [
    { contract_month: '2021-09', value: '178.5', knowledge_date: SESSION },
    { contract_month: '2021-12', value: '181.2', knowledge_date: SESSION },
  ],
};

const WITH_NUMBERS: RespondResult = { ...RESULT, number_calls: [CURVE_LOOKUP, SPREAD, PSD_LOOKUP] };

function mountQ(snapshot: FrozenSnapshot, liveSeries?: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FrozenTurn snapshot={snapshot} {...(liveSeries === undefined ? {} : { liveSeries })} />
    </QueryClientProvider>,
  );
}

describe('FrozenTurn artifacts (D-UX-5) — a reopened turn carries its numbers and its charts', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(CURVE_SERIES);
  });

  it('re-renders the SAME [N] rows the live turn showed, straight out of the frozen payload', () => {
    mountQ(snap(WITH_NUMBERS));
    const panel = screen.getByTestId('numbers');
    // the ref, the metric and the value the answer stood on -- no fetch is needed for any of it
    expect(panel.textContent).toContain('[N2]');
    expect(panel.textContent).toContain('su_ratio');
    expect(panel.textContent).toContain('0.36');
    expect(panel.textContent).toContain('[N1]');
  });

  it('re-derives the SAME chart card the live turn earned, and draws it at the SNAPSHOT’s as-of', async () => {
    mountQ(snap(WITH_NUMBERS));
    // deriveChartCards is a pure function of number_calls + trace, so the frozen payload reproduces the
    // live turn's cards exactly -- here the curve the spread was computed across.
    expect(await screen.findByRole('img', { name: /settle curve/i })).toBeInTheDocument();
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(1));
    expect(h.getSeries.mock.calls[0]).toEqual([
      'silver_futures_eod',
      'settle',
      {
        commodity: 'arabica_coffee',
        country: undefined,
        asof: ASOF, // PIT: the FREEZE's as-of, never today
        contractMonth: '2021-09,2021-12',
        agg: 'latest',
      },
    ]);
  });

  it('expanding a frozen row reads the series AT THE FREEZE, country scope included', async () => {
    mountQ(snap(WITH_NUMBERS));
    await userEvent.click(screen.getByRole('button', { name: /\[N2\]/ }));
    await waitFor(() =>
      expect(h.getSeries).toHaveBeenCalledWith('silver_psd', 'su_ratio', {
        commodity: 'arabica_coffee',
        country: 'Brazil',
        asof: ASOF,
      }),
    );
  });

  it('a turn with NO numbers renders no panel and no empty frame', () => {
    mountQ(snap(RESULT));
    expect(screen.queryByTestId('frozen-series')).toBeNull();
    expect(screen.queryByTestId('numbers')).toBeNull();
    expect(screen.queryByTestId('chart-cards')).toBeNull();
    expect(h.getSeries).not.toHaveBeenCalled();
    expect(screen.getByTestId('frozen-turn').textContent).toContain('Frost cuts the next crop');
  });

  it('an UNPINNED freeze draws nothing rather than a current-vintage line under a frozen figure', () => {
    // getSeries drops an empty asof and the server then defaults to today: a panel here would silently
    // redraw the answer's figures against a graph and a vintage that have both moved on.
    const bare = { ...snap({ ...WITH_NUMBERS, asof: undefined }), asof: null };
    mountQ(bare);
    expect(screen.queryByTestId('frozen-series')).toBeNull();
    expect(h.getSeries).not.toHaveBeenCalled();
  });

  it('the PUBLIC share reader mounts neither: /v1/series is identity-gated', () => {
    // GET /v1/share is public, GET /v1/series is not -- so a signed-out reader would get a row of
    // "couldn't load this chart" instead of a note. The prose, the pins and the sources still render.
    mountQ(snap(WITH_NUMBERS), false);
    expect(screen.queryByTestId('frozen-series')).toBeNull();
    expect(h.getSeries).not.toHaveBeenCalled();
    expect(screen.getByTestId('frozen-pins').textContent).toContain('as of 2021-07-20');
    expect(screen.getByTestId('frozen-sources').textContent).toContain('USDA FAS GAIN Report');
  });
});
