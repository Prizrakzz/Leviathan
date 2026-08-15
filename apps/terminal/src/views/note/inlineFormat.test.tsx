import * as Tooltip from '@radix-ui/react-tooltip';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FormattedNote, parseInline, renderInline } from './inlineFormat';
import { tokenizeCitations } from './citations';
import type { ResolvedMap } from './citations';

const resolved: ResolvedMap = { '1': { source: 'USDA WASDE', date: '2022-01-01', text: 'stocks tightened' } };

// The ACTUAL post-P9 served shape: TYPED prose handles ([E3]/[N4]) against a ledger keyed by the BARE
// INTEGER (verify.py keys report['resolved'] by the digit; answer.py forces the ledger ref to an integer).
// Pre-P9 prose was bare "[3]", so the old bare-key lookup matched by coincidence; the typed prose broke it.
const resolvedInt: ResolvedMap = {
  '3': {
    source: 'USDA WASDE',
    date: '2022-01-01',
    text: 'stocks tightened',
    locator: { kind: 'doc', source_key: 'text/wasde_2022_01.json', snippet: 'stocks tightened' },
  },
  '4': {
    source: 'USDA FAS',
    date: '2022-02-01',
    text: 'exports rose',
    locator: { kind: 'doc', source_key: 'text/fas_2022_02.json', snippet: 'exports rose' },
  },
};

describe('parseInline (6.1 markup subset)', () => {
  it('renders paired **bold** and *em*', () => {
    expect(parseInline('a **b** c', {})).toEqual([
      { k: 'text', v: 'a ' },
      { k: 'strong', v: [{ k: 'text', v: 'b' }] },
      { k: 'text', v: ' c' },
    ]);
    expect(parseInline('x *y* z', {})).toEqual([
      { k: 'text', v: 'x ' },
      { k: 'em', v: [{ k: 'text', v: 'y' }] },
      { k: 'text', v: ' z' },
    ]);
  });

  it('STRIPS an unpaired ** so a raw asterisk never reaches the DOM', () => {
    expect(parseInline('a ** b', {})).toEqual([{ k: 'text', v: 'a  b' }]);
    expect(parseInline('lone * star', {})).toEqual([{ k: 'text', v: 'lone  star' }]);
  });

  it('is streaming-safe: a trailing open **marker keeps the text, drops the marker', () => {
    expect(parseInline('hello **wor', {})).toEqual([{ k: 'text', v: 'hello wor' }]);
    expect(parseInline('tail *', {})).toEqual([{ k: 'text', v: 'tail ' }]);
  });

  it('resolves a citation to a chip token, leaves an unresolved [n] as text', () => {
    expect(parseInline('see [1] now', resolved)).toEqual([
      { k: 'text', v: 'see ' },
      { k: 'cite', ref: '1', resolved: resolved['1'] },
      { k: 'text', v: ' now' },
    ]);
    expect(parseInline('see [9] gone', resolved)).toEqual([{ k: 'text', v: 'see [9] gone' }]);
  });

  it('resolves TYPED evidence handles [E3][E4] against an INTEGER-keyed ledger (P9 contract)', () => {
    // The regression: served prose is "[E3]" but the ledger key is the bare digit "3". This FAILS on the
    // pre-fix matcher (it looked up resolved["E3"], missed, and left "[E3]" as literal text).
    const toks = parseInline('drought tightened [E3][E4]', resolvedInt);
    const cites = toks.filter((t) => t.k === 'cite');
    expect(cites.map((c) => (c as { ref: string }).ref)).toEqual(['E3', 'E4']); // display ref stays TYPED
    // the doc locator on the bare-digit entry flows through so CitationChip can mount its open-PDF button
    expect((cites[0] as { resolved: ResolvedMap[string] }).resolved.locator).toEqual(
      resolvedInt['3']!.locator,
    );
    expect(((cites[0] as { resolved: ResolvedMap[string] }).resolved.locator as { source_key: string }).source_key).toBe(
      'text/wasde_2022_01.json',
    );
  });

  it('still resolves a BARE legacy handle [3] against the same integer ledger (regression)', () => {
    expect(parseInline('legacy [3] cite', resolvedInt)).toEqual([
      { k: 'text', v: 'legacy ' },
      { k: 'cite', ref: '3', resolved: resolvedInt['3'] },
      { k: 'text', v: ' cite' },
    ]);
  });

  it('resolves a TYPED number handle [N4] and keeps the N ref (chip stays cyan/number)', () => {
    const numLedger: ResolvedMap = {
      '4': { source: 'USDA PSD', date: '2024', locator: { kind: 'number', table: 'silver_psd' } },
    };
    const toks = parseInline('ending stocks fell [N4]', numLedger);
    const cite = toks.find((t) => t.k === 'cite') as { ref: string; resolved: ResolvedMap[string] };
    expect(cite.ref).toBe('N4'); // /^[A-Za-z]/ ⇒ isNumber true ⇒ cyan
    expect((cite.resolved.locator as { kind: string }).kind).toBe('number');
  });

  // ── T1-7: the LETTER-SUFFIXED handle, on the anchored copy of the grammar ───────────────────────────
  it('resolves a SUFFIXED number handle [N1b] onto its call, keeping the suffix in the ref', () => {
    const numLedger: ResolvedMap = {
      '1': { source: 'USDA PSD', date: '2024', locator: { kind: 'number', table: 'silver_psd' } },
    };
    const toks = parseInline('stocks fell [N1] from [N1b]', numLedger);
    const cites = toks.filter((t) => t.k === 'cite') as { ref: string; resolved: ResolvedMap[string] }[];
    expect(cites.map((c) => c.ref)).toEqual(['N1', 'N1b']);
    // the completion row is the SAME lookup: same locator ⇒ the click lands on the same chart target
    expect(cites[1]?.resolved.locator).toBe(numLedger['1']!.locator);
  });

  it('inert mode keeps the suffix too (a pre-verifier [N1b] is a visible marker, never text)', () => {
    expect(parseInline('was [N1b] then', {}, { inert: true })).toEqual([
      { k: 'text', v: 'was ' },
      { k: 'inert', ref: 'N1b' },
      { k: 'text', v: ' then' },
    ]);
  });
});

/**
 * THE TWO-COPY PIN (T1-7). Two tokenizers walk the same prose -- `tokenizeCitations` (global) for the note
 * body and `parseInline` (anchored) for the TL;DR/headings -- and this is the defect that lived here: they
 * carried HAND-COPIED regexes, so a handle shape one accepted the other left as literal text. Both now
 * build from `citations.CITE_SRC`; this pin is what fails if anyone re-inlines a copy.
 */
describe('cite grammar parity — the two tokenizers accept EXACTLY the same handle set', () => {
  const led: ResolvedMap = { '1': { source: 'S', date: 'd' }, '12': { source: 'S', date: 'd' } };
  const accepted = ['[1]', '[12]', '[E1]', '[N1]', '[N1b]', '[N12z]'];
  const rejected = ['[1B]', '[Nb]', '[N1bc]', '[]', '[N 1]', '[1-2]'];

  it.each(accepted)('%s chips in BOTH renderers', (tok) => {
    expect(tokenizeCitations(`x ${tok} y`, led).some((s) => s.kind === 'cite')).toBe(true);
    expect(parseInline(`x ${tok} y`, led).some((t) => t.k === 'cite')).toBe(true);
  });

  it.each(rejected)('%s is literal text in BOTH renderers', (tok) => {
    expect(tokenizeCitations(`x ${tok} y`, led).some((s) => s.kind === 'cite')).toBe(false);
    expect(parseInline(`x ${tok} y`, led).some((t) => t.k === 'cite')).toBe(false);
  });
});

describe('render (no raw markers in the DOM)', () => {
  it('renderInline emits <strong> and no literal asterisks', () => {
    render(<div data-testid="w">{renderInline('the **key** driver', {}, () => {})}</div>);
    const el = screen.getByTestId('w');
    expect(el.querySelector('strong')?.textContent).toBe('key');
    expect(el.textContent).toBe('the key driver');
    expect(el.textContent).not.toContain('*');
  });

  it('FormattedNote turns "- " lines into a real <ul> and drops stray markers', () => {
    render(
      <div data-testid="n">
        <FormattedNote text={'lead in\n\n- first **point**\n- second'} resolved={{}} onOpen={() => {}} />
      </div>,
    );
    const el = screen.getByTestId('n');
    expect(el.querySelectorAll('ul li')).toHaveLength(2);
    expect(el.querySelector('strong')?.textContent).toBe('point');
    expect(el.textContent).not.toContain('*');
  });
});

describe('FormattedNote headings (P9-A mentor scaffold)', () => {
  it('renders "## " lines as real headings, never literal ##', () => {
    render(
      <div data-testid="h">
        <FormattedNote
          text={'## Mechanism\nDrought tightens stocks.\n## The record\nUS stocks fell.'}
          resolved={{}}
          onOpen={() => {}}
        />
      </div>,
    );
    const el = screen.getByTestId('h');
    const heads = el.querySelectorAll('h5');
    expect(heads).toHaveLength(2);
    expect(heads[0]?.textContent).toBe('Mechanism');
    expect(heads[1]?.textContent).toBe('The record');
    expect(el.textContent).not.toContain('##');
  });

  it('renders the "## Sources" footer as a heading (the numbers-answer literal-## regression)', () => {
    render(
      <div data-testid="s">
        <FormattedNote text={'Stocks fell 5%.\n\n## Sources\n- WASDE 2022-01'} resolved={{}} onOpen={() => {}} />
      </div>,
    );
    const el = screen.getByTestId('s');
    expect(el.querySelector('h5')?.textContent).toBe('Sources');
    expect(el.textContent).not.toContain('##');
    expect(el.querySelectorAll('ul li')).toHaveLength(1);   // the bullet under the heading still lists
  });

  it('heading text still resolves inline markup and citations', () => {
    render(
      <Tooltip.Provider>
        <div data-testid="c">
          <FormattedNote text={'## The **record** [1]\nbody'} resolved={resolved} onOpen={() => {}} />
        </div>
      </Tooltip.Provider>,
    );
    const el = screen.getByTestId('c');
    expect(el.querySelector('h5 strong')?.textContent).toBe('record');
  });
});

describe('renderInline typed-handle chips (S1: the token becomes a mounted chip, not literal text)', () => {
  it('MOUNTS a clickable chip button for a TYPED evidence handle [E3] (pre-fix it stayed literal text)', () => {
    render(
      <Tooltip.Provider>
        <div data-testid="w">{renderInline('drought tightened [E3]', resolvedInt, () => {})}</div>
      </Tooltip.Provider>,
    );
    // pre-fix this button never mounted (the handle survived as the literal text node "[E3]")
    const chip = screen.getByRole('button', { name: '[E3]' });
    expect(chip.tagName).toBe('BUTTON'); // a real CitationChip trigger, not a bare literal-text span
    expect(chip.textContent).toBe('[E3]'); // the chip label keeps the TYPED display handle
    // NOTE: CitationChip.tsx:26 colors by /^[A-Za-z]/ ⇒ a TYPED evidence ref "E3" renders CYAN, not amber.
    // Restoring amber=evidence needs an N-specific test THERE (`/^N/`), which is outside this S1 surface.
  });

  it('a TYPED number handle [N4] mounts a CYAN chip (number color path — correct as-is)', () => {
    const numLedger: ResolvedMap = {
      '4': { source: 'USDA PSD', date: '2024', locator: { kind: 'number', table: 'silver_psd' } },
    };
    render(
      <Tooltip.Provider>
        <div data-testid="wn">{renderInline('stocks fell [N4]', numLedger, () => {})}</div>
      </Tooltip.Provider>,
    );
    const chip = screen.getByRole('button', { name: '[N4]' });
    expect(chip.className).toContain('border-cyan'); // number chip stays cyan
  });
});

// ── the typed-handle COLOR contract (post-P9): E/bare = evidence amber, N = number cyan ────────────────
import { CitationChip } from './CitationChip';

describe('CitationChip color classification (typed handles)', () => {
  const res = { source: 'USDA WASDE', date: '2022-01-01', text: 'snippet' } as never;
  it.each([
    ['E3', 'text-amber'],   // typed evidence handle stays AMBER (the pre-fix /^[A-Za-z]/ turned it cyan)
    ['3', 'text-amber'],    // legacy bare evidence handle
    ['N4', 'text-cyan'],    // number handle is cyan
  ])('refId %s carries %s', (refId, cls) => {
    render(
      <Tooltip.Provider>
        <CitationChip refId={refId} resolved={res} onOpen={() => {}} />
      </Tooltip.Provider>,
    );
    const chip = screen.getByRole('button', { name: `[${refId}]` });
    expect(chip.className).toContain(cls);
  });
});
