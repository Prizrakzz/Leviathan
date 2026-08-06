import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { openRespondStream } from './sse';

/**
 * D-AM-14 transport threading. The assertion that matters is the NEGATIVE one: a standard turn must send
 * the exact query string this route sent before the wave, because the backend's whole mode design rests on
 * `standard` being a passthrough pin. So these tests read the URL, not a handler.
 */
vi.mock('oidc-client-ts', () => ({
  UserManager: class {},
  WebStorageStateStore: class {
    constructor(_: unknown) {}
  },
}));

const fetchMock = vi.fn();

const okStream = () =>
  ({
    ok: true,
    status: 200,
    body: new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(new TextEncoder().encode('event: result\ndata: {"answer":"ok"}\n\n'));
        c.close();
      },
    }),
  }) as unknown as Response;

/** The URL the transport actually opened. */
const sentUrl = () => new URL(String(fetchMock.mock.calls[0]?.[0]), 'http://t.local');

describe('openRespondStream — the mode query param', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    // A FRESH body per call: one Response reused across two calls hands parseSSE an already-locked stream.
    fetchMock.mockImplementation(() => Promise.resolve(okStream()));
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('standard sends NO mode param — byte-identical to the pre-wave request', async () => {
    await openRespondStream('', { question: 'why tight?', asof: '2026-08-01', mode: 'standard' }, {});
    const u = sentUrl();
    expect(u.searchParams.has('mode')).toBe(false);
    expect(u.search).toBe('?question=why+tight%3F&asof=2026-08-01');
  });

  it('an ABSENT mode sends no param either (and matches the standard request exactly)', async () => {
    await openRespondStream('', { question: 'why tight?', asof: '2026-08-01' }, {});
    const withoutMode = sentUrl().search;
    fetchMock.mockClear();
    await openRespondStream('', { question: 'why tight?', asof: '2026-08-01', mode: 'standard' }, {});
    expect(sentUrl().search).toBe(withoutMode);
  });

  it('quick and deep ride as `mode`', async () => {
    await openRespondStream('', { question: 'why tight?', mode: 'deep' }, {});
    expect(sentUrl().searchParams.get('mode')).toBe('deep');
    fetchMock.mockClear();
    await openRespondStream('', { question: 'why tight?', mode: 'quick' }, {});
    expect(sentUrl().searchParams.get('mode')).toBe('quick');
  });

  it('an unrecognised name is DROPPED, not forwarded', async () => {
    await openRespondStream('', { question: 'why tight?', mode: 'ultra' }, {});
    expect(sentUrl().searchParams.has('mode')).toBe(false);
  });

  it('mode is additive: it does not disturb session_id / context / asof', async () => {
    await openRespondStream(
      '',
      {
        question: 'why tight?',
        asof: '2026-08-01',
        sessionId: 't-abc',
        context: [{ type: 'node', contract: 'corn_cbot', driver_id: 'export_pace' }],
        mode: 'deep',
      },
      {},
    );
    const p = sentUrl().searchParams;
    expect(p.get('question')).toBe('why tight?');
    expect(p.get('asof')).toBe('2026-08-01');
    expect(p.get('session_id')).toBe('t-abc');
    expect(JSON.parse(p.get('context') ?? '[]')).toEqual([
      { type: 'node', contract: 'corn_cbot', driver_id: 'export_pace' },
    ]);
    expect(p.get('mode')).toBe('deep');
  });
});
