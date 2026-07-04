import { describe, expect, it } from 'vitest';
import { MOCK_RESULT } from '@/api/mock';
import { partitionReceipts } from './partition';

describe('partitionReceipts', () => {
  it('splits cited / retrieved-but-uncited / stripped', () => {
    const r = partitionReceipts(MOCK_RESULT);
    expect(r.cited).toHaveLength(3); // [1], [2], [N1]
    expect(r.cited.some((c) => c.kind === 'number' && c.ref === 'N1')).toBe(true);
    expect(r.uncited).toHaveLength(2); // ico_report + the pre-frost gain note
    expect(r.strippedCount).toBe(0);
    expect(r.asof).toBe('2021-07-20');
    // cited evidence rows carry the dated snippet
    expect(r.cited[0]?.snippet).toContain('frost');
  });
});
