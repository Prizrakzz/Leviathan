import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RespondParams } from '@/api/client';
import { DEFAULT_MODE, useMode } from '@/store/mode';
import { useThread } from '@/store/thread';
import { Shell } from './Shell';

/**
 * D-AM-14 end-to-end wiring, through the REAL Shell: the ask bar's picker is what governs the turn the ask
 * bar submits. The transport is the only thing stubbed -- `respondStream` records its params and never
 * settles, which is exactly the live-turn state the composer disables itself in.
 */
const hoisted = vi.hoisted(() => ({ sent: [] as RespondParams[] }));

vi.mock('@/api/client', () => ({
  respondStream: (p: RespondParams) => {
    hoisted.sent.push(p);
    return new Promise<void>(() => {}); // a turn that streams forever -- nothing here asserts on results
  },
  getThreadTurns: () => Promise.resolve({ turns: [] }),
  listThreads: () => Promise.resolve({ items: [] }),
  listArtifacts: () => Promise.resolve({ items: [] }),
  listNotifications: () => Promise.resolve([]),
  getGallery: () => Promise.resolve({ items: [] }),
  suggest: () => Promise.resolve({ suggestions: [] }),
  getProfile: () => Promise.resolve({ onboarded: true, facts: {} }),
  putProfile: () => Promise.resolve({ onboarded: true, facts: {} }),
  getGraph: () => Promise.resolve({ nodes: [], edges: [] }),
  getSeries: () => Promise.resolve({ points: [] }),
  getPdfPage: () => Promise.resolve({}),
  getShare: () => Promise.resolve({}),
  deleteThread: () => Promise.resolve(),
  renameThread: () => Promise.resolve(),
  deleteArtifact: () => Promise.resolve(),
  saveArtifact: () => Promise.resolve({ id: 'a1' }),
  createShare: () => Promise.resolve({ id: 's1', url: '/s/s1' }),
  markNotificationSeen: () => Promise.resolve({ ok: true }),
}));

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Shell />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The hero composer on a brand-new thread, once the empty state has settled. */
async function heroBox() {
  return (await screen.findByTestId('composer-hero')) as HTMLTextAreaElement;
}

describe('Shell: the ask bar mode governs the turn it submits (D-AM-14)', () => {
  beforeEach(() => {
    hoisted.sent = [];
    localStorage.clear();
    useMode.setState({ mode: DEFAULT_MODE });
    useThread.getState().newThread();
  });

  it('the default turn carries `standard` -- and the transport is what drops it', async () => {
    const user = userEvent.setup();
    mount();
    const box = await heroBox();
    await user.type(box, 'why is corn tight?');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    // Shell passes the RAW selection; `store/mode.modeParam` inside openRespondStream is the single place
    // that turns `standard` into an absent param (pinned by api/sse.mode.test.ts).
    expect(hoisted.sent[0]).toMatchObject({ question: 'why is corn tight?', mode: 'standard' });
  });

  it('picking deep at the ask bar sends deep with the next question', async () => {
    const user = userEvent.setup();
    mount();
    await heroBox();

    await user.click(screen.getByTestId('mode-trigger'));
    await user.click(screen.getByTestId('mode-option-deep'));

    const box = await heroBox();
    await user.type(box, 'palm to soyoil transmission');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    expect(hoisted.sent[0]?.mode).toBe('deep');
    expect(hoisted.sent[0]?.question).toBe('palm to soyoil transmission');
  });

  it('the selection persists across a remount -- the desk sets its depth once, not per question', async () => {
    const user = userEvent.setup();
    const first = mount();
    await heroBox();
    await user.click(screen.getByTestId('mode-trigger'));
    await user.click(screen.getByTestId('mode-option-quick'));
    first.unmount();

    // A fresh boot reads the store back out of localStorage (`lv-mode`).
    await useMode.persist.rehydrate();
    mount();
    const box = await heroBox();
    await user.type(box, 'ending stocks corn');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    expect(hoisted.sent[0]?.mode).toBe('quick');
  });
});
