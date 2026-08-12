import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TurnError } from './sse';
import { openRespondStream } from './sse';

/**
 * D-MW-25 — the credits wall on the TURN route.
 *
 * By construction it can only arrive one way: the gate refuses inside the quota dependency, which resolves
 * BEFORE the handler body, so the response is a non-OK 429 and the SSE stream never opens. (A refusal after
 * the StreamingResponse starts is impossible — that is the whole reason the server raises `CreditsExceeded`
 * from the dependency instead of returning a JSONResponse from one, which does not short-circuit.)
 *
 * So this route's failure branch is where the FE learns about credits, and it must produce BOTH halves from
 * ONE body read: the sentence that goes on screen (unchanged behaviour, D-TW-6) and the structured refusal
 * the depth control needs for the reset day.
 */
vi.mock('oidc-client-ts', () => ({
  UserManager: class {},
  WebStorageStateStore: class {
    constructor(_: unknown) {}
  },
}));

const fetchMock = vi.fn();

/** A non-OK response whose body can be read exactly once (the real Response contract). */
function refusal(status: number, body: unknown): Response {
  let read = false;
  return {
    ok: false,
    status,
    body: null,
    json: async () => {
      if (read) throw new TypeError('body stream already read');
      read = true;
      return body;
    },
  } as unknown as Response;
}

describe('openRespondStream — the credits 429', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('reports the sentence AND the structured refusal', async () => {
    fetchMock.mockResolvedValue(
      refusal(429, {
        // The server's slug (server.py `_CREDITS_ERROR_CODE`). It is a CODE, not the sentence -- the
        // sentence is `detail`, and that is what goes on screen.
        error: 'credits_exceeded',
        limit: 100,
        remaining: 0,
        reset_at: '2026-09-01T00:00:00Z',
        detail: 'no credits left this month',
      }),
    );
    let err: TurnError | undefined;
    await openRespondStream('', { question: 'why tight?', mode: 'deep' }, { onError: (e) => (err = e) });

    expect(err?.error).toBe('no credits left this month'); // this string goes ON SCREEN, verbatim
    expect(err?.status).toBe(429);
    expect(err?.credits).toMatchObject({
      code: 'credits_exceeded',
      limit: 100,
      remaining: 0,
      resetAt: '2026-09-01T00:00:00Z',
    });
  });

  it('the DAILY cap 429 is untouched: the sentence, and no credits field', async () => {
    fetchMock.mockResolvedValue(refusal(429, { detail: 'daily limit of 50 turns reached — try again tomorrow' }));
    let err: TurnError | undefined;
    await openRespondStream('', { question: 'why tight?', mode: 'quick' }, { onError: (e) => (err = e) });
    expect(err?.error).toBe('daily limit of 50 turns reached — try again tomorrow');
    expect(err?.credits).toBeUndefined();
    expect(err?.status).toBe(429); // ...but the STATUS still reaches Shell, which is what restores the box
  });

  it('an ordinary failure still falls back to the status line', async () => {
    fetchMock.mockResolvedValue(refusal(503, {}));
    let err: TurnError | undefined;
    await openRespondStream('', { question: 'why tight?' }, { onError: (e) => (err = e) });
    expect(err?.error).toBe('HTTP 503');
    expect(err?.credits).toBeUndefined();
    expect(err?.status).toBe(503);
  });
});

describe('openRespondStream — the turn id on the wire (P5 review F4)', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const urlOf = (): string => String(fetchMock.mock.calls[0]?.[0] ?? '');

  it('sends `turn_id` when the caller minted one -- the server keys idempotency on it', async () => {
    fetchMock.mockResolvedValue(refusal(503, {}));
    await openRespondStream('', { question: 'why tight?', mode: 'deep', turnId: 'abc-123' }, {});
    expect(new URL(urlOf(), 'http://x').searchParams.get('turn_id')).toBe('abc-123');
  });

  it('omits it entirely when there is none -- a mode-less/id-less request is byte-identical to before', async () => {
    fetchMock.mockResolvedValue(refusal(503, {}));
    await openRespondStream('', { question: 'why tight?' }, {});
    expect(urlOf()).not.toContain('turn_id');
  });
});
