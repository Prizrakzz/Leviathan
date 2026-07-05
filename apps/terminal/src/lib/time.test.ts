import { describe, expect, it } from 'vitest';
import { relTime } from './time';

describe('relTime', () => {
  const now = new Date('2026-07-05T12:00:00Z');
  it('formats compact relative times', () => {
    expect(relTime('2026-07-05T11:59:40Z', now)).toBe('now');
    expect(relTime('2026-07-05T11:55:00Z', now)).toBe('5m');
    expect(relTime('2026-07-05T09:00:00Z', now)).toBe('3h');
    expect(relTime('2026-07-01T12:00:00Z', now)).toBe('4d');
    expect(relTime('2026-05-01T12:00:00Z', now)).toBe('2026-05-01');
  });
  it('is safe on missing/garbage input', () => {
    expect(relTime(undefined, now)).toBe('');
    expect(relTime('not-a-date', now)).toBe('');
  });
});
