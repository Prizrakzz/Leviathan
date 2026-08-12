import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RespondParams } from '@/api/client';
import type { DossierEvent, DossierQuota, DossierState } from '@/api/schema';
import { useCompose } from '@/store/compose';
import { DEFAULT_CHOICE, useMode } from '@/store/mode';
import { useThread } from '@/store/thread';
import { useUI } from '@/store/ui';
import { Shell } from './Shell';

/**
 * D-DR-3 end-to-end, through the REAL Shell: choosing **Deep Research** turns the composer's submit into a
 * dossier JOB — a different route, a progress surface driven by the SSE events, and a landing as a frozen
 * ARTIFACT TAB rather than a chat bubble. The transports are the only things stubbed.
 */
const hoisted = vi.hoisted(() => ({
  sent: [] as RespondParams[],
  posted: [] as { question: string; asof?: string }[],
  quotaCalls: 0,
  quota: { remaining: 2, limit: 4, reset_at: '2026-09-01T00:00:00Z' } as DossierQuota | null,
  /** What POST /v1/dossier does. Replaced per-test to drive the 429 path. */
  createImpl: null as null | (() => Promise<{ dossier_id: string }>),
  /** The scripted stage stream. */
  events: [] as DossierEvent[],
  /** What the reconnect poll answers when the stream ends without a terminal event. */
  polled: null as DossierState | null,
  artifacts: [] as { id: string; name?: string }[],
}));

vi.mock('@/api/client', () => ({
  respondStream: (p: RespondParams) => {
    hoisted.sent.push(p);
    return new Promise<void>(() => {});
  },
  getThreadTurns: () => Promise.resolve({ turns: [] }),
  listThreads: () => Promise.resolve({ items: [] }),
  listArtifacts: () => Promise.resolve({ items: hoisted.artifacts }),
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

// D-MW-25: the depth control also reads the credit grant. This suite is about the DOSSIER meter, which is
// a separate one, so credits are dark here -- which is itself the pin that the two never got merged.
vi.mock('@/api/credits', async (orig) => {
  const actual = await orig<typeof import('@/api/credits')>();
  return { ...actual, getCredits: () => Promise.resolve(null) };
});

// The REAL DossierQuotaError class is kept (useDossier branches on `instanceof`), and only the four calls
// that touch the network are replaced.
vi.mock('@/api/dossier', async (orig) => {
  const actual = await orig<typeof import('@/api/dossier')>();
  return {
    ...actual,
    createDossier: (question: string, asof?: string) => {
      hoisted.posted.push({ question, asof });
      return hoisted.createImpl
        ? hoisted.createImpl()
        : Promise.resolve({ dossier_id: 'd-1', plan_pending: true });
    },
    getDossierQuota: () => {
      hoisted.quotaCalls += 1;
      return Promise.resolve(hoisted.quota);
    },
    getDossier: () =>
      hoisted.polled ? Promise.resolve(hoisted.polled) : Promise.reject(new Error('no poll scripted')),
    openDossierStream: async (_id: string, h: { onEvent?: (e: DossierEvent) => void; onDrop?: (r: string) => void }) => {
      for (const e of hoisted.events) {
        h.onEvent?.(e);
        if (actual.isTerminalType(e.type)) return;
      }
      h.onDrop?.('the progress stream ended before the dossier did');
    },
  };
});

const PLAN: DossierEvent = {
  type: 'plan',
  subqueries: [
    { i: 1, n: 3, title: 'balance: stocks-to-use vs its own history' },
    { i: 2, n: 3, title: 'curve: what the term structure prices' },
    { i: 3, n: 3, title: 'episodes: dated windows that look like this' },
  ],
};

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

async function ask(user: ReturnType<typeof userEvent.setup>, q: string) {
  const box = (await screen.findByTestId('composer-hero')) as HTMLTextAreaElement;
  await user.type(box, q);
  await user.keyboard('{Enter}');
  return box;
}

beforeEach(() => {
  hoisted.sent = [];
  hoisted.posted = [];
  hoisted.quotaCalls = 0;
  hoisted.quota = { remaining: 2, limit: 4, reset_at: '2026-09-01T00:00:00Z' };
  hoisted.createImpl = null;
  hoisted.events = [];
  hoisted.polled = null;
  hoisted.artifacts = [];
  localStorage.clear();
  useMode.setState({ choice: 'deep_research' });
  useUI.setState({ tabs: [], activeTabId: null });
  // The compose store is module-level and survives a remount BY DESIGN (a restored question must still be
  // there after a reload), so a suite that exercises the restore path has to reset it between cases or the
  // next mount re-prefills the previous test's words into a fresh box.
  useCompose.setState({ draft: '', rev: 0, focus: false, template: null, slots: [], values: {}, options: {}, spans: {} });
  useThread.getState().newThread();
});

describe('Shell: Deep Research submits a DOSSIER, not a turn (D-DR-3)', () => {
  it('posts the question + the submission as-of, and starts no turn at all', async () => {
    const user = userEvent.setup();
    hoisted.events = [PLAN, { type: 'done', artifact_id: 'art-1' }];
    mount();
    await ask(user, 'how tight is the corn balance?');

    await waitFor(() => expect(hoisted.posted).toHaveLength(1));
    expect(hoisted.posted[0]?.question).toBe('how tight is the corn balance?');
    expect(typeof hoisted.posted[0]?.asof).toBe('string'); // ONE as-of, stamped at submission (D-DR-1)
    // The ask path is untouched: not one byte went to /v1/respond/stream.
    expect(hoisted.sent).toHaveLength(0);
  });

  it('renders the staged progress surface from the SSE events, then lands an ARTIFACT TAB', async () => {
    const user = userEvent.setup();
    hoisted.artifacts = [{ id: 'art-1', name: 'corn balance dossier' }];
    hoisted.events = [
      PLAN,
      { type: 'subquery', i: 1, n: 3, status: 'done' },
      { type: 'subquery', i: 2, n: 3, status: 'done' },
      { type: 'subquery', i: 3, n: 3, status: 'done' },
      { type: 'synthesis' },
      { type: 'done', artifact_id: 'art-1' },
    ];
    mount();
    await ask(user, 'how tight is the corn balance?');

    // The plan is VISIBLE (the Gemini lesson, D-DR-1 step 2): every sub-question by title.
    await waitFor(() => expect(screen.getByTestId('dossier-progress')).toBeTruthy());
    expect(screen.getByTestId('dossier-subquery-1')).toHaveTextContent('stocks-to-use');
    expect(screen.getByTestId('dossier-subquery-3')).toHaveTextContent('dated windows');
    expect(screen.getByTestId('dossier-stage-subqueries')).toHaveTextContent('3/3');
    expect(screen.getByTestId('dossier-stage-synthesis').getAttribute('data-state')).toBe('done');

    // The dossier lands as the FROZEN ARTIFACT, never as a chat bubble.
    await waitFor(() => expect(useUI.getState().tabs).toHaveLength(1));
    const tab = useUI.getState().tabs[0]!;
    expect(tab.kind).toBe('artifact');
    expect(tab.id).toBe('artifact:art-1');
    expect(tab.title).toBe('corn balance dossier'); // the server's own name, read off the refetched list
    expect(useUI.getState().activeTabId).toBe('artifact:art-1');
    expect(screen.getByTestId('dossier-open-tab')).toBeTruthy(); // "open in tab" rides the artifact seam
  });

  it('a PARTIAL dossier says so and still lands — honest-partial, never silent', async () => {
    const user = userEvent.setup();
    hoisted.events = [
      PLAN,
      { type: 'subquery', i: 1, n: 3, status: 'done' },
      { type: 'subquery', i: 2, n: 3, status: 'failed' },
      { type: 'partial', artifact_id: 'art-2', error: 'the curve leg returned no dated rows' },
    ];
    mount();
    await ask(user, 'how tight is the corn balance?');

    await waitFor(() => expect(screen.getByTestId('dossier-partial')).toBeTruthy());
    expect(screen.getByTestId('dossier-partial')).toHaveTextContent('curve leg');
    expect(screen.getByTestId('dossier-status')).toHaveTextContent('partial');
    // Row 3 was never reported on. The card says exactly that rather than inventing a verdict.
    expect(screen.getByTestId('dossier-subquery-3')).toHaveTextContent('no result reported');
    await waitFor(() => expect(useUI.getState().tabs[0]?.id).toBe('artifact:art-2'));
  });

  it('a stream that drops mid-job asks the server what happened instead of declaring failure', async () => {
    const user = userEvent.setup();
    hoisted.events = [PLAN, { type: 'subquery', i: 1, n: 3, status: 'done' }]; // ends with no terminal event
    hoisted.polled = { status: 'done', artifact_id: 'art-3' };
    mount();
    await ask(user, 'how tight is the corn balance?');

    await waitFor(() => expect(useUI.getState().tabs[0]?.id).toBe('artifact:art-3'));
    expect(screen.getByTestId('dossier-status')).toHaveTextContent('done');
    expect(screen.queryByTestId('dossier-failed')).toBeNull();
  });

  it('a dropped stream AND an unreachable job is reported as a failure, not left spinning', async () => {
    const user = userEvent.setup();
    hoisted.events = [PLAN];
    hoisted.polled = null; // the poll rejects
    mount();
    await ask(user, 'how tight is the corn balance?');

    await waitFor(() => expect(screen.getByTestId('dossier-failed')).toBeTruthy());
    expect(screen.getByTestId('dossier-stage-plan').getAttribute('data-state')).toBe('done');
    expect(screen.getByTestId('dossier-stage-subqueries').getAttribute('data-state')).toBe('stopped');
    expect(useUI.getState().tabs).toHaveLength(0);
  });

  it('the quota is re-read after a submission, so the badge never promises a run just spent', async () => {
    const user = userEvent.setup();
    hoisted.events = [PLAN, { type: 'done', artifact_id: 'art-1' }];
    mount();
    await waitFor(() => expect(hoisted.quotaCalls).toBeGreaterThanOrEqual(1));
    const before = hoisted.quotaCalls;
    await ask(user, 'how tight is the corn balance?');
    await waitFor(() => expect(hoisted.quotaCalls).toBeGreaterThan(before));
  });
});

describe('Shell: a refused dossier is non-destructive (D-DR-2 quota)', () => {
  it('429 -> a toast with the RESET DATE, the question handed back, and no job card', async () => {
    const user = userEvent.setup();
    const { DossierQuotaError } = await import('@/api/dossier');
    hoisted.createImpl = () =>
      Promise.reject(new DossierQuotaError('no deep research runs left this month', '2026-09-01T00:00:00Z'));
    mount();
    const box = await ask(user, 'how tight is the corn balance?');

    await waitFor(() => expect(screen.getByTestId('dossier-toast')).toBeTruthy());
    expect(screen.getByTestId('dossier-toast')).toHaveTextContent('no deep research runs left this month');
    expect(screen.getByTestId('dossier-toast-reset')).toHaveTextContent('2026-09-01');
    // Non-destructive: the words come back into the box the user typed them in.
    await waitFor(() => expect(box.value).toBe('how tight is the corn balance?'));
    expect(screen.queryByTestId('dossier-progress')).toBeNull();
    expect(hoisted.sent).toHaveLength(0); // and it certainly did not fall back to a normal turn
  });

  it('any other refusal surfaces the server sentence and still hands the question back', async () => {
    const user = userEvent.setup();
    hoisted.createImpl = () => Promise.reject(new Error('deep research is not enabled for this account'));
    mount();
    const box = await ask(user, 'how tight is the corn balance?');

    await waitFor(() => expect(screen.getByTestId('dossier-toast')).toBeTruthy());
    expect(screen.getByTestId('dossier-toast')).toHaveTextContent('not enabled for this account');
    expect(screen.queryByTestId('dossier-toast-reset')).toBeNull(); // no date invented for a non-quota error
    await waitFor(() => expect(box.value).toBe('how tight is the corn balance?'));
  });

  it('the toast is dismissible and the surface disappears with it', async () => {
    const user = userEvent.setup();
    hoisted.createImpl = () => Promise.reject(new Error('nope'));
    mount();
    await ask(user, 'q');
    await waitFor(() => expect(screen.getByTestId('dossier-toast')).toBeTruthy());
    await user.click(screen.getByLabelText('dismiss'));
    expect(screen.queryByTestId('dossier-surface')).toBeNull();
  });
});

describe('Shell: Standard is unaffected by any of this', () => {
  it('with Standard selected the dossier route is never touched', async () => {
    const user = userEvent.setup();
    useMode.setState({ choice: DEFAULT_CHOICE });
    mount();
    await ask(user, 'why is corn tight?');
    await waitFor(() => expect(hoisted.sent).toHaveLength(1));
    expect(hoisted.sent[0]?.mode).toBe('quick');
    expect(hoisted.posted).toHaveLength(0);
    expect(screen.queryByTestId('dossier-surface')).toBeNull();
  });
});
