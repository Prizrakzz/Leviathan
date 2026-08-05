import { describe, expect, it } from 'vitest';
import type { RespondResult } from '@/api/schema';
import { MOCK_RESULT } from '@/api/mock';
import { citedDrivers, partitionReceipts } from './partition';

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

describe('citedDrivers (D-TW-16)', () => {
  it('unions the fired-regime matches with trace.drivers, regime order first, deduped', () => {
    const r = {
      trace: {
        fired_regimes: [{ matched: ['frost', 'low_stocks'] }, { matched: ['frost'] }],
        drivers: ['low_stocks', 'biennial_off_year'],
      },
    } as unknown as RespondResult;
    expect(citedDrivers(r)).toEqual(['frost', 'low_stocks', 'biennial_off_year']);
  });

  it('reads the mock turn (the ids the map lights) and survives a trace-less turn', () => {
    expect(citedDrivers(MOCK_RESULT)).toEqual(['frost', 'low_stocks']);
    expect(citedDrivers({ answer: '' } as RespondResult)).toEqual([]);
  });

  it('drops non-string / blank entries — trace is untrusted wire JSON', () => {
    const r = {
      trace: { fired_regimes: [{ matched: [1, '', 'frost', null] }, {}, 'nope'], drivers: [{ id: 'x' }, 'dry'] },
    } as unknown as RespondResult;
    expect(citedDrivers(r)).toEqual(['frost', 'dry']);
  });
});
