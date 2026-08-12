import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RespondParams } from '@/api/client';
import type { CreditsRefusal } from '@/api/errors';
import type { StreamHandlers } from '@/api/sse';
import { useCompose } from '@/store/compose';
import { DEFAULT_CHOICE, useMode } from '@/store/mode';
import { useThread } from '@/store/thread';
import { Shell } from './Shell';

/**
 * D-MW-25 — what a user SEES when the credits wall fires, through the real Shell.
 *
 * The wall arrives as a non-OK 429 before the stream opens (the gate refuses in the quota dependency, by
 * construction), so the transport reports it through `onError` with the structured refusal alongside the
 * sentence. Three things have to happen, and all three are the difference between a refusal and a loss:
 * the reason and the RESET DAY on screen, the question back in the box, and the balance re-read.
 */
const hoisted = vi.hoisted(() => ({
  sent: [] as RespondParams[],
  refusal: undefined as CreditsRefusal | undefined,
  /** A non-credits ask-route failure (status + sentence) — the busy-lease 429 is the one that matters. */
  plainFail: undefined as { status?: number; message: string } | undefined,
  creditCalls: 0,
}));

vi.mock('@/api/client', () => ({
  respondStream: (p: RespondParams, h: StreamHandlers) => {
    hoisted.sent.push(p);
    if (hoisted.refusal)
      h.onError?.({ error: hoisted.refusal.message, credits: hoisted.refusal, status: 429 });
    else if (hoisted.plainFail)
      h.onError?.({ error: hoisted.plainFail.message, status: hoisted.plainFail.status });
    return Promise.resolve();
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

vi.mock('@/api/dossier', async (orig) => {
  const actual = await orig<typeof import('@/api/dossier')>();
  return { ...actual, getDossierQuota: () => Promise.resolve(null) };
});

vi.mock('@/api/credits', async (orig) => {
  const actual = await orig<typeof import('@/api/credits')>();
  return {
    ...actual,
    getCredits: () => {
      hoisted.creditCalls += 1;
      return Promise.resolve({ remaining: 0, limit: 100, reset_at: '2026-09-01T00:00:00Z' });
    },
  };
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

/** Ask a question through whichever composer is on screen (hero on an empty thread, pinned afterwards),
 *  clearing whatever a previous restore put back in the box. */
async function ask(user: ReturnType<typeof userEvent.setup>, q: string) {
  const box = (screen.queryByTestId('composer') ??
    (await screen.findByTestId('composer-hero'))) as HTMLTextAreaElement;
  if (box.value) await user.clear(box);
  await user.type(box, q);
  await user.keyboard('{Enter}');
}

beforeEach(() => {
  hoisted.sent = [];
  hoisted.refusal = undefined;
  hoisted.plainFail = undefined;
  hoisted.creditCalls = 0;
  localStorage.clear();
  useMode.setState({ choice: DEFAULT_CHOICE });
  useCompose.getState().clear();
  useThread.getState().newThread();
});

describe('Shell: the credits wall (D-MW-25)', () => {
  it('shows the reason WITH the reset day, and hands the question back to the composer', async () => {
    hoisted.refusal = {
      message: 'no credits left this month',
      code: 'credits_exhausted',
      limit: 100,
      remaining: 0,
      resetAt: '2026-09-01T00:00:00Z',
    };
    const user = userEvent.setup();
    mount();
    await ask(user, 'why is corn tight?');

    const toast = await screen.findByTestId('credits-toast');
    expect(toast).toHaveTextContent('no credits left this month');
    expect(screen.getByTestId('credits-toast-reset')).toHaveTextContent('2026-09-01');
    // Non-destructive: the words come back through the D-UX-1 compose seam.
    await waitFor(() => expect(useCompose.getState().draft).toBe('why is corn tight?'));
  });

  it('re-reads the balance after a refusal — a 429 PROVES the number moved', async () => {
    hoisted.refusal = { message: 'no credits left this month', resetAt: '2026-09-01T00:00:00Z' };
    const user = userEvent.setup();
    mount();
    await waitFor(() => expect(hoisted.creditCalls).toBe(1)); // the mount read
    await ask(user, 'why is corn tight?');
    await waitFor(() => expect(hoisted.creditCalls).toBeGreaterThan(1));
  });

  it('the toast is dismissible, and dismissing one does not suppress the next', async () => {
    hoisted.refusal = { message: 'no credits left this month', resetAt: '2026-09-01T00:00:00Z' };
    const user = userEvent.setup();
    mount();
    await ask(user, 'first question');
    await screen.findByTestId('credits-toast');
    await user.click(screen.getByLabelText('dismiss'));
    expect(screen.queryByTestId('credits-toast')).toBeNull();

    hoisted.refusal = { message: 'still no credits', resetAt: '2026-09-01T00:00:00Z' };
    await ask(user, 'second question');
    await waitFor(() => expect(screen.getByTestId('credits-toast')).toHaveTextContent('still no credits'));
  });

  it('an ORDINARY failure is not a credits wall — no toast, and the composer is left alone', async () => {
    const user = userEvent.setup();
    mount();
    hoisted.refusal = undefined;
    await ask(user, 'why is corn tight?');
    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    expect(screen.queryByTestId('credits-toast')).toBeNull();
    expect(useCompose.getState().draft).toBe('');
  });

  it('the BUSY-LEASE 429 also hands the question back — the restore is not credits-shape-gated', async () => {
    // P5 review F6. "A metered turn is already running on this account" is deliberately NOT the credits
    // shape (different copy, no reset day, no balance) and it is reachable on an ordinary reload mid-
    // Analysis. It is also perfectly retryable — so losing the analyst's sentence to it is a loss, not a
    // refusal. Only the COPY is credits-gated: no toast here, but the words come back.
    hoisted.plainFail = {
      status: 429,
      message: 'a metered turn is already running on this account; wait for it to finish, or run this question as a Scan',
    };
    const user = userEvent.setup();
    mount();
    await ask(user, 'palm to soyoil transmission');
    await waitFor(() => expect(useCompose.getState().draft).toBe('palm to soyoil transmission'));
    expect(screen.queryByTestId('credits-toast')).toBeNull();
  });

  it('a non-429 ask failure leaves the box alone — the restore is a REFUSAL affordance, not a catch-all', async () => {
    hoisted.plainFail = { status: 503, message: 'upstream unavailable' };
    const user = userEvent.setup();
    mount();
    await ask(user, 'why is corn tight?');
    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    expect(useCompose.getState().draft).toBe('');
  });

  it('each QUESTION carries its own turn id — a retry is one charge, two questions are two', async () => {
    // P5 review F4, from the user's side of the seam: the id is minted per question at the submit
    // chokepoint, so the server can recognise a replay of THIS question and refuse to bill it twice.
    hoisted.refusal = { message: 'no credits left this month', resetAt: '2026-09-01T00:00:00Z' };
    const user = userEvent.setup();
    mount();
    await ask(user, 'first question');
    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    await ask(user, 'second question');
    await waitFor(() => expect(hoisted.sent).toHaveLength(2));
    expect(hoisted.sent[0]!.turnId).toBeTruthy();
    expect(hoisted.sent[0]!.turnId).not.toBe(hoisted.sent[1]!.turnId);
  });
});
