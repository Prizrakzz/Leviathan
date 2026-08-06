import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { emptyTurn } from '@/api/useTurn';
import { useSession } from '@/store/session';
import { useUI } from '@/store/ui';

// Mock the api layer (NotificationBell/Onboarding convention: hoisted spies shared by mock + assertions) so
// the list renders from fixtures instead of a jsdom fetch. The chevron test below keeps its ready=false gate.
// D-AM-15: the sidebar now also mounts ArtifactsSection, which calls listArtifacts/deleteArtifact off the
// SAME module -- an explicit vi.mock is exhaustive, so both belong here or every test in this file throws.
const h = vi.hoisted(() => ({
  listThreads: vi.fn(),
  deleteThread: vi.fn(),
  renameThread: vi.fn(),
  listArtifacts: vi.fn(),
  deleteArtifact: vi.fn(),
}));
vi.mock('@/api/client', () => ({
  listThreads: h.listThreads,
  deleteThread: h.deleteThread,
  renameThread: h.renameThread,
  listArtifacts: h.listArtifacts,
  deleteArtifact: h.deleteArtifact,
}));

import { DELETE_ARM_MS, ThreadSidebar } from './ThreadSidebar';

const idleTurn = emptyTurn();
const THREADS = { items: [{ id: 't1', title: 'brazil drought', updated_at: '2026-08-01T09:00:00Z' }] };

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThreadSidebar turn={idleTurn} />
    </QueryClientProvider>,
  );
}

// Benign defaults so no describe leaks a live query into the next; each one below sets what it needs. Session
// readiness is likewise set per-describe and never restored: flipping it back after a test re-enables the
// query on a still-mounted tree, which is an un-acted state update (and a fetch) attributed to the test above.
beforeEach(() => {
  h.listThreads.mockReset().mockResolvedValue({ items: [] });
  h.deleteThread.mockReset().mockResolvedValue(undefined);
  h.renameThread.mockReset().mockResolvedValue(undefined);
  h.listArtifacts.mockReset().mockResolvedValue({ items: [] });
  h.deleteArtifact.mockReset().mockResolvedValue(undefined);
});

describe('ThreadSidebar collapse chevron (W1.6)', () => {
  beforeEach(() => {
    // authEnabled=false defaults session ready=true → the live GET /v1/threads query would fire in jsdom.
    // Gate it off: this test is about the chevron wiring, not the thread list.
    useSession.setState({ ready: false });
    useUI.setState({ threadCollapsed: false });
  });

  it('the header chevron flips threadCollapsed (same state the Ctrl+\\ hotkey toggles)', async () => {
    mount();
    expect(useUI.getState().threadCollapsed).toBe(false);
    await userEvent.click(screen.getByLabelText('collapse threads'));
    expect(useUI.getState().threadCollapsed).toBe(true);
  });
});

describe('ThreadSidebar armed delete (D-TW-8)', () => {
  beforeEach(() => {
    useSession.setState({ ready: true });
    h.listThreads.mockResolvedValue(THREADS);
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  /** Settle the mocked GET (and any pending mutation) while the clock is faked: RTL's waitFor only knows how
   *  to advance jest's timers, so the flush has to be explicit here. */
  const settle = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));

  async function arm() {
    mount();
    await settle();
    fireEvent.click(screen.getByLabelText('delete thread'));
    return screen.getByLabelText('confirm delete');
  }

  it('arming focuses the "sure?" button (the rename-box idiom)', async () => {
    expect(await arm()).toHaveFocus();
  });

  it('auto-disarms after DELETE_ARM_MS, deleting nothing', async () => {
    await arm();
    act(() => vi.advanceTimersByTime(DELETE_ARM_MS));
    expect(screen.queryByLabelText('confirm delete')).toBeNull();
    expect(screen.getByLabelText('delete thread')).toBeInTheDocument(); // back to the idle affordance
    expect(h.deleteThread).not.toHaveBeenCalled();
  });

  it('Escape disarms it immediately, deleting nothing', async () => {
    fireEvent.keyDown(await arm(), { key: 'Escape' });
    expect(screen.queryByLabelText('confirm delete')).toBeNull();
    expect(h.deleteThread).not.toHaveBeenCalled();
  });

  it('still deletes on a click inside the armed window (the timer is not a veto)', async () => {
    const btn = await arm();
    act(() => vi.advanceTimersByTime(DELETE_ARM_MS - 1));
    fireEvent.click(btn);
    await settle();
    expect(h.deleteThread).toHaveBeenCalledWith('t1');
  });
});

describe('ThreadSidebar list state (D-TW-12)', () => {
  beforeEach(() => {
    useSession.setState({ ready: true });
  });

  it('a failed fetch shows the error line and NOT the empty-state copy', async () => {
    h.listThreads.mockReset().mockRejectedValue(new Error('502'));
    mount();
    expect(await screen.findByText(/couldn't load threads/i)).toBeInTheDocument();
    // The bug: a failed fetch also has zero items, so both lines rendered -- "you have none" over "we don't know".
    expect(screen.queryByText(/no saved threads yet/i)).toBeNull();
  });

  it('a genuinely empty list still gets the empty-state copy', async () => {
    h.listThreads.mockResolvedValue({ items: [] });
    mount();
    expect(await screen.findByText(/no saved threads yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/couldn't load threads/i)).toBeNull();
  });
});
