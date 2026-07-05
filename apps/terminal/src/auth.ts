/**
 * Auth barrel. Real Cognito + Google sign-in lives in `auth/oidc.ts` (Phase 4 Stage 4). When the
 * VITE_COGNITO_* env is absent (local mock/dev), `authEnabled` is false and the `/app` route is open so the
 * shell runs without a backend. The API layer calls `getIdToken()` to attach the bearer token.
 */
export { authEnabled, getIdToken, userManager } from './auth/oidc';
