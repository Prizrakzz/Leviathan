/**
 * F7 SKEPTIC — CROSS-LANE CONFORMANCE.
 *
 * Lane A (python emitters) and Lane B (this bundle) were built against the same pinned contract but never
 * ran against each other. This suite closes that gap with REAL backend output: `f7_backend_frames.json` is
 * the verbatim `data:` payload of every `event: stage` frame produced by driving orchestrator.respond ->
 * planner.ground -> answer._answer_l2 through the real `/v1/respond/stream` route, serialised by the same
 * `json.dumps(payload, default=str)` the browser receives. Nothing in this file is hand-written wire data.
 *
 * What it proves, in BOTH directions:
 *   forward  — every content-bearing frame the backend emits parses, and lands as a finding;
 *   backward — the parsed partial's key set is IDENTICAL to the frame's, so neither lane carries a field
 *              the other does not (a rename or a silent drop fails here, not in production).
 */
import { describe, expect, it } from 'vitest';
import frames from './fixtures/f7_backend_frames.json';
import {
  EMPTY_FINDINGS,
  finalizeFindings,
  hasFindings,
  parsePartial,
  reduceFindings,
  type Findings,
} from './partials';
import type { PartialStage, StageEvent } from './schema';

type Frame = Record<string, unknown> & { stage: string };
const LANES = frames as unknown as Record<string, Frame[]>;

/** The pinned contract, restated here so this file is an independent witness (not a re-import of either
 *  lane's own constant). `stage` is the discriminator every frame carries. */
const PINNED: Record<string, string[]> = {
  plan: ['stage', 'intent', 'contracts'],
  walk: ['stage', 'nodes', 'depth'],
  regime: ['stage', 'contract', 'regime', 'direction', 'basis'],
  number: ['stage', 'table', 'metric', 'value', 'unit', 'asof'],
  chain: ['stage', 'chain_id', 'hops'],
  evidence: ['stage', 'node', 'kept'],
  drafting: ['stage'],
  verified: ['stage', 'strips'],
};

const all = (): Frame[] => Object.values(LANES).flat();
const of = (kind: string): Frame[] => all().filter((f) => f.stage === kind);
const keys = (o: object) => Object.keys(o).sort();

function play(lane: Frame[]): Findings {
  let f: Findings = { ...EMPTY_FINDINGS };
  for (const frame of lane) {
    const p = parsePartial(frame as unknown as StageEvent);
    if (p) f = reduceFindings(f, p);
  }
  return f;
}

describe('the fixture is real backend output, not a hand-written mock', () => {
  it('covers every lane and every pinned kind', () => {
    expect(Object.keys(LANES).sort()).toEqual([
      'chain',
      'hybrid',
      'multi_number',
      'numbers_only',
      'reasoning',
      'regime',
    ]);
    const kinds = new Set(all().map((f) => f.stage));
    for (const kind of Object.keys(PINNED)) expect(kinds.has(kind), `no real ${kind} frame captured`).toBe(true);
  });

  it('carries the milestone ticks too, so the unknown-kind path is exercised for real', () => {
    const ticks = all().filter((f) => !(f.stage in PINNED));
    expect(ticks.map((f) => f.stage)).toEqual(
      expect.arrayContaining(['accepted', 'planning', 'walking', 'retrieving', 'synthesizing', 'verifying']),
    );
  });
});

describe('1 · field-by-field conformance, both directions', () => {
  for (const kind of Object.keys(PINNED)) {
    it(`${kind}: backend key set === pinned === parsed key set`, () => {
      const seen = of(kind);
      expect(seen.length, `no real ${kind} frame`).toBeGreaterThan(0);
      for (const frame of seen) {
        // BACKWARD: the emitter sends exactly the pinned fields — no extra, no missing, none renamed.
        expect(keys(frame)).toEqual([...PINNED[kind]!].sort());
        // FORWARD: the FE parser accepts it and narrows to exactly the same key set.
        const p = parsePartial(frame as unknown as StageEvent);
        expect(p, `${kind} frame was DROPPED by parsePartial: ${JSON.stringify(frame)}`).not.toBeNull();
        expect(keys(p as object)).toEqual([...PINNED[kind]!].sort());
      }
    });
  }

  it('every parsed value is === the wire value (no coercion, no drift)', () => {
    for (const frame of all()) {
      const p = parsePartial(frame as unknown as StageEvent) as unknown as Record<string, unknown> | null;
      if (!p) continue;
      for (const k of Object.keys(p)) {
        const a = p[k];
        const b = frame[k];
        if (typeof a === 'object' && a !== null) expect(a).toEqual(b);
        else expect(a, `${frame.stage}.${k} drifted`).toBe(b);
      }
    }
  });

  it('number.value survives as its wire type (backend sends a string here; a float must survive too)', () => {
    const n = parsePartial(of('number')[0] as unknown as StageEvent) as Extract<PartialStage, { stage: 'number' }>;
    expect(typeof n.value).toBe('string');
    expect(n.value).toBe('31400000');
    // pg/Athena hand back floats and Decimals (`default=str` turns a Decimal into a string) — both must land.
    for (const v of [31400000, 31400000.5, 0, -1.5, '31400000.00'])
      expect(parsePartial({ ...(of('number')[0] as object), value: v } as StageEvent)).not.toBeNull();
  });

  it('regime.basis: the backend projects to {date,source} only, and the FE keeps both', () => {
    const r = parsePartial(of('regime')[0] as unknown as StageEvent) as Extract<PartialStage, { stage: 'regime' }>;
    expect(r.basis).toEqual({ frost: { date: '2021-07-20', source: 'GAIN' } });
    for (const b of Object.values(r.basis)) expect(keys(b)).toEqual(['date', 'source']);
  });

  it('chain.hops: the vertical composer drops collapsed hops, the horizontal one dedups the shared node', () => {
    const [vertical, horizontal] = of('chain').map(
      (f) => parsePartial(f as unknown as StageEvent) as Extract<PartialStage, { stage: 'chain' }>,
    );
    expect(vertical!.hops).toEqual(['safrinha', 'Brazil production_mt']);
    expect(horizontal!.hops).toEqual(['palm_oil', 'soybean_oil', 'soybean_meal']);
  });

  it('milestone ticks are dropped, never rendered as findings', () => {
    for (const frame of all().filter((f) => !(f.stage in PINNED)))
      expect(parsePartial(frame as unknown as StageEvent), `${frame.stage} leaked into findings`).toBeNull();
  });
});

describe('2 · a real turn, replayed through the real reducer', () => {
  it('reasoning: plan -> walk -> evidence -> drafting -> verified', () => {
    const f = play(LANES.reasoning!);
    expect(f.plan).toMatchObject({ intent: 'reasoning', contracts: [] });
    expect(f.walk).toMatchObject({ nodes: 2, depth: 1 });
    // SORTED on purpose: `evidence` is emitted from planner.ground's fill POOL, so two identical turns can
    // land these legs in either order. That is the design (the feed shows what landed, when it landed) and
    // it means no consumer may assume a fixed order — this fixture was captured twice and swapped them.
    expect(f.evidence.map((e) => e.node).sort()).toEqual([
      'contract:arabica_coffee:arabica_coffee',
      'driver:arabica_coffee:frost',
    ]);
    expect(f.keptTotal).toBe(2);
    expect(f.phase).toBe('verified');
    expect(f.strips).toBe(2); // the turn really did strip 2 unbacked citations
    expect(f.citationsLive).toBe(true);
  });

  it('hybrid: the number from the worker thread lands alongside the walk', () => {
    const f = play(LANES.hybrid!);
    expect(f.numbers).toHaveLength(1);
    expect(f.numbers[0]).toMatchObject({
      table: 'silver_psd',
      metric: 'ending_stocks_mt',
      value: '31400000',
      unit: 'mt',
      asof: '2024-02-08',
    });
    // arrival order is preserved across lanes: the number landed BETWEEN the two evidence legs
    const seq = [f.walk!.seq, f.numbers[0]!.seq, f.evidence[1]!.seq];
    expect([...seq].sort((a, b) => a - b)).toEqual(seq);
    expect(f.phase).toBe('verified');
  });

  it('numbers_only emits NO drafting and NO verified — the terminal result must finish the turn', () => {
    const mid = play(LANES.numbers_only!);
    expect(mid.phase).toBe('planning');
    expect(mid.citationsLive).toBe(false);
    const done = finalizeFindings(mid);
    expect(done.phase).toBe('verified');
    expect(done.citationsLive).toBe(true);
  });

  it('two numbers off ONE vintage both survive (they differ only by value)', () => {
    // REGRESSION. The pinned `number` contract carries no commodity/country/period — those stay in the
    // note — so corn and wheat ending stocks off the same WASDE release arrive as two frames identical in
    // table, metric and asof. Keyed on those three alone, the wheat row silently REPLACED the corn row and
    // the feed lost a resolved number without a trace. Both must land.
    const raw = LANES.multi_number!;
    expect(raw).toHaveLength(2);
    expect(keys(raw[0]!)).toEqual(keys(raw[1]!));
    expect([raw[0]!.table, raw[0]!.metric, raw[0]!.asof]).toEqual([raw[1]!.table, raw[1]!.metric, raw[1]!.asof]);
    const f = play(raw);
    expect(f.numbers.map((n) => n.value)).toEqual([31400000, 6900000]);
    // ...and an identical RE-emit still collapses: two rows agreeing on all five fields render the same.
    expect(play([...raw, raw[0]!]).numbers).toHaveLength(2);
  });

  it('regime lane: one finding per firing, with its dated basis', () => {
    const f = play(LANES.regime!);
    expect(f.regimes).toHaveLength(1);
    expect(f.regimes[0]).toMatchObject({ contract: 'arabica', regime: 'squeeze', direction: '+' });
    expect(f.regimes[0]!.basis).toEqual([{ driver: 'frost', date: '2021-07-20', source: 'GAIN' }]);
  });

  it('every lane that emitted a partial is renderable; a partial-free lane renders nothing', () => {
    for (const [lane, fr] of Object.entries(LANES)) expect(hasFindings(play(fr)), lane).toBe(true);
    expect(hasFindings(EMPTY_FINDINGS)).toBe(false);
  });
});

describe('3 · forward compatibility: an older bundle meets a newer server', () => {
  it('an unknown kind is dropped without throwing', () => {
    expect(parsePartial({ stage: 'cascade_probe', contract: 'corn', z: 2.4 } as unknown as StageEvent)).toBeNull();
  });

  it('a known kind that GROWS a field still parses, and the extra field is not carried', () => {
    // the one direction forward-compat must absorb: the backend adds `basis_n` to `regime` next quarter.
    const grown = { ...(of('regime')[0] as object), basis_n: 3, confidence: 0.9 };
    const p = parsePartial(grown as unknown as StageEvent);
    expect(p).not.toBeNull();
    expect(keys(p as object)).toEqual([...PINNED.regime!].sort());
  });

  it('replaying a lane with every frame mutated to an unknown kind yields NO findings', () => {
    let f: Findings = { ...EMPTY_FINDINGS };
    for (const frame of LANES.hybrid!) {
      const p = parsePartial({ ...frame, stage: `x_${frame.stage}` } as unknown as StageEvent);
      if (p) f = reduceFindings(f, p);
    }
    expect(hasFindings(f)).toBe(false);
  });
});
