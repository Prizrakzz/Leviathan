import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useSettings } from '@/store/settings';

const { getProfile, putProfile } = vi.hoisted(() => ({ getProfile: vi.fn(), putProfile: vi.fn() }));
vi.mock('@/api/client', () => ({ getProfile, putProfile }));

import Onboarding from './Onboarding';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('Onboarding (6.6)', () => {
  beforeEach(() => {
    getProfile.mockReset();
    putProfile.mockReset().mockResolvedValue({ onboarded: true, facts: {} });
    useSettings.setState({ open: false, tab: 'profile', forceOnboarding: false });
  });

  it('does not show once the user is onboarded', async () => {
    getProfile.mockResolvedValue({ onboarded: true, facts: {} });
    wrap(<Onboarding />);
    // give the query a tick to resolve, then assert the modal never mounted
    await waitFor(() => expect(getProfile).toHaveBeenCalled());
    expect(screen.queryByTestId('onboarding')).toBeNull();
  });

  it('D-TW-13: a FAILED profile fetch fails open — the flow still shows', async () => {
    getProfile.mockRejectedValue(new Error('502')); // the real-Chrome case: profile died, onboarding never came
    wrap(<Onboarding />);
    expect(await screen.findByTestId('onboarding')).toBeInTheDocument();
  });

  it('shows for a fresh user and "Skip all" finishes with onboarded=true', async () => {
    getProfile.mockResolvedValue({ onboarded: false, facts: {} });
    wrap(<Onboarding />);
    await screen.findByTestId('onboarding');
    fireEvent.click(screen.getByRole('button', { name: /Skip all/ }));
    await waitFor(() => expect(putProfile).toHaveBeenCalled());
    expect(putProfile.mock.lastCall?.[0]).toMatchObject({ onboarded: true });
  });

  it('a failing PUT still dismisses the flow — never blocks the terminal (review fix)', async () => {
    getProfile.mockResolvedValue({ onboarded: false, facts: {} });
    putProfile.mockRejectedValue(new Error('500')); // backend down for writes / expired token
    wrap(<Onboarding />);
    await screen.findByTestId('onboarding');
    fireEvent.click(screen.getByRole('button', { name: /Skip all/ }));
    // The local `finished` flag closes the modal regardless of the write outcome (onSuccess never fires).
    await waitFor(() => expect(screen.queryByTestId('onboarding')).toBeNull());
  });

  it('captures answers across steps and finishes with the facts + onboarded', async () => {
    getProfile.mockResolvedValue({ onboarded: false, facts: {} });
    wrap(<Onboarding />);
    await screen.findByTestId('onboarding');
    fireEvent.click(screen.getByRole('button', { name: 'coffee' })); // step 1: a market
    fireEvent.click(screen.getByRole('button', { name: 'Continue' })); // -> step 2 (seat)
    fireEvent.click(screen.getByRole('button', { name: 'Continue' })); // -> step 3 (regions)
    fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
    await waitFor(() => expect(putProfile).toHaveBeenCalled());
    const arg = putProfile.mock.lastCall?.[0] as { facts: { markets: string[] }; onboarded: boolean };
    expect(arg.onboarded).toBe(true);
    expect(arg.facts.markets).toEqual(['coffee']);
  });
});
