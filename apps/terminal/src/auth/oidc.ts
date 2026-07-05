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
 *  "threads disappeared" empty sidebar. */
export async function getIdToken(): Promise<string | null> {
  if (!userManager) return null;
  try {
    const user = await userManager.getUser();
    if (user && !user.expired) return user.id_token ?? null;
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
