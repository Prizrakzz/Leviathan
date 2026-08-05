import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { RespondResult, StageEvent } from './schema';
import { parseSSE } from './sse';

// D-W6.2 — the SSE half of the 401-retry. Mock only oidc-client-ts (UserManager) + global fetch, then drive
// the REAL openRespondStream through fetchWithAuth. The static `parseSSE` import above stays on the first
// (auth-disabled) module instance; the retry tests dynamic-import a fresh, auth-ENABLED './sse'.
const getUser = vi.fn();
const signinSilent = vi.fn();
const signinRedirect = vi.fn();
vi.mock('oidc-client-ts', () => ({
  UserManager: class {
    getUser = getUser;
    signinSilent = signinSilent;
    signinRedirect = signinRedirect;
  },
  WebStorageStateStore: class {
    constructor(_: unknown) {}
  },
}));

const fetchMock = vi.fn();

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
}

/** The ALB-drop shape: the chunks arrive, then bytes simply STOP and the connection stays open forever.
 *  Never closed, never errored — exactly what the watchdog exists to notice. */
function hangingStream(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
    },
  });
}

/** A healthy but SLOW stream: one chunk every `gapMs`, then close. Total elapsed deliberately exceeds the
 *  idle window, so this can only pass if the watchdog is re-armed per chunk (the real turn runs 30-90s). */
function pacedStream(chunks: string[], gapMs: number): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    async pull(c) {
      await new Promise((r) => setTimeout(r, gapMs));
      if (i >= chunks.length) return void c.close();
      c.enqueue(enc.encode(chunks[i]!));
      i += 1;
    },
  });
}

/** Raw byte chunks, so a multi-byte character can be split ACROSS a chunk boundary (TextDecoder holds
 *  the partial sequence when `stream: true`). */
function byteStream(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(ch);
      c.close();
    },
  });
}

async function freshSse() {
  vi.resetModules();
  vi.stubEnv('VITE_COGNITO_AUTHORITY', 'https://cognito.example/pool');
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'client-id');
  return import('./sse');
}

function bearerOf(call: unknown[] | undefined): string | undefined {
  const init = call?.[1] as RequestInit | undefined;
  return (init?.headers as Record<string, string> | undefined)?.Authorization;
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

// D-TW-4 — the silent hang. Every case here used to RESOLVE the promise with no terminal event, leaving
// useTurn at status 'streaming' forever: pipeline frozen at "—", composer disabled, only a reload out
// (and the reload lost the question).
describe('parseSSE watchdog (D-TW-4)', () => {
  it('a stream that ENDS mid-turn onErrors instead of resolving silently', async () => {
    let err: string | undefined;
    const stages: StageEvent[] = [];
    await parseSSE(streamOf(['event: stage\ndata: {"stage":"walking"}\n\n']), {
      onStage: (e) => stages.push(e),
      onError: (e) => (err = e.error),
    });
    expect(stages).toHaveLength(1); // the work that DID arrive is untouched
    expect(err).toBe('stream ended without a result — retry');
  });

  it('a stream that STALLS is aborted after the idle window and onErrors', async () => {
    let err: string | undefined;
    const stages: StageEvent[] = [];
    // Resolving at all is half the assertion: the reader must be cancelled, or this hangs the test.
    await parseSSE(
      hangingStream(['event: stage\ndata: {"stage":"walking"}\n\n']),
      { onStage: (e) => stages.push(e), onError: (e) => (err = e.error) },
      20,
    );
    expect(stages).toHaveLength(1);
    expect(err).toContain('stalled');
  });

  it('the idle window is RE-ARMED per chunk — a slow but alive stream is never killed', async () => {
    let err: string | undefined;
    let result: RespondResult | undefined;
    const chunks = [
      ': keepalive\n\n',
      'event: stage\ndata: {"stage":"walking"}\n\n',
      ': keepalive\n\n',
      ': keepalive\n\n',
      'event: result\ndata: {"answer":"slow but fine"}\n\n',
    ];
    // 5 chunks x 10ms = 50ms of stream against a 30ms window: only per-chunk re-arming survives it.
    await parseSSE(pacedStream(chunks, 10), { onResult: (r) => (result = r), onError: (e) => (err = e.error) }, 30);
    expect(result?.answer).toBe('slow but fine');
    expect(err).toBeUndefined(); // the terminal event landed -> no watchdog fire
  });

  it('a multi-byte character split across chunks survives into the final, blank-line-less block', async () => {
    const enc = new TextEncoder();
    const head = enc.encode('event: stage\ndata: {"stage":"walking","intent":"caf');
    const tail = enc.encode('é"}'); // 0xC3 0xA9 ... -> split the pair across the two chunks
    const stages: StageEvent[] = [];
    await parseSSE(
      byteStream([
        new Uint8Array([...head, tail[0]!]),
        new Uint8Array(tail.slice(1)),
      ]),
      { onStage: (e) => stages.push(e) },
    );
    expect(stages[0]?.intent).toBe('café');
  });
});

describe('openRespondStream 401-retry-after-forced-refresh (D-W6.2)', () => {
  beforeEach(() => {
    getUser.mockReset();
    signinSilent.mockReset();
    signinRedirect.mockReset();
    fetchMock.mockReset();
    vi.unstubAllEnvs();
    vi.stubGlobal('fetch', fetchMock);
    getUser.mockResolvedValue({ expired: false, id_token: 'tok1', refresh_token: 'rt' });
    signinSilent.mockResolvedValue({ expired: false, id_token: 'tok2' });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('401-then-200: one forced refresh, replays with the new bearer, then streams the result', async () => {
    const ok = {
      ok: true,
      status: 200,
      body: streamOf(['event: result\ndata: {"answer":"ok","trace":{"graph_version":"gv"}}\n\n']),
    } as unknown as Response;
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 401, body: null } as unknown as Response)
      .mockResolvedValueOnce(ok);
    const { openRespondStream } = await freshSse();
    let result: RespondResult | undefined;
    let error: string | undefined;
    await openRespondStream(
      '',
      { question: 'why tight?' },
      { onResult: (r) => (result = r), onError: (e) => (error = e.error) },
    );
    expect(result?.answer).toBe('ok');
    expect(error).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(signinSilent).toHaveBeenCalledTimes(1);
    expect(signinRedirect).not.toHaveBeenCalled();
    expect(bearerOf(fetchMock.mock.calls[0])).toBe('Bearer tok1');
    expect(bearerOf(fetchMock.mock.calls[1])).toBe('Bearer tok2');
  });

  it('401 + the forced refresh fails: onError fires (as today) AND bounces to signinRedirect', async () => {
    signinSilent.mockRejectedValue(new Error('refresh revoked')); // forced getIdToken -> null
    fetchMock.mockResolvedValue({ ok: false, status: 401, body: null } as unknown as Response);
    const { openRespondStream } = await freshSse();
    let error: string | undefined;
    await openRespondStream('', { question: 'why tight?' }, { onError: (e) => (error = e.error) });
    expect(error).toBe('HTTP 401');
    expect(fetchMock).toHaveBeenCalledTimes(1); // no replay -- the refresh failed first
    expect(signinRedirect).toHaveBeenCalledTimes(1);
  });

  it('D-TW-6: a non-OK stream surfaces the SERVER sentence, not `HTTP 429`', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 429,
      body: null,
      json: async () => ({ detail: 'daily limit of 50 turns reached — try again tomorrow' }),
    } as unknown as Response);
    const { openRespondStream } = await freshSse();
    let error: string | undefined;
    await openRespondStream('', { question: 'why tight?' }, { onError: (e) => (error = e.error) });
    expect(error).toBe('daily limit of 50 turns reached — try again tomorrow');
    expect(fetchMock).toHaveBeenCalledTimes(1); // a 429 is not the 401 retry path
  });
});
