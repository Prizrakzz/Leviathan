import { describe, expect, it } from 'vitest';
import { mockGraph, mockListThreads, mockRespondStream, mockSuggest, mockThreadTurns } from './mock';
import type { RespondResult, StageEvent } from './schema';

describe('mockRespondStream', () => {
  it('emits the 5.6 tick sequence (progress + synthesizing + tokens), then the result', async () => {
    const stages: StageEvent[] = [];
    let result: RespondResult | undefined;
    await mockRespondStream(
      { question: 'KC frost 2021', asof: '2021-07-20' },
      { onStage: (e) => stages.push(e), onResult: (r) => (result = r) },
      { delay: 0 },
    );
    const names = stages.map((s) => s.stage);
    // ordered milestones
    const order = ['accepted', 'planning', 'walking', 'synthesizing', 'verifying'];
    const idx = order.map((n) => names.indexOf(n));
    expect(idx.every((v) => v >= 0)).toBe(true);
    expect([...idx]).toEqual([...idx].sort((a, b) => a - b));
    // retrieval progress ticks are monotonic to total
    const prog = stages.filter((s) => s.stage === 'retrieving' && s.done != null);
    expect(prog.length).toBeGreaterThan(1);
    expect(prog[prog.length - 1]!.done).toBe(prog[prog.length - 1]!.total);
    // numbers running ticks carry a table; a final completion event follows
    const numRunning = stages.filter((s) => s.stage === 'numbers' && s.running);
    expect(numRunning.length).toBeGreaterThan(0);
    expect(numRunning.every((s) => !!s.table)).toBe(true);
    // token deltas reassemble into parseable tool-JSON
    const draft = stages.filter((s) => s.stage === 'token').map((s) => s.text ?? '').join('');
    expect(() => JSON.parse(draft) as unknown).not.toThrow();
    expect(result?.trace?.graph_version).toBe('3a69acfb87c5');
    expect(result?.asof).toBe('2021-07-20');
  });
});

describe('mock is commodity-aware (S2.1 — no single-fixture stale-render)', () => {
  it('routes a sugar/BRL question to the raw_sugar answer, not the arabica fixture', async () => {
    let frost: RespondResult | undefined;
    let sugar: RespondResult | undefined;
    await mockRespondStream({ question: 'KC arabica frost setup', asof: '2021-07-20' }, { onResult: (r) => (frost = r) }, { delay: 0 });
    await mockRespondStream({ question: 'what does a weak BRL do to the sugar squeeze?', asof: '2024-05-11' }, { onResult: (r) => (sugar = r) }, { delay: 0 });
    expect(frost?.contract).toBe('arabica_coffee');
    expect(sugar?.contract).toBe('raw_sugar');
    expect(sugar?.structured?.tldr).not.toBe(frost?.structured?.tldr); // different answer, not a stale echo
    expect(sugar?.structured?.tldr?.toLowerCase()).toContain('ethanol');
  });

  it('returns a commodity-matched DAG: raw_sugar → the sugar topology, else arabica', () => {
    const sugarTopo = mockGraph('raw_sugar');
    const arabicaTopo = mockGraph('arabica_coffee');
    expect(sugarTopo.contract).toBe('raw_sugar');
    expect(arabicaTopo.contract).toBe('arabica_coffee');
    // the sugar answer's fired drivers are real nodes in the sugar topology (the firing overlay lights up)
    const ids = new Set(sugarTopo.nodes.map((n) => n.id));
    expect(ids.has('sugar_ethanol_parity')).toBe(true);
    expect(ids.has('India_ethanol_diversion')).toBe(true);
  });
});

describe('mockSuggest (6.2)', () => {
  it('returns follow-ups for a turn packet and starters for an empty packet', async () => {
    const follow = await mockSuggest({ question: 'why tight?', tldr: 't', contracts: [] });
    const start = await mockSuggest({ contracts: [] });
    expect(follow.suggestions.length).toBeGreaterThan(0);
    expect(start.suggestions.length).toBeGreaterThan(0);
    expect(follow.suggestions).not.toEqual(start.suggestions); // distinct sets exercise both surfaces
  });
});

describe('mock threads', () => {
  it('lists threads and returns durable turns for the seeded one', () => {
    const { items } = mockListThreads();
    expect(items.length).toBeGreaterThan(0);
    const turns = mockThreadTurns(items[0]!.id);
    expect(turns.turns.length).toBeGreaterThan(0);
    expect(turns.turns[0]!.answer).toBeTruthy(); // full-answer persistence shape
    expect(mockThreadTurns('t-unknown').turns).toEqual([]);
  });
});
