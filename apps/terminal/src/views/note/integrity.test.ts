import { describe, expect, it } from 'vitest';
import { MOCK_RESULT } from '@/api/mock';
import { computeIntegrity } from './integrity';

describe('computeIntegrity', () => {
  it('derives the strip counts from trace + number statuses', () => {
    const g = computeIntegrity(MOCK_RESULT);
    expect(g).toMatchObject({
      verified: 3,
      stripped: 0,
      lookedUp: 2, // N1, N2 ok
      requested: 3,
      notYetPub: 1, // N3 not-yet-published
      graphVersion: '3a69acfb87c5',
    });
    expect(g.degraded).toBeUndefined();
  });
});
