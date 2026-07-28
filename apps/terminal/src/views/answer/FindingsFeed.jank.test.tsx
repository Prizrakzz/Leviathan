/**
 * F7 SKEPTIC — THE SMOOTHNESS GATES.
 *
 * "No half measures, no jank" is a shipping requirement, so the two failure modes that actually produce
 * jank get a regression test each rather than a code comment.
 *
 *  1. RE-RENDER STORM. Findings ride the same turn object as the synthesis draft, so `findings` changes
 *     identity on every `token` delta — thousands of them across a 24-50s synthesis, all landing while the
 *     typewriter needs frames. Measured before the memo: 400 deltas = 400 commits of a 54-row feed and
 *     ~780ms of React work whose output was byte-identical. After: ~0.8ms.
 *
 *  2. REMOUNT ON SETTLE. AnswerView renders the reveal in branches; when the feed sits at a DIFFERENT
 *     child slot in two of them, React unmounts the subtree between them — replaying every row's enter
 *     animation at the exact moment the answer lands, and discarding the reader's expand/collapse choice.
 *
 * Both are measured against real DOM, not asserted from the source.
 */
import { Profiler, type ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { EMPTY_FINDINGS, parsePartial, reduceFindings, type Findings } from '@/api/partials';
import type { StageEvent } from '@/api/schema';
import { FindingsFeed } from './FindingsFeed';

/** A wide-but-plausible turn: 3 contracts x 4 regimes, 8 numbers, 30 evidence legs, 2 chains = 54 rows. */
function wideTurn(): Findings {
  let f: Findings = { ...EMPTY_FINDINGS };
  const push = (e: object) => {
    const p = parsePartial(e as StageEvent);
    if (p) f = reduceFindings(f, p);
  };
  push({ stage: 'plan', intent: 'hybrid', contracts: ['corn', 'wheat', 'soybeans'] });
  push({ stage: 'walk', nodes: 34, depth: 3 });
  for (let n = 0; n < 30; n++) push({ stage: 'evidence', node: `driver:corn:d${n}`, kept: n % 5 });
  for (const c of ['corn', 'wheat', 'soybeans'])
    for (let i = 0; i < 4; i++)
      push({
        stage: 'regime',
        contract: c,
        regime: `squeeze_${i}`,
        direction: '+',
        basis: {
          drought: { date: '2024-05-01', source: 'NOAA' },
          stocks: { date: '2024-05-10', source: 'WASDE' },
        },
      });
  for (let i = 0; i < 8; i++)
    push({ stage: 'number', table: 'silver_psd', metric: `m${i}`, value: 1000 + i, unit: 'mt', asof: '2024-02-08' });
  push({ stage: 'chain', chain_id: 'chain_corn', hops: ['safrinha', 'br_production', 'us_export'] });
  push({ stage: 'chain', chain_id: 'xmit_palm', hops: ['palm_oil', 'soybean_oil'] });
  return f;
}

describe('1 · the feed does not re-render on token deltas', () => {
  it('400 draft updates cost the feed effectively nothing', () => {
    const f = wideTurn();
    let commits = 0;
    let totalMs = 0;
    const wrap = (turn: object): ReactNode => (
      <Profiler
        id="feed"
        onRender={(_id, _phase, actualDuration) => {
          commits++;
          totalMs += actualDuration;
        }}
      >
        <FindingsFeed findings={turn as Findings} />
      </Profiler>
    );
    // useTurn's shape: TurnState extends Findings. A token delta returns `{...s, draft: s.draft + text}`,
    // so the carrier is new but every findings field keeps its reference.
    const turn = { ...f, status: 'streaming', stages: [], draft: '' };
    const { rerender } = render(wrap(turn));
    expect(document.querySelectorAll('[data-testid="finding-row"]')).toHaveLength(54);
    commits = 0;
    totalMs = 0;
    for (let i = 0; i < 400; i++) rerender(wrap({ ...turn, draft: 'x'.repeat(i) }));
    expect(commits).toBe(400); // the PARENT still renders — that is the SSE turn state, unavoidable
    // ...but the feed itself bails out. 400 real renders of 54 rows measured ~780ms here; the memo puts
    // it under 1ms. The bound is deliberately loose (50ms) so this fails on a regression, not on a slow CI box.
    expect(totalMs, `feed re-rendered on token deltas: ${totalMs.toFixed(1)}ms for 400 draft updates`).toBeLessThan(50);
  });

  it('a landed finding DOES re-render the feed (the memo cannot be a mute button)', () => {
    let f = wideTurn();
    const wrap = (turn: object): ReactNode => <FindingsFeed findings={turn as Findings} />;
    const { rerender } = render(wrap({ ...f, status: 'streaming', stages: [], draft: '' }));
    expect(document.querySelectorAll('[data-testid="finding-row"]')).toHaveLength(54);
    f = reduceFindings(f, parsePartial({ stage: 'evidence', node: 'driver:corn:late', kept: 9 } as StageEvent)!);
    rerender(wrap({ ...f, status: 'streaming', stages: [], draft: '' }));
    expect(document.querySelectorAll('[data-testid="finding-row"]')).toHaveLength(55);
  });
});

describe('2 · the feed survives the turn settling, with the reader\'s state intact', () => {
  /** The exact branch shape AnswerView renders: reveal (streaming | done-but-typing) -> final. */
  function Turn({ phase, findings }: { phase: 'streaming' | 'settling' | 'final'; findings: Findings }) {
    const revealing = phase === 'streaming' || phase === 'settling';
    return (
      <div className="space-y-3">
        <div>question</div>
        {revealing && <div>pipeline</div>}
        <FindingsFeed findings={findings} />
        {revealing && <div>draft</div>}
        {phase === 'final' && (
          <div>
            <div>banners</div>
            <div>note</div>
          </div>
        )}
      </div>
    );
  }

  it('the same DOM nodes carry through streaming -> settling -> final (no animation replay)', () => {
    const f = wideTurn();
    const { rerender } = render(<Turn phase="streaming" findings={f} />);
    const feed = document.querySelector('[data-testid="findings-feed"]');
    const firstRow = document.querySelectorAll('[data-testid="finding-row"]')[0];
    rerender(<Turn phase="settling" findings={f} />);
    expect(document.querySelector('[data-testid="findings-feed"]')).toBe(feed);
    rerender(<Turn phase="final" findings={{ ...f, phase: 'verified', strips: 3, citationsLive: true }} />);
    expect(document.querySelector('[data-testid="findings-feed"]')).toBe(feed);
    expect(document.querySelectorAll('[data-testid="finding-row"]')[0]).toBe(firstRow);
    expect(screen.getByTestId('findings-strips')).toHaveTextContent('3 stripped');
  });

  it('a reader who expanded the feed keeps it expanded when the answer lands', () => {
    const f = wideTurn();
    const { rerender } = render(<Turn phase="streaming" findings={{ ...f, phase: 'drafting' }} />);
    // drafting -> auto-collapsed; the reader opens it to read the provenance while the writer works
    expect(screen.getByTestId('findings-feed')).toHaveAttribute('data-open', 'false');
    fireEvent.click(screen.getByTestId('findings-toggle'));
    expect(screen.getByTestId('findings-feed')).toHaveAttribute('data-open', 'true');
    rerender(<Turn phase="final" findings={{ ...f, phase: 'verified', citationsLive: true }} />);
    expect(screen.getByTestId('findings-feed'), 'the settle discarded the reader\'s choice').toHaveAttribute(
      'data-open',
      'true',
    );
  });
});

describe('3 · appending a finding does not move the page', () => {
  function Page({ findings }: { findings: Findings }) {
    return (
      <div>
        <FindingsFeed findings={findings} />
        <div data-testid="below">the draft lives here</div>
      </div>
    );
  }

  it('rows land inside a height-capped scroll box, so 5 findings and 54 shift the same', () => {
    let f = wideTurn();
    const { rerender } = render(<Page findings={f} />);
    const box = screen.getByTestId('findings-rows');
    // The cap is what makes the append safe: it is a class contract, so assert the class, not a jsdom px.
    expect(box.className).toContain('max-h-64');
    expect(box.className).toContain('overflow-y-auto');
    for (let i = 0; i < 40; i++) {
      f = reduceFindings(f, parsePartial({ stage: 'evidence', node: `driver:x:${i}`, kept: 1 } as StageEvent)!);
      rerender(<Page findings={f} />);
    }
    expect(screen.getByTestId('findings-rows')).toBe(box); // still the same box; nothing above it re-laid out
    expect(document.querySelectorAll('[data-testid="finding-row"]')).toHaveLength(94);
  });

  it('every row has a stable key, so an append never remounts an existing row', () => {
    let f = wideTurn();
    const { rerender } = render(<Page findings={f} />);
    const before = [...document.querySelectorAll('[data-testid="finding-row"]')];
    f = reduceFindings(f, parsePartial({ stage: 'regime', contract: 'cocoa', regime: 'deficit', direction: '-', basis: {} } as StageEvent)!);
    rerender(<Page findings={f} />);
    const after = [...document.querySelectorAll('[data-testid="finding-row"]')];
    expect(after.slice(0, before.length)).toEqual(before); // identity, not equality: no remount, no re-animation
    expect(after).toHaveLength(before.length + 1);
  });

  it('a re-emitted finding updates in place and keeps its arrival slot', () => {
    let f = wideTurn();
    const { rerender } = render(<Page findings={f} />);
    const before = [...document.querySelectorAll('[data-testid="finding-row"]')];
    const at = before.findIndex((el) => el.textContent?.includes('driver:x') === false && el.getAttribute('data-kind') === 'evidence');
    f = reduceFindings(f, parsePartial({ stage: 'evidence', node: 'driver:corn:d0', kept: 99 } as StageEvent)!);
    rerender(<Page findings={f} />);
    const after = [...document.querySelectorAll('[data-testid="finding-row"]')];
    expect(after).toHaveLength(before.length); // updated, not appended
    expect(after[at]).toBe(before[at]); // same DOM node -> no reorder, no re-animation
    expect(after.find((el) => el.textContent?.includes('driver:corn:d0'))?.textContent).toContain('99');
  });
});

describe('4 · the citation rule holds through the whole reveal', () => {
  it('citationsLive alone cannot mint a chip — a resolved map is also required', () => {
    // This is what makes AnswerView safe passing `live` through the WHOLE reveal: `verified` sets
    // citationsLive before the terminal `result`, but `resolvedFor(r)` needs `r`, which lands with it.
    let f = wideTurn();
    f = reduceFindings(f, parsePartial({ stage: 'verified', strips: 7 } as StageEvent)!);
    expect(f.citationsLive).toBe(true);
    expect(f.strips).toBe(7);
    // the feed shows the verifier's own number; nothing about it activates a handle
    render(<FindingsFeed findings={f} />);
    expect(screen.getByTestId('findings-strips')).toHaveTextContent('7 stripped');
    expect(document.querySelector('[data-testid="cite-inert"]')).toBeNull();
  });
});

describe('5 · unbounded growth is survivable', () => {
  it('a pathologically wide walk (300 findings) still renders inside the cap', () => {
    let f: Findings = { ...EMPTY_FINDINGS };
    for (let i = 0; i < 300; i++)
      f = reduceFindings(f, parsePartial({ stage: 'evidence', node: `driver:c:${i}`, kept: 1 } as StageEvent)!);
    const t0 = performance.now();
    render(<FindingsFeed findings={f} />);
    const ms = performance.now() - t0;
    expect(document.querySelectorAll('[data-testid="finding-row"]')).toHaveLength(300);
    expect(screen.getByTestId('findings-rows').className).toContain('max-h-64');
    // There is no virtualisation and no cap; 300 rows is the honest ceiling this stays cheap at.
    expect(ms, `300 findings took ${ms.toFixed(0)}ms to mount`).toBeLessThan(2000);
  });
});

describe('6 · reduced motion is honoured explicitly', () => {
  it('the enter animation is a NAMED class the global rule can switch off', () => {
    render(<FindingsFeed findings={wideTurn()} />);
    const row = document.querySelector('[data-testid="finding-row"]');
    // styles/global.css: `.lv-finding { animation: lv-finding-in ... }` plus an `animation: none !important`
    // inside `@media (prefers-reduced-motion: reduce)`. The class must actually be on the row for that to bite.
    expect(row?.className).toContain('lv-finding');
    // Only opacity/transform animate, so an append can never reflow the rows above it.
    expect(row?.className).not.toMatch(/animate-(height|width)/);
  });
});
