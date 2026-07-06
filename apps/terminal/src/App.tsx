import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from 'react-oidc-context';
import { useQueryClient } from '@tanstack/react-query';
import { authEnabled } from './auth/oidc';
import { Landing } from './landing/Landing';
import { useSession } from './store/session';
import { useThread } from './store/thread';

// The landing gate and terminal are ONE app; the terminal is lazy-loaded behind the auth gate (§7).
const Terminal = lazy(() => import('./shell/Terminal'));

const loading = <div className="p-6 font-mono text-12 text-text-dim">loading terminal…</div>;

function TerminalGate({ authed }: { authed: boolean }) {
  // Before bouncing an unauthenticated visit to the landing, try ONE silent sign-in: a stored refresh
  // token (30d) restores the session without the Google redirect — this is what kills the
  // "sign in again every visit" friction (5.6 W3).
  const auth = useAuth();
  const [silent, setSilent] = useState<'idle' | 'checking' | 'fail'>('idle');
  const tried = useRef(false);
  useEffect(() => {
    if (authed || tried.current) return;
    tried.current = true;
    setSilent('checking');
    auth
      .signinSilent()
      .then((u) => setSilent(u ? 'idle' : 'fail'))
      .catch(() => setSilent('fail'));
  }, [authed, auth]);
  if (authed) return <Suspense fallback={loading}>{<Terminal />}</Suspense>;
  if (silent === 'checking') return loading;
  return <Navigate to="/?signin=1" replace />;
}

/** Bridges react-oidc-context state into the `useSession` store (components/queries can't call useAuth()
 *  in mock mode — no provider). Also invalidates the per-user queries the moment auth lands, so a list
 *  that raced the token restore refetches instead of staying empty. */
function AuthBridge() {
  const auth = useAuth();
  const qc = useQueryClient();
  const ready = auth.isAuthenticated && !auth.isLoading;
  useEffect(() => {
    useSession.getState().setReady(ready);
    if (ready) {
      void qc.invalidateQueries({ queryKey: ['threads'] });
      void qc.invalidateQueries({ queryKey: ['thread-turns'] });
    }
  }, [ready, qc]);
  return null;
}

/** Prod: Cognito + Google sign-in gates /app; /auth/callback lands the OAuth redirect. */
function AuthedApp() {
  const auth = useAuth();
  // While a stored session loads or the redirect is being processed, hold — don't bounce to landing.
  if (auth.isLoading) return loading;
  return (
    <>
      <AuthBridge />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="/auth/callback"
          element={auth.isAuthenticated ? <CallbackLanding /> : loading}
        />
        <Route path="/app" element={<TerminalGate authed={auth.isAuthenticated} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}

/** Fresh interactive login → start a NEW empty thread (user decision: land on a clean composer). The
 *  thread store is no longer persisted (5.8), so every visit/reload already starts fresh; this newThread()
 *  is belt-and-suspenders for the login redirect. Past threads re-open from the sidebar. */
function CallbackLanding() {
  useEffect(() => {
    useThread.getState().newThread();
  }, []);
  return <Navigate to="/app" replace />;
}

/** Local/mock builds (no VITE_COGNITO_* env): the shell is open so it runs without a backend. Renders
 *  Terminal directly — TerminalGate calls useAuth(), which requires the (absent) AuthProvider. */
function OpenApp() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/app" element={<Suspense fallback={loading}>{<Terminal />}</Suspense>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return authEnabled ? <AuthedApp /> : <OpenApp />;
}
