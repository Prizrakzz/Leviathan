import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SuggestionChips, watchChipLabel, watchChipText } from './SuggestionChips';

describe('SuggestionChips (6.2)', () => {
  it('renders chips and click fires onAsk with the question', () => {
    const onAsk = vi.fn();
    render(<SuggestionChips items={['How thin are stocks?', 'What about frost?']} onAsk={onAsk} />);
    const chips = screen.getByTestId('suggestion-chips');
    expect(chips.querySelectorAll('button')).toHaveLength(2);
    fireEvent.click(screen.getByText('What about frost?'));
    expect(onAsk).toHaveBeenCalledWith('What about frost?');
  });

  it('renders NOTHING for an empty list (chips are a nicety, never an error state)', () => {
    render(<SuggestionChips items={[]} onAsk={() => {}} />);
    expect(screen.queryByTestId('suggestion-chips')).toBeNull();
  });

  it('P9-E1a: watch chips render PREPENDED and click PREFILLS via onPrefill, never onAsk', () => {
    const onAsk = vi.fn();
    const onPrefill = vi.fn();
    render(
      <SuggestionChips
        items={['How thin are stocks?']}
        onAsk={onAsk}
        watchItems={['certified stocks through July']}
        onPrefill={onPrefill}
      />,
    );
    const buttons = screen.getByTestId('suggestion-chips').querySelectorAll('button');
    expect(buttons).toHaveLength(2);
    expect(buttons[0]!.textContent).toBe('certified stocks through July'); // watch chip first
    fireEvent.click(screen.getByTestId('watch-chip'));
    expect(onPrefill).toHaveBeenCalledWith('certified stocks through July');
    expect(onAsk).not.toHaveBeenCalled();
  });

  it('P9-E1a: watch chips alone still render the row (server suggestions may be empty)', () => {
    render(<SuggestionChips items={[]} onAsk={() => {}} watchItems={['a']} onPrefill={() => {}} />);
    expect(screen.getByTestId('suggestion-chips')).toBeTruthy();
  });

  it('S3: clamps to EXACTLY 3 suggester chips even when the merged source over-produces', () => {
    render(
      <SuggestionChips
        items={['q1?', 'q2?', 'q3?', 'q4?', 'q5?']} // server over-produces (>3)
        onAsk={() => {}}
        watchItems={['w1', 'w2']} // a separate class, merged into the same "follow up" row
        onPrefill={() => {}}
      />,
    );
    const row = screen.getByTestId('suggestion-chips');
    // suggester follow-ups = every chip except the watch chips; clamp holds at 3 (was 5 before the fix)
    const suggesters = [...row.querySelectorAll('button')].filter(
      (b) => b.getAttribute('data-testid') !== 'watch-chip',
    );
    expect(suggesters).toHaveLength(3);
    // watch chips stay their own visually-distinct class, unclamped by the suggester clamp
    expect(row.querySelectorAll('[data-testid="watch-chip"]')).toHaveLength(2);
  });
});

/** D-TW-24 -- MEASURED in authed prod: watch-suggestion chips rendered raw markdown. The label literally
 *  read `**BRL/USD trajectory**: a further weakening real strengthens the …` — unrendered bold markers plus
 *  the wholesale bullet sentence, because SuggestionChips renders `{q}` as a plain text child (nothing here
 *  goes through inlineFormat, which is what strips markers for note prose). Fixed at the label boundary. */
describe('D-TW-24: watch-chip labels (render boundary -- server data untouched)', () => {
  // The exact string measured on screen, including the 90-char clip deriveWatchChips already applied.
  const MEASURED =
    '**BRL/USD trajectory**: a further weakening real strengthens the incentive to sell…';

  it('the measured label: bold markers gone, truncated to the watch-item TITLE', () => {
    expect(watchChipLabel(MEASURED)).toBe('BRL/USD trajectory');
  });

  it('the rendered chip shows the title; the FULL (de-marked) sentence rides the tooltip', () => {
    render(<SuggestionChips items={[]} onAsk={() => {}} watchItems={[MEASURED]} onPrefill={() => {}} />);
    const chip = screen.getByTestId('watch-chip');
    expect(chip.textContent).toBe('BRL/USD trajectory');
    expect(chip.textContent).not.toContain('**'); // the literal defect
    expect(chip.getAttribute('title')).toBe(
      'BRL/USD trajectory: a further weakening real strengthens the incentive to sell…',
    );
  });

  it('prefill carries the sentence WITHOUT markers -- the composer must never receive raw `**`', () => {
    const onPrefill = vi.fn();
    render(<SuggestionChips items={[]} onAsk={() => {}} watchItems={[MEASURED]} onPrefill={onPrefill} />);
    fireEvent.click(screen.getByTestId('watch-chip'));
    expect(onPrefill).toHaveBeenCalledWith(
      'BRL/USD trajectory: a further weakening real strengthens the incentive to sell…',
    );
  });

  it('an untitled bullet keeps its whole sentence -- only markers are stripped', () => {
    const plain = 'Certified/tenderable *stocks* through the July frost window';
    expect(watchChipLabel(plain)).toBe('Certified/tenderable stocks through the July frost window');
  });

  it('a mid-sentence colon does NOT truncate: the title rule needs the `**name**:` shape', () => {
    const colon = 'Watch the crush margin: it is the transmission channel to soymeal';
    expect(watchChipLabel(colon)).toBe(colon);
  });

  it('snake_case ids survive -- `_` is NOT treated as an emphasis marker', () => {
    expect(watchChipText('Watch silver_psd su_ratio prints')).toBe('Watch silver_psd su_ratio prints');
  });

  it('a bullet clipped MID-bold degrades to stripped prose, never a mangled title', () => {
    // deriveWatchChips caps at 90 chars, so a long item can lose its closing `**`.
    expect(watchChipLabel('**An unusually long watch item name that ran past the cap')).toBe(
      'An unusually long watch item name that ran past the cap',
    );
  });

  it('two items sharing a title still render two chips (React keys stay on the RAW text)', () => {
    render(
      <SuggestionChips
        items={[]}
        onAsk={() => {}}
        watchItems={['**Basis**: Paranagua premiums', '**Basis**: Gulf premiums']}
        onPrefill={() => {}}
      />,
    );
    const chips = screen.getAllByTestId('watch-chip');
    expect(chips).toHaveLength(2);
    expect(chips.map((c) => c.textContent)).toEqual(['Basis', 'Basis']);
  });
});
