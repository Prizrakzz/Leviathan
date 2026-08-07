import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RespondParams } from '@/api/client';
import { DEFAULT_CHOICE, useMode } from '@/store/mode';
import { useThread } from '@/store/thread';
import { Shell } from './Shell';

/**
 * D-DR-3's STANDARD-MODE INVARIANT, through the REAL Shell: a normal ask is byte-identical to what it was
 * before the two-mode rework, except that the mode field is now always `quick` (the wire value of the
 * **Standard** label). The transport is the only thing stubbed -- `respondStream` records its params and
 * never settles, which is exactly the live-turn state the composer disables itself in.
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

// The picker reads the weekly allowance. This suite is about the ASK path, so the dossier routes are dark.
vi.mock('@/api/dossier', async (orig) => {
  const actual = await orig<typeof import('@/api/dossier')>();
  return { ...actual, getDossierQuota: () => Promise.resolve(null) };
});

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

describe('Shell: the Standard ask (D-DR-3 invariant)', () => {
  beforeEach(() => {
    hoisted.sent = [];
    localStorage.clear();
    useMode.setState({ choice: DEFAULT_CHOICE });
    useThread.getState().newThread();
  });

  it('every ask carries mode `quick` — the label is Standard, the wire says quick', async () => {
    const user = userEvent.setup();
    mount();
    const box = await heroBox();
    await user.type(box, 'why is corn tight?');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    expect(hoisted.sent[0]).toMatchObject({ question: 'why is corn tight?', mode: 'quick' });
  });

  it('the captured submit is byte-identical to the pre-wave one apart from `mode`', async () => {
    const user = userEvent.setup();
    mount();
    const box = await heroBox();
    await user.type(box, 'ending stocks corn');
    await user.keyboard('{Enter}');
    await waitFor(() => expect(hoisted.sent).toHaveLength(1));

    // The WHOLE param object, key by key: no field appeared, none disappeared, and nothing dossier-shaped
    // leaked onto the turn request. `context` stays absent with no chips attached (the pre-wave shape);
    // `asof` and `sessionId` are the store values Shell has always read at submit.
    const sent = hoisted.sent[0]!;
    expect(Object.keys(sent).sort()).toEqual(['asof', 'context', 'mode', 'question', 'sessionId']);
    expect(sent.context).toBeUndefined();
    expect(sent.mode).toBe('quick');
    expect(sent.question).toBe('ending stocks corn');
    expect(typeof sent.sessionId).toBe('string');
  });

  it('choosing Standard explicitly changes nothing about the request', async () => {
    const user = userEvent.setup();
    mount();
    await heroBox();
    await user.click(screen.getByTestId('mode-trigger'));
    await user.click(screen.getByTestId('mode-option-quick'));

    const box = await heroBox();
    await user.type(box, 'palm to soyoil transmission');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    expect(hoisted.sent[0]?.mode).toBe('quick');
    expect(hoisted.sent[0]?.question).toBe('palm to soyoil transmission');
  });

  it('the selection persists across a remount — the desk sets its depth once, not per question', async () => {
    const user = userEvent.setup();
    const first = mount();
    await heroBox();
    await user.click(screen.getByTestId('mode-trigger'));
    await user.click(screen.getByTestId('mode-option-quick'));
    first.unmount();

    // A fresh boot reads the store back out of localStorage (`lv-mode`).
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('quick');
    mount();
    const box = await heroBox();
    await user.type(box, 'ending stocks corn');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    expect(hoisted.sent[0]?.mode).toBe('quick');
  });
});
