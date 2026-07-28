import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RespondResult, StageEvent } from './schema';
import type { StreamHandlers } from './sse';
import { useTurn } from './useTurn';

// The hook is driven by hand: `respondStream` captures the handlers and never resolves, so each test
// pushes the exact SSE sequence it wants to assert about (ordering included).
const hoisted = vi.hoisted(() => ({ h: null as StreamHandlers | null }));
vi.mock('./client', () => ({
  respondStream: (_p: unknown, h: StreamHandlers) => {
    hoisted.h = h;
    return new Promise<void>(() => {});
  },
}));

function turn() {
  const hook = renderHook(() => useTurn());
  act(() => hook.result.current.start('why is corn tight?'));
  const send = (...events: StageEvent[]) =>
    act(() => {
      for (const e of events) hoisted.h?.onStage?.(e);
    });
  const finish = (r: Partial<RespondResult> = {}) =>
    act(() => hoisted.h?.onResult?.({ answer: 'a', ...r } as RespondResult));
  return { hook, send, finish, state: () => hook.result.current };
}

const PLAN: StageEvent = { stage: 'plan', intent: 'hybrid', contracts: ['corn_cbot'] };
const WALK: StageEvent = { stage: 'walk', nodes: 34, depth: 3 };
const REGIME: StageEvent = {
  stage: 'regime',
  contract: 'corn_cbot',
  regime: 'export_pace_surge',
  direction: 'bullish',
  basis: { fgis_inspections: { date: '2026-07-18', source: 'usda_fgis' } },
};
const NUMBER: StageEvent = {
  stage: 'number', table: 'silver_psd', metric: 'su_ratio', value: 0.36, unit: 'ratio', asof: '2026-06-11',
};
const CHAIN: StageEvent = { stage: 'chain', chain_id: 'palm_sbo_sbm', hops: ['palm', 'sbo', 'sbm'] };
const EVIDENCE: StageEvent = { stage: 'evidence', node: 'export_pace', kept: 12 };

describe('useTurn — F7 structured accumulation', () => {
  beforeEach(() => {
    hoisted.h = null;
  });

  it('accumulates each content kind into structured state', () => {
    const t = turn();
    t.send(PLAN, WALK, REGIME, NUMBER, CHAIN, EVIDENCE);
    const s = t.state();
    expect(s.plan).toMatchObject({ intent: 'hybrid', contracts: ['corn_cbot'] });
    expect(s.walk).toMatchObject({ nodes: 34, depth: 3 });
    expect(s.regimes.map((r) => r.regime)).toEqual(['export_pace_surge']);
    expect(s.regimes[0]!.basis).toEqual([
      { driver: 'fgis_inspections', date: '2026-07-18', source: 'usda_fgis' },
    ]);
    expect(s.numbers[0]).toMatchObject({ table: 'silver_psd', metric: 'su_ratio', value: 0.36, unit: 'ratio' });
    expect(s.chains[0]).toMatchObject({ chain_id: 'palm_sbo_sbm', hops: ['palm', 'sbo', 'sbm'] });
    expect(s.evidence[0]).toMatchObject({ node: 'export_pace', kept: 12 });
    expect(s.keptTotal).toBe(12);
  });

  it('keeps the RAW stages[] feed intact — partials append there too (the Pipeline still reads it)', () => {
    const t = turn();
    t.send({ stage: 'planning', intent: 'hybrid' }, PLAN, { stage: 'walking' }, WALK, REGIME);
    const s = t.state();
    expect(s.stages.map((x) => x.stage)).toEqual(['planning', 'plan', 'walking', 'walk', 'regime']);
    expect(s.stages.every((x) => typeof x.ts === 'number')).toBe(true);
  });

  it('`token` still grows the draft ONLY — never a stage row, never a finding', () => {
    const t = turn();
    t.send({ stage: 'token', text: '{"tldr":"corn ' }, { stage: 'token', text: 'is tight"}' });
    const s = t.state();
    expect(s.draft).toBe('{"tldr":"corn is tight"}');
    expect(s.stages).toHaveLength(0);
    expect(s.phase).toBe('idle');
  });

  it('an UNKNOWN kind from a newer server is ignored by the findings and never throws', () => {
    const t = turn();
    expect(() =>
      t.send({ stage: 'quantum_flux', nodes: 3 } as StageEvent, { stage: 'chain_v2' } as StageEvent, PLAN),
    ).not.toThrow();
    const s = t.state();
    expect(s.stages.map((x) => x.stage)).toEqual(['quantum_flux', 'chain_v2', 'plan']); // raw feed keeps them
    expect(s.regimes).toEqual([]);
    expect(s.chains).toEqual([]);
    expect(s.plan).toMatchObject({ intent: 'hybrid' }); // the known kind still lands
  });

  it('phase walks forward with the stream and citations activate only on verified', () => {
    const t = turn();
    expect(t.state().phase).toBe('idle');
    t.send(PLAN);
    expect(t.state().phase).toBe('planning');
    t.send(WALK, REGIME);
    expect(t.state().phase).toBe('walking');
    t.send({ stage: 'drafting' });
    expect(t.state().phase).toBe('drafting');
    expect(t.state().citationsLive).toBe(false); // the draft is PRE-verifier
    t.send({ stage: 'verified', strips: 7 });
    expect(t.state().phase).toBe('verified');
    expect(t.state().citationsLive).toBe(true);
    expect(t.state().strips).toBe(7);
  });

  it('the terminal result activates citations even when no `verified` stage was ever sent', () => {
    const t = turn();
    t.send(PLAN, { stage: 'drafting' });
    expect(t.state().citationsLive).toBe(false);
    t.finish({ answer: 'done' });
    expect(t.state().status).toBe('done');
    expect(t.state().citationsLive).toBe(true);
    expect(t.state().result?.answer).toBe('done');
  });

  it('DEGRADES: a server that emits no partials leaves every findings field at zero', () => {
    const t = turn();
    t.send(
      { stage: 'accepted' },
      { stage: 'planning', intent: 'hybrid', contracts: ['corn_cbot'] },
      { stage: 'walking', nodes: 7, regimes: 1 },
      { stage: 'retrieving', done: 3, total: 7 },
      { stage: 'numbers', calls: 2, running: true, table: 'silver_psd' },
      { stage: 'synthesizing' },
      { stage: 'verifying', checked: 3, stripped: 1 },
    );
    const s = t.state();
    expect(s.stages).toHaveLength(7); // the pre-F7 feed, unchanged
    expect(s.phase).toBe('idle');
    expect(s.plan).toBeNull();
    expect(s.walk).toBeNull();
    expect(s.regimes).toEqual([]);
    expect(s.numbers).toEqual([]);
    expect(s.chains).toEqual([]);
    expect(s.evidence).toEqual([]);
    expect(s.strips).toBeNull();
    t.finish();
    expect(t.state().phase).toBe('idle'); // nothing streamed → nothing to show
  });

  it('a new turn resets the findings (no bleed from the previous question)', () => {
    const t = turn();
    t.send(PLAN, REGIME, { stage: 'verified', strips: 3 });
    expect(t.state().regimes).toHaveLength(1);
    act(() => t.state().start('and soybeans?'));
    const s = t.state();
    expect(s.status).toBe('streaming');
    expect(s.regimes).toEqual([]);
    expect(s.plan).toBeNull();
    expect(s.phase).toBe('idle');
    expect(s.citationsLive).toBe(false);
    expect(s.strips).toBeNull();
    expect(s.stages).toEqual([]);
    expect(s.draft).toBe('');
  });
});
