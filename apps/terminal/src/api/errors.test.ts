import { describe, expect, it } from 'vitest';
import { creditsRefusalFrom, httpError, httpErrorMessage, readHttpError } from './errors';

/** A Response stand-in. `body` is what res.json() does: return a value, or throw (non-JSON). */
function res(status: number, json?: () => unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (!json) throw new SyntaxError('Unexpected token < in JSON at position 0');
      return json();
    },
  } as unknown as Response;
}

describe('httpErrorMessage (D-TW-6)', () => {
  it('lifts the server sentence out of `detail` — the quota wall a user actually hits', async () => {
    const msg = await httpErrorMessage(
      res(429, () => ({ detail: 'daily limit of 50 turns reached — try again tomorrow' })),
      '/v1/respond/stream',
    );
    expect(msg).toBe('daily limit of 50 turns reached — try again tomorrow'); // and NOT "HTTP 429"
  });

  it('falls back to status + route when the body carries no detail', async () => {
    expect(await httpErrorMessage(res(401, () => ({})), '/v1/threads')).toBe('HTTP 401 on /v1/threads');
    expect(await httpErrorMessage(res(401, () => ({})))).toBe('HTTP 401'); // no route context = on-screen text
  });

  it('falls back when the body is not JSON at all — the SPA index.html answering an API call', async () => {
    expect(await httpErrorMessage(res(200), '/v1/profile')).toBe('HTTP 200 on /v1/profile');
  });

  it('ignores a non-string detail (FastAPI 422 arrays) rather than printing [object Object]', async () => {
    const msg = await httpErrorMessage(
      res(422, () => ({ detail: [{ loc: ['query', 'asof'], msg: 'invalid date' }] })),
      '/v1/series/silver_psd/su_ratio',
    );
    expect(msg).toBe('HTTP 422 on /v1/series/silver_psd/su_ratio');
  });

  it('trims, and treats a whitespace-only detail as absent', async () => {
    expect(await httpErrorMessage(res(500, () => ({ detail: '  boom  ' })), '/x')).toBe('boom');
    expect(await httpErrorMessage(res(500, () => ({ detail: '   ' })), '/x')).toBe('HTTP 500 on /x');
  });

  it('httpError wraps the same message in an Error (the client.ts throw shape)', async () => {
    const e = await httpError(res(403, () => ({ detail: 'not your thread' })), '/v1/threads/t1');
    expect(e).toBeInstanceOf(Error);
    expect(e.message).toBe('not your thread');
  });
});

/**
 * D-MW-25 — the credits 429. The pinned server body is TOP-LEVEL
 * `{error, limit, remaining, reset_at, detail}`, raised as `CreditsExceeded` from the quota dependency and
 * rendered by an app-level exception handler. The FE half is here.
 */
const WALL = {
  error: 'credits_exhausted',
  limit: 100,
  remaining: 0,
  reset_at: '2026-09-01T00:00:00Z',
  detail: 'no credits left this month',
};

describe('creditsRefusalFrom (D-MW-25)', () => {
  it('parses the pinned top-level body, structured fields AND sentence', () => {
    expect(creditsRefusalFrom(429, WALL)).toEqual({
      message: 'no credits left this month',
      code: 'credits_exhausted',
      limit: 100,
      remaining: 0,
      resetAt: '2026-09-01T00:00:00Z',
    });
  });

  it('the DAILY-turn 429 is not a credits wall — it carries no reset instant and no count', () => {
    // The discriminator, stated as a test: the daily cap is an ordinary HTTPException with a string detail,
    // and it must keep rendering exactly as it did before this change.
    expect(creditsRefusalFrom(429, { detail: 'daily limit of 50 turns reached — try again tomorrow' })).toBeNull();
  });

  it('is 429-only, and never guesses from a partial body', () => {
    expect(creditsRefusalFrom(500, WALL)).toBeNull();
    expect(creditsRefusalFrom(429, { reset_at: '2026-09-01T00:00:00Z' })).toBeNull(); // no count
    expect(creditsRefusalFrom(429, { limit: 100, remaining: 0 })).toBeNull(); // no reset instant
    expect(creditsRefusalFrom(429, null)).toBeNull();
    expect(creditsRefusalFrom(429, 'nope')).toBeNull();
  });

  it('tolerates the nested `detail` variant, and falls back to its own sentence', () => {
    const nested = creditsRefusalFrom(429, { detail: { limit: 100, remaining: 0, reset_at: '2026-09-01T00:00:00Z' } });
    expect(nested?.resetAt).toBe('2026-09-01T00:00:00Z');
    expect(nested?.message).toBe('no credits left this month'); // ours, because the server sent no sentence
  });
});

describe('readHttpError — ONE body read, both halves', () => {
  it('returns the sentence and the refusal together (the body can only be consumed once)', async () => {
    const { message, credits } = await readHttpError(res(429, () => WALL), '/v1/respond/stream');
    expect(message).toBe('no credits left this month');
    expect(credits?.resetAt).toBe('2026-09-01T00:00:00Z');
    expect(credits?.remaining).toBe(0);
  });

  it('a non-credits failure yields the same message it always did, with no refusal', async () => {
    const { message, credits } = await readHttpError(res(503, () => ({})), '/v1/respond/stream');
    expect(message).toBe('HTTP 503 on /v1/respond/stream');
    expect(credits).toBeNull();
  });
});
