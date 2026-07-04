import { describe, expect, it } from 'vitest';
import type { RespondResult, StageEvent } from './schema';
import { parseSSE } from './sse';

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
}

describe('parseSSE', () => {
  it('parses ordered stage events then the terminal result, ignoring keepalive comments', async () => {
    const chunks = [
      'event: stage\ndata: {"stage":"planning","intent":"hybrid"}\n\n',
      ': keepalive\n\n',
      'event: stage\ndata: {"stage":"verifying","checked":4,"stripped":0}\n\n',
      'event: result\ndata: {"answer":"hi","trace":{"graph_version":"gv"}}\n\n',
    ];
    const stages: StageEvent[] = [];
    let result: RespondResult | undefined;
    await parseSSE(streamOf(chunks), { onStage: (e) => stages.push(e), onResult: (r) => (result = r) });
    expect(stages.map((s) => s.stage)).toEqual(['planning', 'verifying']);
    expect(stages[1]?.checked).toBe(4);
    expect(result?.answer).toBe('hi');
    expect(result?.trace?.graph_version).toBe('gv');
  });

  it('reassembles an event split across byte chunks', async () => {
    const chunks = ['event: sta', 'ge\ndata: {"stage":"walk', 'ing","nodes":7}\n\n'];
    const stages: StageEvent[] = [];
    await parseSSE(streamOf(chunks), { onStage: (e) => stages.push(e) });
    expect(stages).toEqual([{ stage: 'walking', nodes: 7 }]);
  });

  it('stops at the terminal error event', async () => {
    const chunks = [
      'event: error\ndata: {"error":"RuntimeError: boom"}\n\n',
      'event: stage\ndata: {"stage":"walking"}\n\n',
    ];
    const stages: StageEvent[] = [];
    let err: string | undefined;
    await parseSSE(streamOf(chunks), { onStage: (e) => stages.push(e), onError: (e) => (err = e.error) });
    expect(err).toContain('RuntimeError');
    expect(stages).toHaveLength(0); // nothing after the terminal event
  });
});
