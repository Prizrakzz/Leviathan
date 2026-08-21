import { describe, expect, it } from 'vitest';
import { buildPageMap, locateInPage, rangesForSpan } from './locateSpan';

// The find-controller page-string shape: str concatenation + '\n' on hasEOL; empty strs detached.
const ITEMS = [
  { str: 'Frost struck the ', hasEOL: false },
  { str: '', hasEOL: false }, // detached span: contributes NO run and NO text
  { str: 'arabica belt in July', hasEOL: true },
  { str: 'causing severe crop damage.', hasEOL: true },
];

describe('buildPageMap', () => {
  it('concatenates strs, appends newline on hasEOL, and skips empty items', () => {
    const m = buildPageMap(ITEMS);
    expect(m.pageText).toBe('Frost struck the arabica belt in July\ncausing severe crop damage.\n');
    expect(m.runs.map((r) => r.divIndex)).toEqual([0, 2, 3]); // item 1 (empty) has no run
    expect(m.runs[1]).toEqual({ divIndex: 2, start: 17, end: 37 });
  });
});

describe('locateInPage', () => {
  const m = buildPageMap(ITEMS);

  it('raw substring is the T0 path (the measured 99.4%)', () => {
    expect(locateInPage(m, 'arabica belt')).toEqual({ start: 17, end: 29 });
  });

  it('spans crossing item boundaries and the hasEOL newline still locate raw', () => {
    const hit = locateInPage(m, 'in July\ncausing severe');
    expect(hit).toEqual({ start: 30, end: 52 });
  });

  it('strips the 140-char locator ellipsis before matching (mirrors pdfpage._norm)', () => {
    expect(locateInPage(m, 'arabica belt...')).toEqual({ start: 17, end: 29 });
  });

  it('folded fallback closes the accent-divergence class', () => {
    const acc = buildPageMap([{ str: 'safra de café no Paraná', hasEOL: false }]);
    const hit = locateInPage(acc, 'safra de cafe no Parana'); // server text lost the diacritics
    expect(hit).not.toBeNull();
    expect(acc.pageText.slice(hit!.start, hit!.end)).toBe('safra de café no Paraná');
  });

  it('folded fallback also absorbs whitespace-shape divergence', () => {
    const hit = locateInPage(m, 'arabica  belt   in July');
    expect(hit).not.toBeNull();
    expect(m.pageText.slice(hit!.start, hit!.end)).toBe('arabica belt in July');
  });

  it('a genuine miss returns null (the page-jump degrade), never throws', () => {
    expect(locateInPage(m, 'soybean crush margins in Mato Grosso')).toBeNull();
    expect(locateInPage(m, '')).toBeNull();
    expect(locateInPage(m, '...')).toBeNull();
  });
});

describe('rangesForSpan', () => {
  const m = buildPageMap(ITEMS);

  it('slices a cross-item span into per-div local ranges, skipping the virtual newline', () => {
    const hit = locateInPage(m, 'belt in July\ncausing')!;
    const rr = rangesForSpan(m, hit.start, hit.end);
    expect(rr).toEqual([
      { divIndex: 2, startOffset: 8, endOffset: 20 }, // 'belt in July' within item 2
      { divIndex: 3, startOffset: 0, endOffset: 7 }, // 'causing' within item 3
    ]);
  });

  it('a span inside one item yields exactly one local range', () => {
    const hit = locateInPage(m, 'severe crop')!;
    expect(rangesForSpan(m, hit.start, hit.end)).toEqual([{ divIndex: 3, startOffset: 8, endOffset: 19 }]);
  });
});
