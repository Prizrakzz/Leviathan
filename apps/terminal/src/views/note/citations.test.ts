import { describe, expect, it } from 'vitest';
import { resolvedFor, resolvedMap, tokenizeCitations } from './citations';

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

describe('resolvedFor (6.4 unified live + durable)', () => {
  it('durable turn: official name from structured.sources + snippet from citation locator', () => {
    const turn = {
      structured: { sources: [{ ref: 1, source: 'USDA WASDE', date: '2022-01-01', source_key: 's3://w/1' }] },
      sources: [{ id: 'E1', kind: 'evidence', source: 'usda_wasde', locator: { source_key: 's3://w/1', snippet: 'stocks thin' } }],
    };
    const m = resolvedFor(turn);
    expect(m['1']?.source).toBe('USDA WASDE'); // official, not the raw usda_wasde
    expect(m['1']?.text).toBe('stocks thin'); // durable snippet joined by source_key
  });

  it('live result: official name wins over the raw verifier source; numbers carry a query locator', () => {
    const live = {
      structured: { sources: [{ ref: 1, source: 'USDA FAS GAIN Report — Corn', source_key: 's3://g/1' }, { ref: 'N1', source: 'USDA PSD' }] },
      trace: { citation_verifier: { resolved: { '1': { source: 'usda_gain_corn', date: '2022', text: 'corn note' } } } },
      citations: [{ id: 'N1', kind: 'number', locator: { kind: 'number', table: 'silver_psd', commodity: 'corn' } }],
    };
    const m = resolvedFor(live);
    expect(m['1']?.source).toBe('USDA FAS GAIN Report — Corn'); // official, not raw
    expect(m['1']?.text).toBe('corn note'); // live verifier text
    expect(m['N1']?.locator?.table).toBe('silver_psd'); // number provenance for the popover
  });
});

describe('resolvedFor doc locator (6.5 click-to-page)', () => {
  it('emits a doc locator {kind, source_key, snippet} for a structured source with a source_key', () => {
    const turn = {
      structured: { sources: [{ ref: 1, source: 'USDA WASDE', date: '2022-01-01', source_key: 's3://w/1' }] },
      sources: [{ id: 'E1', kind: 'evidence', locator: { source_key: 's3://w/1', snippet: 'stocks thin' } }],
    };
    const loc = resolvedFor(turn)['1']?.locator;
    expect(loc?.kind).toBe('doc');
    expect(loc?.source_key).toBe('s3://w/1');
    expect(loc?.snippet).toBe('stocks thin'); // the resolved snippet flows into the locator
  });

  it('passes char_start/offset_kind through WHEN the source carries them (D1 exact page)', () => {
    const turn = {
      structured: { sources: [{ ref: 1, source: 'GAIN', source_key: 's3://g/1', char_start: 4096, offset_kind: 'exact' }] },
      sources: [{ id: 'E1', kind: 'evidence', locator: { source_key: 's3://g/1', snippet: 'frost' } }],
    };
    const loc = resolvedFor(turn)['1']?.locator;
    expect(loc?.char_start).toBe(4096);
    expect(loc?.offset_kind).toBe('exact');
  });

  it('OMITS char_start/offset_kind when the source lacks them (legacy props, defensive)', () => {
    const turn = {
      structured: { sources: [{ ref: 1, source: 'GAIN', source_key: 's3://g/1' }] },
      sources: [{ id: 'E1', kind: 'evidence', locator: { source_key: 's3://g/1', snippet: 'frost' } }],
    };
    const loc = resolvedFor(turn)['1']?.locator ?? {};
    expect(loc.kind).toBe('doc');
    expect('char_start' in loc).toBe(false);
    expect('offset_kind' in loc).toBe(false);
  });

  it('a number ref keeps its number locator even when its source has a source_key (precedence)', () => {
    const turn = {
      structured: { sources: [{ ref: 'N1', source: 'USDA PSD', source_key: 's3://n/1' }] },
      citations: [{ id: 'N1', kind: 'number', locator: { kind: 'number', table: 'silver_psd', commodity: 'corn' } }],
    };
    const loc = resolvedFor(turn)['N1']?.locator;
    expect(loc?.kind).toBe('number'); // number wins over the doc locator
    expect(loc?.table).toBe('silver_psd');
  });

  it('no source_key → no locator (unchanged for number-less, key-less refs)', () => {
    const turn = {
      structured: { sources: [{ ref: 1, source: 'A wire report', date: '2022-01-01' }] },
    };
    expect(resolvedFor(turn)['1']?.locator).toBeUndefined();
  });
});
