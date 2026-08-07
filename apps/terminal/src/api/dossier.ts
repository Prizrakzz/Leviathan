import { fetchWithAuth } from '../auth/oidc';
import { httpErrorMessage } from './errors';
import type {
  DossierAccepted,
  DossierEvent,
  DossierQuota,
  DossierState,
} from './schema';
import { readSSEBlocks, SSE_IDLE_MS } from './sse';

/**
 * D-DR — the deep-research dossier transport.
 *
 * A dossier is a JOB, not a turn, and the seam says so: a POST that returns 202 with an id, a stage stream
 * to watch it, a poll to read it back, and a small quota GET. It lands as a frozen ARTIFACT (the D-AM-15
 * share/artifacts seam) — never as a chat bubble — so nothing here returns an answer body.
 *
 * DARK-FIRST is a first-class case, not an error. `GRAPHRAG_DOSSIER` absent means every route 404s, and the
 * FE must render that as "not available here" rather than as a broken feature: `getDossierQuota` answers
 * `null` on 404 and the picker disables the option with an honest hint. Only a 404 is treated that way; a
 * 500 still throws, because a server fault is not a product decision.
 */

const BASE = import.meta.env.VITE_API_BASE ?? '';
const MOCK = import.meta.env.VITE_MOCK === '1';

/** The quota's react-query key. Declared HERE, next to the fetcher, so the picker's badge and the submit
 *  path's post-submission refetch can never drift onto two keys and show two different numbers. */
export const DOSSIER_QUOTA_KEY = ['dossier-quota'] as const;

/** The dossier wall clock (D-DR-1: ~20 min job cap). The stage stream is quiet for minutes at a time while a
 *  sub-query runs, so the turn transport's 90s no-bytes watchdog would kill a healthy job. The backend's
 *  keepalive is what makes any window meaningful; this one is generous by the same margin as SSE_IDLE_MS. */
export const DOSSIER_IDLE_MS = 6 * SSE_IDLE_MS; // 9 min of total silence = dead, not slow

/** A 429 from POST /v1/dossier. Carries the reset date so the composer's toast can say WHEN, not just no —
 *  a bare "quota exhausted" on a WEEKLY allowance is the least actionable refusal we could ship. */
export class DossierQuotaError extends Error {
  readonly resetAt?: string;
  constructor(message: string, resetAt?: string) {
    super(message);
    this.name = 'DossierQuotaError';
    this.resetAt = resetAt;
  }
}

/** Pull `reset_at` out of whatever shape the refusal arrived in: top-level (the locked contract) or nested
 *  under FastAPI's `detail` (what a HTTPException(detail={...}) produces). Never throws. */
function resetAtOf(body: unknown): string | undefined {
  const b = (body ?? {}) as { reset_at?: unknown; detail?: { reset_at?: unknown } | unknown };
  if (typeof b.reset_at === 'string') return b.reset_at;
  const d = (b as { detail?: { reset_at?: unknown } }).detail;
  if (d && typeof d === 'object' && typeof (d as { reset_at?: unknown }).reset_at === 'string')
    return (d as { reset_at: string }).reset_at;
  return undefined;
}

/** Submit a dossier. 202 -> `{dossier_id, plan_pending}`; 429 -> DossierQuotaError with the reset date.
 *  The as-of is stamped ONCE at submission and governs every sub-query (D-DR-1 PIT-by-construction), so it
 *  rides the body rather than being re-read per sub-call. */
export async function createDossier(question: string, asof?: string): Promise<DossierAccepted> {
  if (MOCK) return mockCreateDossier();
  const res = await fetchWithAuth(`${BASE}/v1/dossier`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(asof ? { question, asof } : { question }),
  });
  if (res.ok) return (await res.json()) as DossierAccepted;
  // Read the body ONCE: `httpErrorMessage` consumes it, so the 429 branch parses first and builds its own
  // sentence from what it found (falling back to the server's `detail` when it is a plain string).
  if (res.status === 429) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // no body / not JSON -- the generic sentence below is all we have
    }
    const detail = (body as { detail?: unknown } | null)?.detail;
    const msg =
      typeof detail === 'string' && detail.trim()
        ? detail.trim()
        : 'no deep research runs left this week';
    throw new DossierQuotaError(msg, resetAtOf(body));
  }
  throw new Error(await httpErrorMessage(res, 'POST /v1/dossier'));
}

/** Read a dossier back (a reconnect, or a stream that died mid-job). */
export async function getDossier(id: string): Promise<DossierState> {
  if (MOCK) return { status: 'done', subqueries: [], artifact_id: 'mock-dossier-artifact' };
  const res = await fetchWithAuth(`${BASE}/v1/dossier/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(await httpErrorMessage(res, `GET /v1/dossier/${id}`));
  return (await res.json()) as DossierState;
}

/** The weekly allowance, or `null` when the dossier routes are dark (404). See the header note. */
export async function getDossierQuota(): Promise<DossierQuota | null> {
  if (MOCK) return { remaining: 2, limit: 3, reset_at: mockResetAt() };
  const res = await fetchWithAuth(`${BASE}/v1/dossier/quota`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await httpErrorMessage(res, 'GET /v1/dossier/quota'));
  return (await res.json()) as DossierQuota;
}

export interface DossierStreamHandlers {
  onEvent?: (e: DossierEvent) => void;
  /** The stream ended with NO terminal event (dropped, stalled, or a server that just stopped). */
  onDrop?: (reason: string) => void;
}

/**
 * Open the dossier's stage stream and pump it. Terminal events are `done` / `partial` / `failed` / `error`;
 * a `done`/`partial` carries the artifact_id the caller opens as a tab.
 *
 * Dispatch is on the PAYLOAD's `type`, not on the SSE `event:` name, because that is where the locked
 * contract puts the discriminator. A block whose data does not parse, or carries no `type`, is skipped
 * rather than guessed at.
 */
export async function openDossierStream(
  id: string,
  h: DossierStreamHandlers,
  signal?: AbortSignal,
  idleMs: number = DOSSIER_IDLE_MS,
): Promise<void> {
  if (MOCK) return mockDossierStream(h);
  const res = await fetchWithAuth(`${BASE}/v1/dossier/${encodeURIComponent(id)}/events`, {
    headers: { Accept: 'text/event-stream' },
    signal,
  });
  if (!res.ok || !res.body) {
    h.onDrop?.(res.ok ? 'the progress stream did not open' : await httpErrorMessage(res));
    return;
  }
  const { terminated, stalled } = await readSSEBlocks(res.body, (block) => dispatchDossierBlock(block, h), idleMs);
  if (terminated) return;
  h.onDrop?.(
    stalled
      ? `the progress stream went quiet for ${Math.round(idleMs / 60000)} min`
      : 'the progress stream ended before the dossier did',
  );
}

/** true == terminal (stop reading). Exported for the unit tests, which drive it block by block. */
export function dispatchDossierBlock(block: string, h: DossierStreamHandlers): boolean {
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue; // blank or keepalive comment
    if (line.startsWith('data:')) data.push(line.slice(5).trim());
  }
  if (!data.length) return false;
  let payload: unknown;
  try {
    payload = JSON.parse(data.join('\n'));
  } catch {
    return false;
  }
  const e = payload as DossierEvent;
  if (!e || typeof e.type !== 'string') return false;
  h.onEvent?.(e);
  return isTerminalType(e.type);
}

export function isTerminalType(type: string): boolean {
  return type === 'done' || type === 'partial' || type === 'failed' || type === 'error';
}

// ── VITE_MOCK=1: a synthetic job so the whole surface runs without a backend ────────────────────────
function mockResetAt(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + (8 - (d.getUTCDay() || 7))); // next UTC Monday
  d.setUTCHours(0, 0, 0, 0);
  return d.toISOString();
}

function mockCreateDossier(): Promise<DossierAccepted> {
  return Promise.resolve({ dossier_id: 'mock-dossier-1', plan_pending: true });
}

async function mockDossierStream(h: DossierStreamHandlers): Promise<void> {
  const titles = [
    'balance: where does the S/U ratio sit vs its own history?',
    'curve: what does the term structure price for carry?',
    'positioning: what is the managed-money net doing?',
    'episodes: which dated windows look like this one?',
  ];
  const n = titles.length;
  const tick = () => new Promise((r) => setTimeout(r, 120));
  h.onEvent?.({ type: 'plan', subqueries: titles.map((title, k) => ({ i: k + 1, n, title, status: 'pending' })) });
  for (let k = 0; k < n; k += 1) {
    await tick();
    h.onEvent?.({ type: 'subquery', i: k + 1, n, title: titles[k]!, status: 'running' });
    await tick();
    h.onEvent?.({ type: 'subquery', i: k + 1, n, title: titles[k]!, status: 'done' });
  }
  await tick();
  h.onEvent?.({ type: 'synthesis', stage: 'composing the dossier' });
  await tick();
  h.onEvent?.({ type: 'done', artifact_id: 'mock-dossier-artifact' });
}
