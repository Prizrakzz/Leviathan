import { describe, expect, it } from 'vitest';
import {
  EMPTY_FINDINGS,
  finalizeFindings,
  hasFindings,
  parsePartial,
  reduceFindings,
  type Findings,
} from './partials';
import type { PartialStage, StageEvent } from './schema';

// ── the discriminated union, pinned at TYPE level ──────────────────────────────────────────────────
// This function only compiles if `PartialStage` discriminates on `stage`: each branch must see EXACTLY
// that kind's fields (a wrong field name, or a field borrowed from a sibling kind, is a build failure —
// `npm run build` runs tsc, so this is a real gate, not a comment). The `never` default proves the union
// is exhaustively handled: adding a kind without handling it here stops the build.
function describeKind(p: PartialStage): string {
  switch (p.stage) {
    case 'plan':
      return `plan:${p.intent}:${p.contracts.join('+')}`;
    case 'walk':
      return `walk:${p.nodes}:${p.depth}`;
    case 'regime':
      return `regime:${p.contract}:${p.regime}:${p.direction}:${Object.keys(p.basis).join('+')}`;
    case 'number':
      return `number:${p.table}:${p.metric}:${p.value}:${p.unit ?? '-'}:${p.asof}`;
    case 'chain':
      return `chain:${p.chain_id}:${p.hops.join('>')}`;
    case 'evidence':
      return `evidence:${p.node}:${p.kept}`;
    case 'drafting':
      return 'drafting';
    case 'verified':
      return `verified:${p.strips}`;
    default: {
      const exhaustive: never = p;
      return exhaustive;
    }
  }
}

const feed = (events: unknown[]): Findings => {
  let f: Findings = { ...EMPTY_FINDINGS };
  for (const e of events) {
    const p = parsePartial(e);
    if (p) f = reduceFindings(f, p);
  }
  return f;
};

describe('parsePartial — the wire→union boundary', () => {
  it('narrows every content-bearing kind to its own shape', () => {
    const wire: StageEvent[] = [
      { stage: 'plan', intent: 'hybrid', contracts: ['corn_cbot', 'soybean_cbot'] },
      { stage: 'walk', nodes: 34, depth: 3 },
      { stage: 'regime', contract: 'corn_cbot', regime: 'export_pace_surge', direction: 'bullish',
        basis: { fgis_inspections: { date: '2026-07-18', source: 'usda_fgis' } } },
      { stage: 'number', table: 'silver_psd', metric: 'su_ratio', value: 0.36, unit: 'ratio', asof: '2026-06-11' },
      { stage: 'chain', chain_id: 'palm_sbo_sbm', hops: ['palm', 'sbo', 'sbm'] },
      { stage: 'evidence', node: 'export_pace', kept: 12 },
      { stage: 'drafting' },
      { stage: 'verified', strips: 7 },
    ];
    expect(wire.map((e) => describeKind(parsePartial(e) as PartialStage))).toEqual([
      'plan:hybrid:corn_cbot+soybean_cbot',
      'walk:34:3',
      'regime:corn_cbot:export_pace_surge:bullish:fgis_inspections',
      'number:silver_psd:su_ratio:0.36:ratio:2026-06-11',
      'chain:palm_sbo_sbm:palm>sbo>sbm',
      'evidence:export_pace:12',
      'drafting',
      'verified:7',
    ]);
  });

  it('UNKNOWN-KIND FALLBACK: a newer server’s kind is ignored, never thrown on, never rendered', () => {
    // invariant 3 — an older SPA WILL meet a newer server.
    expect(parsePartial({ stage: 'quantum_flux', payload: { anything: true } })).toBeNull();
    expect(parsePartial({ stage: 'chain_v2', chain_id: 'x', hops: ['a'] })).toBeNull();
    // milestone ticks keep their own path (Pipeline reads stages[]) — not findings.
    for (const s of ['accepted', 'planning', 'walking', 'retrieving', 'numbers', 'synthesizing', 'verifying', 'floor', 'token'])
      expect(parsePartial({ stage: s })).toBeNull();
    // junk of every shape
    for (const junk of [null, undefined, 42, 'plan', [], {}, { stage: 7 }])
      expect(() => parsePartial(junk)).not.toThrow();
    for (const junk of [null, undefined, 42, 'plan', [], {}, { stage: 7 }]) expect(parsePartial(junk)).toBeNull();
  });

  it('drops a KNOWN kind whose required fields are missing or mistyped (no half-populated row)', () => {
    expect(parsePartial({ stage: 'plan' })).toBeNull(); // no intent
    expect(parsePartial({ stage: 'walk', nodes: 'lots' })).toBeNull();
    expect(parsePartial({ stage: 'regime', contract: 'corn_cbot' })).toBeNull(); // no regime
    expect(parsePartial({ stage: 'number', table: 't', metric: 'm' })).toBeNull(); // no value
    expect(parsePartial({ stage: 'number', table: 't', metric: 'm', value: {} })).toBeNull();
    expect(parsePartial({ stage: 'number', table: 't', metric: 'm', value: '  ' })).toBeNull(); // unresolved
    // …but a real zero is a real number and must survive
    expect(parsePartial({ stage: 'number', table: 't', metric: 'm', value: 0 })).toMatchObject({ value: 0 });
    expect(parsePartial({ stage: 'chain', hops: ['a'] })).toBeNull(); // no chain_id
    expect(parsePartial({ stage: 'evidence', kept: 3 })).toBeNull(); // no node
  });

  it('tolerates thin-but-valid payloads with documented defaults', () => {
    expect(parsePartial({ stage: 'plan', intent: 'numbers_only' })).toEqual({
      stage: 'plan', intent: 'numbers_only', contracts: [],
    });
    expect(parsePartial({ stage: 'walk', nodes: 5 })).toEqual({ stage: 'walk', nodes: 5, depth: 0 });
    expect(parsePartial({ stage: 'number', table: 't', metric: 'm', value: '1.2' })).toEqual({
      stage: 'number', table: 't', metric: 'm', value: '1.2', unit: null, asof: '',
    });
    expect(parsePartial({ stage: 'verified' })).toEqual({ stage: 'verified', strips: 0 });
    // a basis whose entries are junk keeps the DRIVER (that it fired is engine truth) and drops the junk
    const r = parsePartial({ stage: 'regime', contract: 'c', regime: 'r', basis: { d: 'nope', e: { date: 1 } } });
    expect(r).toEqual({ stage: 'regime', contract: 'c', regime: 'r', direction: '', basis: { d: {}, e: {} } });
  });

  it('never leaks prose: only the contracted fields survive the boundary', () => {
    const p = parsePartial({
      stage: 'regime', contract: 'c', regime: 'r', direction: 'bullish', basis: {},
      document_text: 'the full source document…', api_key: 'sk-live-123',
    });
    expect(Object.keys(p as object).sort()).toEqual(['basis', 'contract', 'direction', 'regime', 'stage']);
  });
});

describe('reduceFindings — accumulation per kind', () => {
  it('accumulates each kind into its own structured list', () => {
    const f = feed([
      { stage: 'plan', intent: 'hybrid', contracts: ['corn_cbot'] },
      { stage: 'walk', nodes: 34, depth: 3 },
      { stage: 'regime', contract: 'corn_cbot', regime: 'export_pace_surge', direction: 'bullish',
        basis: { fgis: { date: '2026-07-18', source: 'usda_fgis' } } },
      { stage: 'regime', contract: 'corn_cbot', regime: 'stocks_tight', direction: 'bullish', basis: {} },
      { stage: 'number', table: 'silver_psd', metric: 'su_ratio', value: 0.36, unit: null, asof: '2026-06-11' },
      { stage: 'chain', chain_id: 'palm_sbo_sbm', hops: ['palm', 'sbo', 'sbm'] },
      { stage: 'evidence', node: 'export_pace', kept: 12 },
      { stage: 'evidence', node: 'stocks', kept: 9 },
    ]);
    expect(f.plan).toMatchObject({ intent: 'hybrid', contracts: ['corn_cbot'] });
    expect(f.walk).toMatchObject({ nodes: 34, depth: 3 });
    expect(f.regimes.map((r) => r.regime)).toEqual(['export_pace_surge', 'stocks_tight']);
    expect(f.regimes[0]!.basis).toEqual([{ driver: 'fgis', date: '2026-07-18', source: 'usda_fgis' }]);
    expect(f.numbers).toHaveLength(1);
    expect(f.chains[0]!.hops).toEqual(['palm', 'sbo', 'sbm']);
    expect(f.evidence.map((e) => e.node)).toEqual(['export_pace', 'stocks']);
    expect(f.keptTotal).toBe(21);
    // arrival order is preserved across kinds (the feed reads as a log)
    expect(f.seq).toBe(8);
  });

  it('UPSERTS by identity: a re-emitted finding updates its row instead of duplicating it', () => {
    const f = feed([
      { stage: 'regime', contract: 'corn_cbot', regime: 'r1', direction: 'bullish', basis: {} },
      { stage: 'evidence', node: 'n1', kept: 4 },
      { stage: 'regime', contract: 'corn_cbot', regime: 'r1', direction: 'bearish', basis: {} },
      { stage: 'evidence', node: 'n1', kept: 9 },
    ]);
    expect(f.regimes).toHaveLength(1);
    expect(f.regimes[0]!.direction).toBe('bearish');
    expect(f.evidence).toHaveLength(1);
    expect(f.keptTotal).toBe(9); // recomputed, NOT summed — no double count
  });

  it('an identical re-emit is a NO-OP (same object reference → no wasted render)', () => {
    const one = parsePartial({ stage: 'regime', contract: 'c', regime: 'r', direction: 'up', basis: {} })!;
    const a = reduceFindings({ ...EMPTY_FINDINGS }, one);
    const b = reduceFindings(a, one);
    expect(b).toBe(a);
    const draft = parsePartial({ stage: 'drafting' })!;
    const c = reduceFindings(a, draft);
    expect(reduceFindings(c, draft)).toBe(c);
  });

  it('keeps a re-emitted row in its original slot (no reorder, no re-animation)', () => {
    const f = feed([
      { stage: 'regime', contract: 'c', regime: 'first', direction: 'up', basis: {} },
      { stage: 'regime', contract: 'c', regime: 'second', direction: 'up', basis: {} },
      { stage: 'regime', contract: 'c', regime: 'first', direction: 'down', basis: {} },
    ]);
    expect(f.regimes.map((r) => r.regime)).toEqual(['first', 'second']);
    expect(f.regimes[0]!.seq).toBeLessThan(f.regimes[1]!.seq);
  });
});

describe('phase + the citation activation rule', () => {
  it('advances idle → planning → walking → drafting → verified', () => {
    const seen: string[] = [];
    let f: Findings = { ...EMPTY_FINDINGS };
    seen.push(f.phase);
    for (const e of [
      { stage: 'plan', intent: 'hybrid', contracts: [] },
      { stage: 'walk', nodes: 3, depth: 1 },
      { stage: 'drafting' },
      { stage: 'verified', strips: 2 },
    ]) {
      f = reduceFindings(f, parsePartial(e)!);
      seen.push(f.phase);
    }
    expect(seen).toEqual(['idle', 'planning', 'walking', 'drafting', 'verified']);
  });

  it('NEVER goes backwards: a straggler partial after drafting keeps the phase', () => {
    let f = feed([
      { stage: 'plan', intent: 'hybrid', contracts: [] },
      { stage: 'walk', nodes: 3, depth: 1 },
      { stage: 'drafting' },
    ]);
    expect(f.phase).toBe('drafting');
    f = reduceFindings(f, parsePartial({ stage: 'walk', nodes: 9, depth: 2 })!);
    expect(f.phase).toBe('drafting'); // the walk row updates; the phase does not rewind
    expect(f.walk).toMatchObject({ nodes: 9 });
    f = reduceFindings(f, parsePartial({ stage: 'verified', strips: 1 })!);
    f = reduceFindings(f, parsePartial({ stage: 'plan', intent: 'hybrid', contracts: ['late'] })!);
    expect(f.phase).toBe('verified');
  });

  it('citations are INERT until verified, then LIVE — and `result` alone also activates them', () => {
    const streaming = feed([
      { stage: 'plan', intent: 'hybrid', contracts: [] },
      { stage: 'regime', contract: 'c', regime: 'r', direction: 'up', basis: {} },
      { stage: 'drafting' },
    ]);
    expect(streaming.citationsLive).toBe(false); // pre-verifier: nothing clickable
    expect(streaming.strips).toBeNull();

    const verified = reduceFindings(streaming, parsePartial({ stage: 'verified', strips: 7 })!);
    expect(verified.citationsLive).toBe(true);
    expect(verified.strips).toBe(7);

    // An older server never sends `verified`; the terminal result must still activate.
    const noVerifiedStage = finalizeFindings(streaming);
    expect(noVerifiedStage.citationsLive).toBe(true);
    expect(noVerifiedStage.phase).toBe('verified');
  });

  it('finalize on a turn that streamed NOTHING leaves the phase idle (nothing to show)', () => {
    const f = finalizeFindings({ ...EMPTY_FINDINGS });
    expect(f.phase).toBe('idle');
    expect(f.citationsLive).toBe(true);
    expect(hasFindings(f)).toBe(false);
  });
});

describe('hasFindings — the degradation gate', () => {
  it('is false for empty/absent findings and true once anything lands', () => {
    expect(hasFindings(null)).toBe(false);
    expect(hasFindings(undefined)).toBe(false);
    expect(hasFindings({})).toBe(false); // an older cached state shape carries none of the keys
    expect(hasFindings(EMPTY_FINDINGS)).toBe(false);
    expect(hasFindings(feed([{ stage: 'evidence', node: 'n', kept: 1 }]))).toBe(true);
    expect(hasFindings(feed([{ stage: 'plan', intent: 'hybrid', contracts: [] }]))).toBe(true);
  });
});
