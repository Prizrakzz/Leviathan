import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts';

/**
 * Cognito + Google OIDC (Phase 4 Stage 4). Authorization-code + PKCE against the Cognito user pool; the
 * hosted-domain authorize endpoint is discovered from the authority's OIDC metadata. `identity_provider=
 * Google` sends users straight to Google (skipping the Cognito chooser). We send the ID token to the API
 * (auth.py verifies aud = app client id). Auth is DISABLED when the env vars are absent (local mock/dev).
 */
const authority = import.meta.env.VITE_COGNITO_AUTHORITY as string | undefined;
const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined;
const redirectUri =
  (import.meta.env.VITE_COGNITO_REDIRECT_URI as string | undefined) ??
  (typeof window !== 'undefined' ? `${window.location.origin}/auth/callback` : '');

export const authEnabled = Boolean(authority && clientId);

export const userManager: UserManager | null = authEnabled
  ? new UserManager({
      authority: authority!,
      client_id: clientId!,
      redirect_uri: redirectUri,
      post_logout_redirect_uri: typeof window !== 'undefined' ? window.location.origin : undefined,
      response_type: 'code',
      scope: 'openid email profile',
      extraQueryParams: { identity_provider: 'Google' },
      userStore: new WebStorageStateStore({ store: window.localStorage }),
      automaticSilentRenew: true,
    })
  : null;

// Single-flight guard: N concurrent getIdToken() calls with an expired token share ONE silent renewal
// instead of racing N refresh-token grants against Cognito (which rotates the refresh token).
let renewing: Promise<User | null> | null = null;

/** The current ID token for API/SSE Authorization headers, or null (unauthenticated / auth disabled).
 *  An expired stored session with a refresh token is silently RENEWED here (Cognito refresh grant, 30d)
 *  instead of returning null — pre-5.6 the null turned into header-less requests → silent 401s → the
 *  "threads disappeared" empty sidebar.
 *
 *  `{force: true}` (D-W6.2) skips the not-expired short-circuit and renews unconditionally — for the
 *  401-retry path where the CLIENT believes the token valid but the SERVER rejected it (clock skew,
 *  revocation, key rotation). It still needs a refresh_token to mint a new one, and still shares the ONE
 *  single-flight renewal so a forced refresh and a concurrent expiry renewal never race two grants. */
export async function getIdToken(opts?: { force?: boolean }): Promise<string | null> {
  if (!userManager) return null;
  try {
    const user = await userManager.getUser();
    if (!opts?.force && user && !user.expired) return user.id_token ?? null;
    if (!user?.refresh_token) return null;
    renewing ??= userManager
      .signinSilent()
      .catch(() => null)
      .finally(() => {
        renewing = null;
      });
    const renewed = await renewing;
    return renewed && !renewed.expired ? (renewed.id_token ?? null) : null;
  } catch {
    return null;
  }
}

/** fetch with the bearer header + a single 401-retry-after-forced-refresh (D-W6.2 — the ONE shared
 *  implementation for the client.ts JSON helpers and the sse.ts stream). The first attempt uses the
 *  normal pre-request token (silently renewed if merely expired). If the SERVER 401s a token the client
 *  thought valid, we force ONE refresh and replay with the new bearer; a still-401 replay is returned
 *  as-is so the caller fails exactly as before (no redirect — the token was valid, the resource wasn't).
 *  When the forced refresh yields no token (the refresh grant itself failed — revoked/rotated), we bounce
 *  to the Cognito hosted login (signinRedirect, the Landing.tsx path) instead of a silent header-less
 *  error, and return the 401 so the caller still fails while the redirect navigates away. `userManager`
 *  is null in auth-disabled dev mode, so the redirect is guarded. */
export async function fetchWithAuth(url: string, init: RequestInit = {}): Promise<Response> {
  const withBearer = (token: string | null): RequestInit => {
    const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
    if (token) headers.Authorization = `Bearer ${token}`;
    return { ...init, headers };
  };
  const res = await fetch(url, withBearer(await getIdToken()));
  if (res.status !== 401) return res;
  const forced = await getIdToken({ force: true });
  if (!forced) {
    void userManager?.signinRedirect();
    return res;
  }
  return fetch(url, withBearer(forced));
}
