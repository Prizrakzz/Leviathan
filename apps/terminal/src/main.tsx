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
import { injectTokens } from './tokens/tokens';

injectTokens(); // set the design-token CSS var values on :root before first paint

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } });

// After the OAuth redirect, strip ?code/?state but stay on /auth/callback so the router stays consistent;
// the callback route then <Navigate>s to /app once the session is established.
function onSigninCallback() {
  window.history.replaceState({}, document.title, '/auth/callback');
}

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
    <QueryClientProvider client={qc}>
      <AuthShell>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AuthShell>
    </QueryClientProvider>
  </React.StrictMode>,
);
