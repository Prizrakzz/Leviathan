import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// D-W6.2 — the api-layer half of the 401-retry: drive the REAL client helpers (getJSON/postJSON/DELETE)
// through the REAL fetchWithAuth + getIdToken by mocking only oidc-client-ts (the UserManager surface) and
// the global fetch. VITE_MOCK stays unset so the helpers hit the real fetch path, not the in-repo mock.
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

async function freshClient() {
  vi.resetModules();
  vi.stubEnv('VITE_COGNITO_AUTHORITY', 'https://cognito.example/pool');
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'client-id');
  return import('./client');
}

function res(status: number, body: unknown = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function bearerOf(call: unknown[] | undefined): string | undefined {
  const init = call?.[1] as RequestInit | undefined;
  return (init?.headers as Record<string, string> | undefined)?.Authorization;
}

describe('client 401-retry-after-forced-refresh (D-W6.2)', () => {
  beforeEach(() => {
    getUser.mockReset();
    signinSilent.mockReset();
    signinRedirect.mockReset();
    fetchMock.mockReset();
    vi.unstubAllEnvs();
    vi.stubGlobal('fetch', fetchMock);
    // The common case for a 401 replay: the client BELIEVES its token valid (not expired) but the server
    // rejects it -> only the forced refresh mints a new one, so signinSilent-count == forced-refresh-count.
    getUser.mockResolvedValue({ expired: false, id_token: 'tok1', refresh_token: 'rt' });
    signinSilent.mockResolvedValue({ expired: false, id_token: 'tok2' });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('401-then-200: exactly one forced refresh, one replay with the new bearer, success', async () => {
    fetchMock.mockResolvedValueOnce(res(401)).mockResolvedValueOnce(res(200, { items: [] }));
    const { listThreads } = await freshClient();
    expect(await listThreads()).toEqual({ items: [] });
    expect(fetchMock).toHaveBeenCalledTimes(2); // original + one replay
    expect(signinSilent).toHaveBeenCalledTimes(1); // exactly one forced refresh
    expect(signinRedirect).not.toHaveBeenCalled();
    expect(bearerOf(fetchMock.mock.calls[0])).toBe('Bearer tok1'); // original: pre-request token
    expect(bearerOf(fetchMock.mock.calls[1])).toBe('Bearer tok2'); // replay: the forced-refresh token
  });

  it('401-then-401 (refresh succeeded): throws exactly as today, NO redirect', async () => {
    fetchMock.mockResolvedValue(res(401)); // both the original and the replay 401
    const { listThreads } = await freshClient();
    await expect(listThreads()).rejects.toThrow('HTTP 401');
    expect(fetchMock).toHaveBeenCalledTimes(2); // one replay was attempted
    expect(signinSilent).toHaveBeenCalledTimes(1);
    expect(signinRedirect).not.toHaveBeenCalled(); // token refreshed fine; the resource simply 401s
  });

  it('401 + the forced refresh itself fails: throws AND bounces to signinRedirect', async () => {
    signinSilent.mockRejectedValue(new Error('refresh revoked')); // forced getIdToken -> null
    fetchMock.mockResolvedValue(res(401));
    const { listThreads } = await freshClient();
    await expect(listThreads()).rejects.toThrow('HTTP 401');
    expect(fetchMock).toHaveBeenCalledTimes(1); // no replay -- refresh failed before we could replay
    expect(signinRedirect).toHaveBeenCalledTimes(1); // re-login instead of a silent header-less error
  });

  it('POST helper shares the retry: replay preserves method + body + content-type + new bearer', async () => {
    fetchMock.mockResolvedValueOnce(res(401)).mockResolvedValueOnce(res(200, { ok: true }));
    const { markNotificationSeen } = await freshClient();
    expect(await markNotificationSeen('n1')).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const replay = fetchMock.mock.calls[1]![1] as RequestInit;
    expect(replay.method).toBe('POST');
    expect(replay.body).toBe(JSON.stringify({}));
    const h = replay.headers as Record<string, string>;
    expect(h['content-type']).toBe('application/json');
    expect(h.Authorization).toBe('Bearer tok2');
  });

  it('DELETE helper shares the retry: replay preserves the DELETE method + new bearer', async () => {
    fetchMock.mockResolvedValueOnce(res(401)).mockResolvedValueOnce(res(200));
    const { deleteThread } = await freshClient();
    await expect(deleteThread('t1')).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const replay = fetchMock.mock.calls[1]![1] as RequestInit;
    expect(replay.method).toBe('DELETE');
    expect(bearerOf(fetchMock.mock.calls[1])).toBe('Bearer tok2');
  });

  it('a non-401 error is NOT retried (no spurious refresh)', async () => {
    fetchMock.mockResolvedValue(res(500));
    const { listThreads } = await freshClient();
    await expect(listThreads()).rejects.toThrow('HTTP 500');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(signinSilent).not.toHaveBeenCalled();
    expect(signinRedirect).not.toHaveBeenCalled();
  });
});
