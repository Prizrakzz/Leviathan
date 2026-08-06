import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
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
