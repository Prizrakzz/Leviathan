import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { NotificationItem } from '@/api/schema';
import { useAsOf } from '@/store/asof';
import { useUI } from '@/store/ui';

// Mock the api layer + auth exactly like the sibling tests (Onboarding/SettingsModal): hoisted spies so the
// module mock and the assertions share one instance. `authed` is a mutable flag the auth-gate test flips.
const h = vi.hoisted(() => ({
  listNotifications: vi.fn(),
  markNotificationSeen: vi.fn(),
  authed: true,
}));
vi.mock('@/api/client', () => ({
  listNotifications: h.listNotifications,
  markNotificationSeen: h.markNotificationSeen,
}));
// authEnabled=true routes through the AuthedBell (useAuth) path so test #6 can exercise the null gate.
vi.mock('@/auth/oidc', () => ({ authEnabled: true }));
vi.mock('react-oidc-context', () => ({ useAuth: () => ({ isAuthenticated: h.authed }) }));

import { NotificationBell } from './NotificationBell';

/** A digest item carrying EXTRA server fields (headline/url) the typed projection must never leak. */
function item(over: Record<string, unknown> = {}): NotificationItem {
  return {
    notif_id: 'n1',
    created_at: '2026-07-10T06:00:00Z',
    seen: false,
    event_type: 'export_ban',
    commodity: 'corn',
    date: '2026-07-10',
    country: 'Argentina',
    summary: 'Argentina halted corn export registrations.',
    label: 'export ban - corn (Argentina)',
    query: 'Has export ban hit corn before? What cascaded?',
    driver_id: 'export_policy',
    headline: 'BREAKING: Argentina slams the door on corn',
    url: 'https://example.com/corn-ban',
    ...over,
  } as unknown as NotificationItem;
}

function mount(setCmd = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NotificationBell setCmd={setCmd} />
    </QueryClientProvider>,
  );
  return setCmd;
}

const bell = () => screen.getByLabelText(/notifications/i);

describe('NotificationBell (P3 Track D)', () => {
  beforeEach(() => {
    h.listNotifications.mockReset().mockResolvedValue([]);
    h.markNotificationSeen.mockReset().mockResolvedValue({ ok: true });
    h.authed = true;
    useUI.getState().clearChips();
    useAsOf.getState().goLive(); // as-of = today (live) so a today-dated item passes the PIT guard
    localStorage.clear();
  });

  it('badge shows the unseen count (2 items, 1 unseen → 1)', async () => {
    h.listNotifications.mockResolvedValue([
      item({ notif_id: 'a', seen: false }),
      item({ notif_id: 'b', seen: true }),
    ]);
    mount();
    expect(await screen.findByTestId('notif-badge')).toHaveTextContent('1');
  });

  it('row click attaches a typed event chip + prefills the composer (no submit)', async () => {
    const n = item();
    h.listNotifications.mockResolvedValue([n]);
    const setCmd = mount();
    await userEvent.click(bell());
    await userEvent.click(await screen.findByRole('button', { name: /export ban/i }));

    const chip = useUI.getState().attachedChips[0]!;
    expect(chip).toMatchObject({ type: 'event', event_type: 'export_ban', commodity: 'corn' });
    expect(setCmd).toHaveBeenCalledWith(n.query);
    expect(setCmd).not.toHaveBeenCalledWith((n as unknown as { headline: string }).headline); // prefill, not headline
  });

  it('the attached chip is a TYPED projection — no headline/url/driver_id leak', async () => {
    h.listNotifications.mockResolvedValue([item()]);
    mount();
    await userEvent.click(bell());
    await userEvent.click(await screen.findByRole('button', { name: /export ban/i }));

    const chip = useUI.getState().attachedChips[0]!;
    expect('headline' in chip).toBe(false);
    expect('url' in chip).toBe(false);
    expect('driver_id' in chip).toBe(false);
  });

  it('row click marks the item seen (POST .../seen)', async () => {
    const n = item({ notif_id: 'seen-me' });
    h.listNotifications.mockResolvedValue([n]);
    mount();
    await userEvent.click(bell());
    await userEvent.click(await screen.findByRole('button', { name: /export ban/i }));
    expect(h.markNotificationSeen).toHaveBeenCalledWith('seen-me');
  });

  it('PIT guard: a future-dated item does NOT attach or mark seen (as-of behind the event)', async () => {
    useAsOf.setState({ asof: '2020-01-01', live: false });
    h.listNotifications.mockResolvedValue([item({ date: '2026-07-10' })]);
    mount();
    await userEvent.click(bell());
    await userEvent.click(await screen.findByRole('button', { name: /export ban/i }));

    expect(useUI.getState().attachedChips).toHaveLength(0);
    expect(h.markNotificationSeen).not.toHaveBeenCalled();
    expect(screen.getByText(/move the as-of forward/i)).toBeInTheDocument();
  });

  it('D-TW-11: the seen-write is AWAITED before the refetch it triggers', async () => {
    h.listNotifications.mockResolvedValue([item()]);
    let markDone!: () => void;
    h.markNotificationSeen.mockReturnValue(
      new Promise<{ ok: boolean }>((res) => {
        markDone = () => res({ ok: true });
      }),
    );
    mount();
    await userEvent.click(bell());
    await userEvent.click(await screen.findByRole('button', { name: /export ban/i }));

    expect(h.markNotificationSeen).toHaveBeenCalledWith('n1');
    // The bug: the invalidate fired alongside the POST, its refetch usually won the race, the row came back
    // still-unseen and the badge kept its count until the 5-minute poll. One list read so far = no refetch.
    expect(h.listNotifications).toHaveBeenCalledTimes(1);

    markDone();
    await waitFor(() => expect(h.listNotifications).toHaveBeenCalledTimes(2));
  });

  it('D-TW-11: a rejected mark-seen is logged, never silent', async () => {
    const err = new Error('502');
    h.listNotifications.mockResolvedValue([item()]);
    h.markNotificationSeen.mockRejectedValue(err);
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    mount();
    await userEvent.click(bell());
    await userEvent.click(await screen.findByRole('button', { name: /export ban/i }));

    await waitFor(() => expect(log).toHaveBeenCalledWith('[notifications] mark-seen failed:', err));
    log.mockRestore();
  });

  it('renders nothing when unauthenticated', () => {
    h.authed = false;
    h.listNotifications.mockResolvedValue([item()]);
    mount();
    expect(screen.queryByLabelText(/notifications/i)).toBeNull();
  });
});
