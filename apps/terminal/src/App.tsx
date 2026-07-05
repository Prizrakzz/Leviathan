import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from 'react-oidc-context';
import { authEnabled } from './auth/oidc';
import { Landing } from './landing/Landing';

// The landing gate and terminal are ONE app; the terminal is lazy-loaded behind the auth gate (§7).
const Terminal = lazy(() => import('./shell/Terminal'));

const loading = <div className="p-6 font-mono text-12 text-text-dim">loading terminal…</div>;

function TerminalGate({ authed }: { authed: boolean }) {
  if (!authed) return <Navigate to="/?signin=1" replace />;
  return <Suspense fallback={loading}>{<Terminal />}</Suspense>;
}

/** Prod: Cognito + Google sign-in gates /app; /auth/callback lands the OAuth redirect. */
function AuthedApp() {
  const auth = useAuth();
  // While a stored session loads or the redirect is being processed, hold — don't bounce to landing.
  if (auth.isLoading) return loading;
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route
        path="/auth/callback"
        element={auth.isAuthenticated ? <Navigate to="/app" replace /> : loading}
      />
      <Route path="/app" element={<TerminalGate authed={auth.isAuthenticated} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

/** Local/mock builds (no VITE_COGNITO_* env): the shell is open so it runs without a backend. */
function OpenApp() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/app" element={<TerminalGate authed={true} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return authEnabled ? <AuthedApp /> : <OpenApp />;
}
