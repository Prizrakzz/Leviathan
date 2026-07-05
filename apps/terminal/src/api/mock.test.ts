import { describe, expect, it } from 'vitest';
import { mockListThreads, mockRespondStream, mockThreadTurns } from './mock';
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
