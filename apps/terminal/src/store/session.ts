import { create } from 'zustand';
import { authEnabled } from '@/auth/oidc';

/**
 * Auth-session readiness (5.6 W3). Data queries (`threads`, `thread-turns`, the convergence prefetch)
 * gate on `ready` so they never fire before a token exists — pre-5.6 they raced the OIDC restore, got a
 * silent 401, and React Query never refetched (the empty-sidebar bug). `useAuthBridge` (App.tsx) syncs
 * react-oidc-context state into this store; mock/local builds (no Cognito env) are ready immediately.
 */
export interface SessionState {
  ready: boolean;
  setReady: (r: boolean) => void;
}

export const useSession = create<SessionState>((set) => ({
  ready: !authEnabled,
  setReady: (r) => set({ ready: r }),
}));
