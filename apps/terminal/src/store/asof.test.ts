import { beforeEach, describe, expect, it } from 'vitest';
import { CORPUS_START, clampDate, shiftDate, today, useAsOf } from './asof';

describe('as-of store (the global horizon)', () => {
  beforeEach(() => useAsOf.getState().goLive());

  it('clamps a future date to today and a pre-1973 date to the corpus start', () => {
    expect(clampDate('2999-01-01')).toBe(today());
    expect(clampDate('1900-01-01')).toBe(CORPUS_START);
    expect(clampDate('2021-07-20')).toBe('2021-07-20');
  });

  it('setAsOf drops live for a past date and goLive restores it', () => {
    useAsOf.getState().setAsOf('2021-07-20');
    expect(useAsOf.getState()).toMatchObject({ asof: '2021-07-20', live: false });
    useAsOf.getState().goLive();
    expect(useAsOf.getState()).toMatchObject({ asof: today(), live: true });
  });

  it('step nudges by one day, or ~a month when large', () => {
    useAsOf.getState().setAsOf('2021-07-20');
    useAsOf.getState().step(-1);
    expect(useAsOf.getState().asof).toBe('2021-07-19');
    useAsOf.getState().step(1, true);
    expect(useAsOf.getState().asof).toBe(shiftDate('2021-07-19', 30));
  });

  it('shiftDate crosses month boundaries correctly', () => {
    expect(shiftDate('2021-01-31', 1)).toBe('2021-02-01');
    expect(shiftDate('2021-03-01', -1)).toBe('2021-02-28');
  });
});
