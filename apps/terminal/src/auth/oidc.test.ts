import { beforeEach, describe, expect, it, vi } from 'vitest';

const getUser = vi.fn();
const signinSilent = vi.fn();
vi.mock('oidc-client-ts', () => ({
  UserManager: class {
    getUser = getUser;
    signinSilent = signinSilent;
  },
  WebStorageStateStore: class {
    constructor(_: unknown) {}
  },
}));

async function freshOidc() {
  vi.resetModules();
  vi.stubEnv('VITE_COGNITO_AUTHORITY', 'https://cognito.example/pool');
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'client-id');
  return import('./oidc');
}

describe('getIdToken silent renewal (5.6 W3)', () => {
  beforeEach(() => {
    getUser.mockReset();
    signinSilent.mockReset();
    vi.unstubAllEnvs();
  });

  it('returns the stored token when not expired (no renew)', async () => {
    getUser.mockResolvedValue({ expired: false, id_token: 'live-token' });
    const { getIdToken } = await freshOidc();
    expect(await getIdToken()).toBe('live-token');
    expect(signinSilent).not.toHaveBeenCalled();
  });

  it('renews an expired session ONCE under concurrent callers (single-flight)', async () => {
    getUser.mockResolvedValue({ expired: true, refresh_token: 'rt', id_token: 'stale' });
    let release!: (u: unknown) => void;
    signinSilent.mockImplementation(() => new Promise((r) => (release = r)));
    const { getIdToken } = await freshOidc();
    const p1 = getIdToken();
    const p2 = getIdToken();
    await new Promise((r) => setTimeout(r, 0)); // both reach the renew branch
    release({ expired: false, id_token: 'fresh' });
    expect(await p1).toBe('fresh');
    expect(await p2).toBe('fresh');
    expect(signinSilent).toHaveBeenCalledTimes(1);
  });

  it('returns null when expired with no refresh token', async () => {
    getUser.mockResolvedValue({ expired: true, id_token: 'stale' });
    const { getIdToken } = await freshOidc();
    expect(await getIdToken()).toBeNull();
    expect(signinSilent).not.toHaveBeenCalled();
  });

  it('returns null (not a throw) when the renewal fails', async () => {
    getUser.mockResolvedValue({ expired: true, refresh_token: 'rt' });
    signinSilent.mockRejectedValue(new Error('refresh revoked'));
    const { getIdToken } = await freshOidc();
    expect(await getIdToken()).toBeNull();
  });
});
