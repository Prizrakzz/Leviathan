import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CREDITS_KEY, CREDITS_ROUTE, getCredits } from './credits';

/**
 * D-MW-25 — reading the monthly grant.
 *
 * The one behaviour worth a test of its own is the DARK case: `GRAPHRAG_CREDITS` absent means the route
 * 404s and nothing is metered, and the FE must render that as "no meter here" rather than as a broken
 * feature. A 500 is NOT that: a server fault is not a product decision, so it still throws and the badge
 * simply does not appear.
 */
vi.mock('oidc-client-ts', () => ({
  UserManager: class {},
  WebStorageStateStore: class {
    constructor(_: unknown) {}
  },
}));

const fetchMock = vi.fn();

const jsonRes = (status: number, body: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as Response;

describe('getCredits', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('returns the server balance', async () => {
    fetchMock.mockResolvedValue(jsonRes(200, { remaining: 97, limit: 100, reset_at: '2026-09-01T00:00:00Z' }));
    await expect(getCredits()).resolves.toEqual({
      remaining: 97,
      limit: 100,
      reset_at: '2026-09-01T00:00:00Z',
    });
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(CREDITS_ROUTE);
  });

  it('404 means METERING IS DARK, not an error', async () => {
    fetchMock.mockResolvedValue(jsonRes(404, { detail: 'not found' }));
    await expect(getCredits()).resolves.toBeNull();
  });

  it('a server fault still throws, with the server sentence', async () => {
    fetchMock.mockResolvedValue(jsonRes(500, { detail: 'ledger unavailable' }));
    await expect(getCredits()).rejects.toThrow('ledger unavailable');
  });

  it('the query key is a single declared constant (badge and invalidations cannot drift apart)', () => {
    expect([...CREDITS_KEY]).toEqual(['credits']);
  });
});
