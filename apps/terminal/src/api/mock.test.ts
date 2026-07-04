import { describe, expect, it } from 'vitest';
import { mockRespondStream } from './mock';
import type { RespondResult, StageEvent } from './schema';

describe('mockRespondStream', () => {
  it('emits accepted + five ordered pipeline ticks, then the result', async () => {
    const stages: StageEvent[] = [];
    let result: RespondResult | undefined;
    await mockRespondStream(
      { question: 'KC frost 2021', asof: '2021-07-20' },
      { onStage: (e) => stages.push(e), onResult: (r) => (result = r) },
      { delay: 0 },
    );
    expect(stages.map((s) => s.stage)).toEqual([
      'accepted',
      'planning',
      'walking',
      'retrieving',
      'numbers',
      'verifying',
    ]);
    expect(result?.trace?.graph_version).toBe('3a69acfb87c5');
    expect(result?.asof).toBe('2021-07-20');
    expect((result as Record<string, unknown>).question).toBe('KC frost 2021');
  });
});
