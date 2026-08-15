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

  it('resolves a TYPED handle [E3] against a BARE-integer ledger key (P9 prose contract)', () => {
    // served prose is "[E3]" but the ledger is keyed by the bare digit "3"; pre-fix the tokenizer looked
    // up resolved["E3"], missed, and left "[E3]" as plain text (chip suppressed).
    const intLedger = { '3': { source: 'USDA WASDE', date: '2022-01-01' } };
    const segs = tokenizeCitations('drought tightened [E3] hard', intLedger);
    expect(segs.map((s) => s.kind)).toEqual(['text', 'cite', 'text']);
    const cite = segs.find((s) => s.kind === 'cite') as { ref: string; resolved: { source?: string } };
    expect(cite.ref).toBe('E3'); // display ref stays TYPED
    expect(cite.resolved.source).toBe('USDA WASDE'); // resolved by the bare digit "3"
  });

  // ── T1-7: the LETTER-SUFFIXED handle ────────────────────────────────────────────────────────────────
  it('CHIPS a letter-suffixed handle [N1b] and routes it to its CALL (same chart target as [N1])', () => {
    // Pre-fix the grammar was `\[([A-Za-z]?)(\d+)\]`, so "[N1b]" matched nothing and reached the reader as
    // literal text -- a dead marker beside a real, footed row. `citations._mint_row_citations` mints N1b as
    // a COMPLETION ROW of call 1: the same query, hence the same chart locator, a different period.
    const led = {
      '1': { source: 'USDA PSD', date: '2021-06-11', locator: { kind: 'number', table: 'silver_psd' } },
    };
    const segs = tokenizeCitations('stocks fell [N1] from [N1b] a year earlier.', led);
    const cites = segs.filter((s) => s.kind === 'cite') as { ref: string; resolved: { locator?: unknown } }[];
    expect(cites.map((c) => c.ref)).toEqual(['N1', 'N1b']); // the SUFFIX survives into the display/click ref
    expect(cites[1]?.resolved.locator).toBe(cites[0]?.resolved.locator); // ...onto call 1's chart target
  });

  it('a suffixed handle prefers its OWN sibling entry when the ledger carries one', () => {
    const led = {
      '1': { source: 'USDA PSD', locator: { kind: 'number', table: 'silver_psd', period: '2025' } },
      '1b': { source: 'USDA PSD', locator: { kind: 'number', table: 'silver_psd', period: '2024' } },
    };
    const cite = tokenizeCitations('was [N1b] then', led).find((s) => s.kind === 'cite') as {
      ref: string;
      resolved: { locator?: { period?: string } };
    };
    expect(cite.ref).toBe('N1b');
    expect(cite.resolved.locator?.period).toBe('2024'); // the ROW's period, not the headline's
  });

  it('an unresolved suffixed handle still stays plain text (no new fabrication surface)', () => {
    expect(tokenizeCitations('see [N9c] gone', resolved)).toEqual([
      { kind: 'text', text: 'see [N9c] gone' },
    ]);
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

  it('number provenance resolves by the BARE ledger digit so a rendered [N] chip keeps its query (H1)', () => {
    // The post-P9 prod shape: the ledger ref is the BARE INTEGER "4" while the machine citation id is "N4".
    // Pre-fix numLocByRef was keyed by "N4" but the ref iterated is the bare "4" ⇒ the locator was dropped
    // and the [N4] chip's provenance line went blank. resolvedInline resolves [N4] by digit ⇒ key "4".
    const r = {
      structured: { sources: [{ ref: 4, source: 'USDA PSD' }] },
      citations: [{ id: 'N4', kind: 'number', locator: { kind: 'number', table: 'silver_psd', commodity: 'corn' } }],
    };
    const m = resolvedFor(r);
    expect(m['4']?.locator?.table).toBe('silver_psd'); // provenance found under the bare digit
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

  it('T1-7: a suffixed number citation is admitted under its own key, with its ROW period', () => {
    // `cit.unify` ships `N1` (the headline) and `N1b` (a completion row of the SAME call): same table +
    // metric, its own `locator.period`. Both must be addressable, and the sibling must not overwrite or be
    // overwritten by the headline.
    const turn = {
      structured: { sources: [{ ref: 1, source: 'USDA PSD', date: '2021-06-11' }] },
      citations: [
        { id: 'N1', kind: 'number', locator: { kind: 'number', table: 'silver_psd', period: '2025' } },
        { id: 'N1b', kind: 'number', locator: { kind: 'number', table: 'silver_psd', period: '2024' } },
      ],
    };
    const m = resolvedFor(turn);
    expect(m['1']?.locator?.period).toBe('2025');
    expect(m['1b']?.locator?.period).toBe('2024'); // the sibling keeps ITS row
    expect(m['1b']?.locator?.table).toBe('silver_psd'); // ...on the same chart target
    // and it INHERITS the call's display identity rather than hovering as a bare " · "
    expect(m['1b']?.source).toBe('USDA PSD');
    expect(m['1b']?.date).toBe('2021-06-11');
  });

  it('T1-7: a turn with NO suffixed citations is byte-identical (anti-vacuity)', () => {
    const turn = {
      structured: { sources: [{ ref: 1, source: 'USDA WASDE', date: '2022-01-01' }] },
      citations: [{ id: 'N1', kind: 'number', locator: { kind: 'number', table: 'silver_psd' } }],
    };
    expect(Object.keys(resolvedFor(turn))).toEqual(['1']);
  });

  it('no source_key → no locator (unchanged for number-less, key-less refs)', () => {
    const turn = {
      structured: { sources: [{ ref: 1, source: 'A wire report', date: '2022-01-01' }] },
    };
    expect(resolvedFor(turn)['1']?.locator).toBeUndefined();
  });
});
