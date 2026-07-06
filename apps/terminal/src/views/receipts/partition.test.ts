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
    // cited evidence rows carry the dated snippet (6.4: from locator.snippet)
    expect(r.cited[0]?.snippet).toContain('frost');
  });

  it('6.4: ref comes from citation id, cited rows get the OFFICIAL name + source_key for pinning', () => {
    const r = partitionReceipts(MOCK_RESULT);
    // the latent bug fixed: refs render even though live citations are keyed `id`, not `ref`
    expect(r.cited.map((c) => c.ref)).toEqual(['1', '2', 'N1']);
    // cited evidence row shows the OFFICIAL name (joined from structured.sources), not the raw slug
    expect(r.cited[0]?.source).toBe('USDA FAS GAIN Report — Coffee');
    expect(r.cited[0]?.source).not.toContain('_');
    // the pin key is present
    expect(r.cited[0]?.sourceKey).toBe('s3://gain/kc-2021-07-20');
  });
});
