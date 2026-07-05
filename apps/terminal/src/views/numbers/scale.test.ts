import { describe, expect, it } from 'vitest';
import { MOCK_SERIES } from '@/api/mock';
import { isAnomaly, parsePoints, sparkPath, vintageIndex } from './scale';

describe('numbers scaling', () => {
  it('parses string values to numeric points, dropping empties', () => {
    const pts = parsePoints(MOCK_SERIES.points as Record<string, unknown>[]);
    expect(pts).toHaveLength(6);
    expect(pts[5]).toMatchObject({ period: '2021', value: 0.36 });
  });

  it('sparkPath spans the width and emits one command per point', () => {
    const d = sparkPath([1, 2, 3, 2], 90, 18);
    expect(d.startsWith('M')).toBe(true);
    expect((d.match(/[ML]/g) ?? []).length).toBe(4);
  });

  it('vintageIndex is the last point known at/before the as-of', () => {
    const pts = parsePoints(MOCK_SERIES.points as Record<string, unknown>[]);
    expect(vintageIndex(pts, '2021-07-20')).toBe(5); // 2021 vintage known 2021-06-11
    expect(vintageIndex(pts, '2019-01-01')).toBe(2); // only through the 2018 vintage
  });

  it('flags |z| over threshold', () => {
    expect(isAnomaly('-1.4')).toBe(false);
    expect(isAnomaly('-2.1')).toBe(true);
    expect(isAnomaly(null)).toBe(false);
  });
});
