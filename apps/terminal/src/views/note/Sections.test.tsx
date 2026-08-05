import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { RespondResult, Section } from '@/api/schema';
import { Note } from './Note';
import { Sections } from './Sections';

const noop = () => {};

function noteResult(structured: RespondResult['structured']): RespondResult {
  return { answer: '', structured };
}

describe('Sections (P9-C per-kind renderer)', () => {
  it('renders every kind with its heading from the payload (no hardcoded English)', () => {
    const sections: Section[] = [
      { kind: 'mechanism', heading: 'Mechanism', body: 'Frost cuts the next crop.' },
      { kind: 'record', heading: 'The record', body: 'Stocks-to-use 0.36 going in.' },
      { kind: 'disagreement', heading: 'Where the record disagrees', body: '1975 spiked on an on-year crop.' },
      { kind: 'watch', heading: 'What to watch', body: 'Certified stocks into July.' },
    ];
    render(
      <div data-testid="w">
        <Sections sections={sections} resolved={{}} onOpen={noop} />
      </div>,
    );
    const el = screen.getByTestId('w');
    const heads = [...el.querySelectorAll('h5')].map((h) => h.textContent);
    expect(heads).toEqual(['Mechanism', 'The record', 'Where the record disagrees', 'What to watch']);
    expect(el.textContent).toContain('Frost cuts the next crop.');
    expect(el.textContent).not.toContain('##'); // headings are clean display text, never markers
  });

  it('disagreement renders as the amber callout card (the fork must look like a fork)', () => {
    render(
      <Sections
        sections={[{ kind: 'disagreement', heading: 'Where the record disagrees', body: 'The fork body.' }]}
        resolved={{}}
        onOpen={noop}
      />,
    );
    const card = screen.getByTestId('section-disagreement');
    expect(card.className).toContain('border-amber');
    expect(card.className).toContain('rounded-panel');
    expect(card.textContent).toContain('The fork body.');
  });

  it('record renders as the compact bordered card (v1 = styled prose, no table)', () => {
    render(
      <Sections
        sections={[{ kind: 'record', heading: 'The record', body: '- 1994: the nearby doubled' }]}
        resolved={{}}
        onOpen={noop}
      />,
    );
    const card = screen.getByTestId('section-record');
    expect(card.className).toContain('border-line');
    expect(card.className).toContain('bg-bg-1');
    expect(card.querySelector('table')).toBeNull();
    expect(card.textContent).toContain('the nearby doubled');
  });

  it('an UNKNOWN kind degrades to plain prose under its heading (open union, never blanks)', () => {
    render(
      <div data-testid="u">
        <Sections sections={[{ kind: 'lag', heading: 'Dated lags', body: 'Six to nine months out.' }]} resolved={{}} onOpen={noop} />
      </div>,
    );
    const el = screen.getByTestId('u');
    expect(el.querySelector('h5')?.textContent).toBe('Dated lags');
    expect(el.textContent).toContain('Six to nine months out.');
    expect(el.querySelector('.border-amber')).toBeNull(); // no callout minted for unknown kinds
  });

  it('an EMPTY heading (pre-prose section) renders body only, no heading element', () => {
    render(
      <div data-testid="e">
        <Sections sections={[{ kind: 'other', heading: '', body: 'Lead-in prose only.' }]} resolved={{}} onOpen={noop} />
      </div>,
    );
    const el = screen.getByTestId('e');
    expect(el.querySelector('h5')).toBeNull();
    expect(el.querySelector('h4')).toBeNull();
    expect(el.textContent).toContain('Lead-in prose only.');
  });
});

describe('Note fallback matrix (P9-C: sections win, mechanism stays the fallback)', () => {
  it('sections + mechanism: Sections wins and the flat mechanism is NOT double-rendered', () => {
    const r = noteResult({
      tldr: 'Headline.',
      mechanism: '## Old heading\nold flat body',
      sections: [{ kind: 'record', heading: 'The record', body: 'sectioned body' }],
    });
    render(<Note result={r} onOpenReceipts={noop} />);
    expect(screen.getByTestId('sections')).toBeTruthy();
    expect(screen.getByTestId('note').textContent).toContain('sectioned body');
    expect(screen.getByTestId('note').textContent).not.toContain('old flat body');
  });

  it('mechanism-only (old turn / flag off): the flat FormattedNote render, ## branch intact', () => {
    const r = noteResult({ tldr: 'Headline.', mechanism: '## Mechanism\nflat body renders' });
    render(<Note result={r} onOpenReceipts={noop} />);
    expect(screen.queryByTestId('sections')).toBeNull();
    expect(screen.getByTestId('note').textContent).toContain('flat body renders');
    expect(screen.getByTestId('note').querySelector('h5')?.textContent).toBe('Mechanism');
  });

  it('an EMPTY sections array falls back to mechanism (never a blank Why)', () => {
    const r = noteResult({ tldr: 'Headline.', mechanism: 'still the flat body', sections: [] });
    render(<Note result={r} onOpenReceipts={noop} />);
    expect(screen.queryByTestId('sections')).toBeNull();
    expect(screen.getByTestId('note').textContent).toContain('still the flat body');
  });

  it('structured null: Note renders nothing (the banners path owns that state)', () => {
    const { container } = render(<Note result={noteResult(null)} onOpenReceipts={noop} />);
    expect(container.firstChild).toBeNull();
  });
});

describe('D-RC response-contract shapes (flat mechanism branch, ANSWER_V2 off = serving reality)', () => {
  // A contract reshapes WHICH ## headings the mechanism string carries -- never the schema. The
  // flat FormattedNote branch must render every v1 plan subset without error and without blanks.
  const NL = String.fromCharCode(10);
  const mk = (...lines: string[]) => lines.join(NL);
  const SHAPES: Array<[string, string]> = [
    ['context_node (2 sections)', mk('## Mechanism', 'barley competes in feed.', '## What to watch', 'rations.')],
    ['ranking (3 sections)', mk('## Mechanism', 'metric: exports_mt MY2026 (PSD).', '## The record', 'Russia 47.5 MMT', '## What to watch', 'weather.')],
    ['enumeration (5 sections incl. Episodes)', mk('## Mechanism', 'channel.', '## The record', 'dated items.', '## Episodes', '- 2010: ban [E1]', '## Where the record disagrees', 'eras diverge.', '## What to watch', 'next ban.')],
    ['outlook (5 sections incl. Outlook)', mk('## Mechanism', 'chain.', '## The record', 'rows.', '## Where the record disagrees', 'fork.', '## What to watch', 'signals.', '## Outlook', 'balance of risks.')],
  ];
  for (const [label, mech] of SHAPES) {
    it(`renders ${label} without error, all headings present`, () => {
      const r = noteResult({ tldr: 'Headline.', mechanism: mech });
      render(<Note result={r} onOpenReceipts={noop} />);
      const note = screen.getByTestId('note');
      const heads = Array.from(note.querySelectorAll('h5')).map((h) => h.textContent);
      const expected = mech.split(NL).filter((l) => l.startsWith('## ')).map((l) => l.slice(3));
      expect(heads).toEqual(expected);
      expect(note.textContent && note.textContent.length > 0).toBe(true);
    });
  }
});
