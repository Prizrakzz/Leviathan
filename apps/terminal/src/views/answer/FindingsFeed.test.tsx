import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { EMPTY_FINDINGS, parsePartial, reduceFindings, type Findings } from '@/api/partials';
import { FindingsFeed } from './FindingsFeed';

/** Drive the REAL reducer so the render tests can never drift from the accumulation contract. */
function findingsOf(events: unknown[]): Findings {
  let f: Findings = { ...EMPTY_FINDINGS };
  for (const e of events) {
    const p = parsePartial(e);
    if (p) f = reduceFindings(f, p);
  }
  return f;
}

const STREAM = [
  { stage: 'plan', intent: 'hybrid', contracts: ['corn_cbot', 'soybean_cbot'] },
  { stage: 'walk', nodes: 34, depth: 3 },
  {
    stage: 'regime', contract: 'corn_cbot', regime: 'export_pace_surge', direction: 'bullish',
    basis: { fgis_inspections: { date: '2026-07-18', source: 'usda_fgis' } },
  },
  { stage: 'number', table: 'silver_psd', metric: 'su_ratio', value: 0.36, unit: 'ratio', asof: '2026-06-11' },
  { stage: 'chain', chain_id: 'palm_sbo_sbm', hops: ['palm', 'sbo', 'sbm'] },
  { stage: 'evidence', node: 'export_pace', kept: 12 },
];

describe('FindingsFeed (F7) — the live findings surface', () => {
  it('mounts and shows substance: intent + contracts, the walk shape, regimes with their dated basis', () => {
    render(<FindingsFeed findings={findingsOf(STREAM)} />);
    const rows = screen.getAllByTestId('finding-row');
    expect(rows.map((r) => r.dataset.kind)).toEqual(['plan', 'walk', 'regime', 'number', 'chain', 'evidence']);
    expect(screen.getByTestId('findings-feed').textContent).toContain('hybrid');
    expect(screen.getByTestId('findings-feed').textContent).toContain('corn cbot, soybean cbot');
    expect(screen.getByText('34')).toBeTruthy();
    expect(screen.getByText('export pace surge')).toBeTruthy();
    // the basis is what makes a firing checkable — driver, date AND source must all render
    const regime = rows[2]!;
    expect(regime.textContent).toContain('fgis inspections');
    expect(regime.textContent).toContain('2026-07-18');
    expect(regime.textContent).toContain('usda fgis');
    // a resolved number keeps its table + as-of (provenance, not just the value)
    expect(rows[3]!.textContent).toContain('0.36');
    expect(rows[3]!.textContent).toContain('silver_psd');
    expect(rows[3]!.textContent).toContain('as of 2026-06-11');
    expect(rows[4]!.textContent).toContain('palm → sbo → sbm');
    expect(rows[5]!.textContent).toContain('12');
  });

  it('APPENDS on update without throwing and without disturbing the rows already shown', () => {
    const first = findingsOf(STREAM.slice(0, 2));
    const view = render(<FindingsFeed findings={first} />);
    expect(screen.getAllByTestId('finding-row')).toHaveLength(2);
    const walkRow = screen.getAllByTestId('finding-row')[1]!;
    expect(() => view.rerender(<FindingsFeed findings={findingsOf(STREAM)} />)).not.toThrow();
    const rows = screen.getAllByTestId('finding-row');
    expect(rows).toHaveLength(6);
    expect(rows[1]).toBe(walkRow); // same DOM node: appending never re-mounts (nor re-animates) what is up
  });

  it('COLLAPSES into a summary when drafting starts — kept, not destroyed — and re-expands on click', async () => {
    const drafting = findingsOf([...STREAM, { stage: 'drafting' }]);
    render(<FindingsFeed findings={drafting} />);
    const feed = screen.getByTestId('findings-feed');
    expect(feed.dataset.phase).toBe('drafting');
    expect(feed.dataset.open).toBe('false');
    expect(screen.getByTestId('findings-toggle').getAttribute('aria-expanded')).toBe('false');
    // the summary keeps the counts on screen, and the rows stay MOUNTED (provenance one click away)
    expect(screen.getByTestId('findings-summary').textContent).toBe('1 regime · 1 number · 1 chain · 12 props kept');
    expect(screen.getAllByTestId('finding-row')).toHaveLength(6);
    await userEvent.click(screen.getByTestId('findings-toggle'));
    expect(screen.getByTestId('findings-feed').dataset.open).toBe('true');
  });

  it('the USER’s open/closed choice outranks the automatic collapse', async () => {
    const view = render(<FindingsFeed findings={findingsOf(STREAM)} />);
    expect(screen.getByTestId('findings-feed').dataset.open).toBe('true'); // auto: open while the engines work
    await userEvent.click(screen.getByTestId('findings-toggle')); // user collapses it early
    expect(screen.getByTestId('findings-feed').dataset.open).toBe('false');
    view.rerender(<FindingsFeed findings={findingsOf([...STREAM, { stage: 'evidence', node: 'stocks', kept: 4 }])} />);
    expect(screen.getByTestId('findings-feed').dataset.open).toBe('false'); // more findings do not re-open it
    await userEvent.click(screen.getByTestId('findings-toggle')); // user pins it OPEN
    view.rerender(<FindingsFeed findings={findingsOf([...STREAM, { stage: 'drafting' }])} />);
    expect(screen.getByTestId('findings-feed').dataset.open).toBe('true'); // drafting does not close it under them
  });

  it('shows the verifier’s strip count only once `verified` has landed', () => {
    const view = render(<FindingsFeed findings={findingsOf([...STREAM, { stage: 'drafting' }])} />);
    expect(screen.queryByTestId('findings-strips')).toBeNull();
    view.rerender(<FindingsFeed findings={findingsOf([...STREAM, { stage: 'verified', strips: 7 }])} />);
    expect(screen.getByTestId('findings-strips').textContent).toBe('7 stripped');
  });

  it('DEGRADES to nothing: no partials (an older server) renders no feed at all', () => {
    const { container } = render(<FindingsFeed findings={EMPTY_FINDINGS} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId('findings-feed')).toBeNull();
    // an older cached turn shape carries none of the keys at all
    expect(render(<FindingsFeed findings={{}} />).container.firstChild).toBeNull();
    // and a stream of ONLY unknown kinds is the same thing
    const unknown = findingsOf([{ stage: 'quantum_flux', nodes: 3 }, { stage: 'chain_v2', hops: ['a'] }]);
    expect(render(<FindingsFeed findings={unknown} />).container.firstChild).toBeNull();
  });

  it('normalises BOTH direction dialects (`+`/`-` from the firing rules, words from the map) to one mark', () => {
    const view = render(
      <FindingsFeed
        findings={findingsOf([
          { stage: 'regime', contract: 'c', regime: 'export_pace_surge', direction: '+', basis: {} },
          { stage: 'regime', contract: 'c', regime: 'crush_margin_squeeze', direction: 'bearish', basis: {} },
          { stage: 'regime', contract: 'c', regime: 'odd_one', direction: 'sideways', basis: {} },
        ])}
      />,
    );
    const rows = screen.getAllByTestId('finding-row');
    expect(rows[0]!.textContent).toContain('▲');
    expect(rows[0]!.querySelector('.text-pos')).toBeTruthy();
    expect(rows[1]!.textContent).toContain('▼');
    expect(rows[1]!.querySelector('.text-neg')).toBeTruthy();
    expect(rows[2]!.textContent).toContain('sideways'); // unrecognised → shown verbatim, never guessed at
    // a slug that already says it does not say it twice
    view.rerender(
      <FindingsFeed
        findings={findingsOf([{ stage: 'regime', contract: 'c', regime: 'sideways_drift', direction: 'sideways', basis: {} }])}
      />,
    );
    expect(screen.getAllByTestId('finding-row')[0]!.textContent).toBe('regimesideways drift · c');
  });

  it('survives thin/degenerate findings (empty basis, no hops, missing lists)', () => {
    const thin = findingsOf([
      { stage: 'plan', intent: 'numbers_only' },
      { stage: 'regime', contract: 'c', regime: 'r' },
      { stage: 'chain', chain_id: 'x' },
      { stage: 'number', table: 't', metric: 'm', value: '1.2' },
      // the backend projects a missing date/source to EMPTY STRINGS rather than omitting them
      { stage: 'regime', contract: 'c', regime: 'r2', direction: '+', basis: { undated_driver: { date: '', source: '' } } },
    ]);
    expect(() => render(<FindingsFeed findings={thin} />)).not.toThrow();
    const rows = screen.getAllByTestId('finding-row');
    expect(rows).toHaveLength(5);
    expect(rows[4]!.textContent).toBe('regime▲r2 · cundated driver'); // no empty date/source artifacts
  });
});
