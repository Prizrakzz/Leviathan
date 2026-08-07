import { describe, expect, it } from 'vitest';
import type { components } from '@/api/types.gen';
import { cellLabel, firedCount, heatBucket, maxProximity, rankRows } from './heat';

type Card = components['schemas']['RegimeCard'];
type Row = components['schemas']['ConvergenceRow'];

const card = (over: Partial<Card>): Card => ({
  name: 'r',
  direction: '+',
  matched: [],
  threshold: 2,
  fired: false,
  n_active: 0,
  proximity: 0,
  ...over,
});
const row = (contract: string, cards: Partial<Card>[]): Row => ({
  contract,
  regimes: cards.map(card),
  drivers: [],
});

describe('heatBucket', () => {
  it('fired always wins regardless of proximity', () => {
    expect(heatBucket(0, true)).toBe('fired');
  });
  it('buckets by proximity thresholds', () => {
    expect(heatBucket(0.9, false)).toBe('hot');
    expect(heatBucket(0.6, false)).toBe('warm');
    expect(heatBucket(0.3, false)).toBe('cool');
    expect(heatBucket(0.1, false)).toBe('dormant');
  });
  it('treats non-finite proximity as dormant', () => {
    expect(heatBucket(Number.NaN, false)).toBe('dormant');
  });
});

describe('maxProximity / firedCount', () => {
  it('a fired regime pins the row max to 1', () => {
    expect(maxProximity(row('corn', [{ proximity: 0.2 }, { fired: true, proximity: 0.5 }]))).toBe(1);
  });
  it('counts fired regimes', () => {
    expect(firedCount(row('corn', [{ fired: true }, { fired: false }, { fired: true }]))).toBe(2);
  });
});

describe('rankRows', () => {
  it('sorts hottest first, stable on contract name', () => {
    const rows = [
      row('wheat', [{ proximity: 0.1 }]),
      row('corn', [{ fired: true }]),
      row('cocoa', [{ proximity: 0.1 }]),
    ];
    expect(rankRows(rows).map((r) => r.contract)).toEqual(['corn', 'cocoa', 'wheat']);
  });
  it('does not mutate the input', () => {
    const rows = [row('b', [{ proximity: 0.1 }]), row('a', [{ fired: true }])];
    rankRows(rows);
    expect(rows.map((r) => r.contract)).toEqual(['b', 'a']);
  });
});

describe('cellLabel', () => {
  it('shows a direction glyph + active/threshold', () => {
    expect(cellLabel(card({ direction: '+', n_active: 2, threshold: 3 }))).toBe('▲ 2/3');
    expect(cellLabel(card({ direction: '-', n_active: 1, threshold: 2 }))).toBe('▼ 1/2');
  });
});
