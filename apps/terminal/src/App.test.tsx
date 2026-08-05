import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

// The /auth/callback branch (D-TW-7) only exists in the AUTHED app, so both auth surfaces are mocked:
// `authEnabled` picks AuthedApp, and `useAuth` hands back the exact provider state under test.
const hoisted = vi.hoisted(() => ({
  auth: {} as { isLoading: boolean; isAuthenticated: boolean; error?: Error; signinSilent: () => Promise<null> },
}));
vi.mock('react-oidc-context', () => ({ useAuth: () => hoisted.auth }));
vi.mock('./auth/oidc', () => ({ authEnabled: true, userManager: null }));

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/auth/callback']}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('/auth/callback error branch (D-TW-7)', () => {
  beforeEach(() => {
    hoisted.auth = { isLoading: false, isAuthenticated: false, signinSilent: () => Promise.resolve(null) };
  });

  it('a failed code exchange shows the reason and the way back — not "loading terminal…" forever', () => {
    hoisted.auth.error = new Error('invalid_grant: authorization code has expired');
    mount();
    expect(screen.getByTestId('auth-error')).toHaveTextContent('invalid_grant');
    expect(screen.getByRole('link', { name: 'back to sign in' })).toHaveAttribute('href', '/');
  });

  it('with no error it still HOLDS on the callback (the redirect is mid-flight, not failed)', () => {
    mount();
    expect(screen.queryByTestId('auth-error')).toBeNull();
    expect(screen.getByText(/loading terminal/)).toBeInTheDocument();
  });
});
