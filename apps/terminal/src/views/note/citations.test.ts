import { describe, expect, it } from 'vitest';
import { resolvedMap, tokenizeCitations } from './citations';

const resolved = {
  '1': { source: 'usda_gain_coffee', date: '2021-07-20' },
  N1: { source: 'silver_psd', date: '2021-06-11' },
};

describe('citation tokenizer', () => {
  it('splits text + resolved citation chips', () => {
    const segs = tokenizeCitations('frost hit [1]; stocks thin [N1].', resolved);
    expect(segs.map((s) => s.kind)).toEqual(['text', 'cite', 'text', 'cite', 'text']);
    expect(segs.filter((s) => s.kind === 'cite').map((s) => (s as { ref: string }).ref)).toEqual(['1', 'N1']);
  });

  it('leaves an unresolved ref as plain text (fabricated refs never chip)', () => {
    const segs = tokenizeCitations('see [9] which was stripped', resolved);
    expect(segs).toEqual([{ kind: 'text', text: 'see [9] which was stripped' }]);
  });

  it('reads the resolved map from trace.citation_verifier', () => {
    const m = resolvedMap({ trace: { citation_verifier: { resolved } } });
    expect(m['1']?.source).toBe('usda_gain_coffee');
    expect(resolvedMap({ trace: {} })).toEqual({});
  });
});
