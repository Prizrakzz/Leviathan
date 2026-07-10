import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useSettings } from '@/store/settings';
import { useUI } from '@/store/ui';
import { OVERLAY_SCRIM, PALETTE } from '@/tokens/tokens';

const { getProfile, putProfile } = vi.hoisted(() => ({ getProfile: vi.fn(), putProfile: vi.fn() }));
vi.mock('@/api/client', () => ({ getProfile, putProfile }));

import SettingsModal from './SettingsModal';

const BASE = {
  sub: 'u',
  email: 'you@x.com',
  name: 'You',
  facts: { markets: ['sugar'] },
  onboarded: true,
  turn_count: 5,
  first_seen: '2026-06-01T00:00:00Z',
};

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('SettingsModal (6.6)', () => {
  beforeEach(() => {
    getProfile.mockReset().mockResolvedValue({ ...BASE });
    putProfile.mockReset().mockImplementation((u: { facts?: unknown; onboarded?: boolean }) =>
      Promise.resolve({ ...BASE, ...(u.facts ? { facts: u.facts } : {}) }),
    );
    useSettings.setState({ open: true, tab: 'profile', forceOnboarding: false });
    useUI.setState({ accent: 'cyan' });
  });

  it('loads the profile, edits a market fact, and PUTs the merged set', async () => {
    wrap(<SettingsModal />);
    await screen.findByText(/you@x.com/);
    // P9-E2: the Radix Dialog.Overlay (portaled to body) dims through the shared scrim constant.
    const overlay = document.querySelector('.backdrop-blur-sm');
    expect(overlay?.className).toContain(OVERLAY_SCRIM);
    fireEvent.click(screen.getByRole('button', { name: 'coffee' })); // add to the existing ['sugar']
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(putProfile).toHaveBeenCalled());
    const arg = putProfile.mock.lastCall?.[0] as { facts: { markets: string[] } };
    expect(arg.facts.markets).toEqual(expect.arrayContaining(['sugar', 'coffee']));
  });

  it('the appearance tab swaps the interactive accent instantly (client-only)', async () => {
    wrap(<SettingsModal />);
    await screen.findByText(/you@x.com/);
    fireEvent.click(screen.getByRole('button', { name: /Appearance/ }));
    fireEvent.click(screen.getByRole('button', { name: /amber/ }));
    expect(useUI.getState().accent).toBe('amber');
    expect(document.documentElement.style.getPropertyValue('--cyan')).toBe(PALETTE.amber);
    expect(putProfile).not.toHaveBeenCalled(); // appearance never hits the server
  });

  it('"Redo onboarding" closes settings and arms the onboarding flow', async () => {
    wrap(<SettingsModal />);
    await screen.findByText(/you@x.com/);
    fireEvent.click(screen.getByRole('button', { name: /Redo onboarding/ }));
    expect(useSettings.getState().open).toBe(false);
    expect(useSettings.getState().forceOnboarding).toBe(true);
  });
});
