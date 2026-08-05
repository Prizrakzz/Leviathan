import { describe, expect, it } from 'vitest';
import { httpError, httpErrorMessage } from './errors';

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
