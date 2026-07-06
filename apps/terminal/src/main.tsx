import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import '@fontsource/ibm-plex-mono/600.css';
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/600.css';
import './styles/global.css';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { type ReactNode } from 'react';
import ReactDOM from 'react-dom/client';
import { AuthProvider } from 'react-oidc-context';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { authEnabled, userManager } from './auth/oidc';
import { ErrorBoundary } from './shell/ErrorBoundary';
import { useUI } from './store/ui';
import { applyAccent, injectTokens } from './tokens/tokens';

injectTokens(); // set the design-token CSS var values on :root before first paint
applyAccent(useUI.getState().accent); // then the user's persisted accent (6.6), also pre-paint (no flash)

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } });

// After the OAuth redirect, strip ?code/?state but stay on /auth/callback so the router stays consistent;
// the callback route then <Navigate>s to /app once the session is established.
function onSigninCallback() {
  window.history.replaceState({}, document.title, '/auth/callback');
}

// The absolute backstop (S2.1): if anything below the providers throws — a shell/route error, a failed
// lazy chunk — show a readable panel with a reload instead of a blank dark page. Errors below this are
// contained by the finer-grained boundaries in AnswerView; this only fires for a truly fatal render.
const rootFallback = (
  <div className="flex min-h-screen items-center justify-center bg-bg-0 p-6">
    <div className="max-w-sm rounded-panel border border-line bg-bg-1 p-4 text-center">
      <div className="font-mono text-12 uppercase tracking-wider text-neg">something went wrong</div>
      <p className="mt-2 font-sans text-13 text-text-dim">
        The terminal hit an unexpected error. Reloading usually fixes it.
      </p>
      <button
        onClick={() => window.location.reload()}
        className="mt-3 rounded-chip border border-cyan px-3 py-1 font-mono text-11 text-cyan hover:bg-bg-2"
      >
        reload
      </button>
    </div>
  </div>
);

// Only mount the OIDC provider when Cognito is configured (prod). Local/mock builds skip it entirely.
function AuthShell({ children }: { children: ReactNode }) {
  if (authEnabled && userManager) {
    return (
      <AuthProvider userManager={userManager} onSigninCallback={onSigninCallback}>
        {children}
      </AuthProvider>
    );
  }
  return <>{children}</>;
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary fallback={rootFallback}>
      <QueryClientProvider client={qc}>
        <AuthShell>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AuthShell>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
