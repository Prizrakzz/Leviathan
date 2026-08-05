import { fetchWithAuth } from '../auth/oidc';
import { httpError } from './errors';
import { MOCK_SERIES, mockGraph, mockRespondStream } from './mock';
import type { ContextAttachment, NotificationItem, PdfPage } from './schema';
import { openRespondStream, type StreamHandlers } from './sse';
import type { components } from './types.gen';

type Schemas = components['schemas'];

const BASE = import.meta.env.VITE_API_BASE ?? '';
const MOCK = import.meta.env.VITE_MOCK === '1';

/** Stream a turn. `VITE_MOCK=1` routes to the in-repo mock so the whole UI runs without the backend. */
export function respondStream(
  params: { question: string; asof?: string; sessionId?: string; context?: ContextAttachment[] },
  h: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return MOCK ? mockRespondStream(params, h) : openRespondStream(BASE, params, h, signal);
}

// All four helpers below route through fetchWithAuth (oidc.ts) so the bearer header AND the shared
// 401-retry-after-forced-refresh (D-W6.2) live in ONE place — never re-implemented per verb. They also
// share ONE failure shape (httpError, D-TW-6) so the server's own `detail` sentence reaches the caller
// instead of a bare status code.
async function getJSON<T>(path: string): Promise<T> {
  const res = await fetchWithAuth(`${BASE}${path}`);
  if (!res.ok) throw await httpError(res, path);
  return (await res.json()) as T;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithAuth(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await httpError(res, path);
  return (await res.json()) as T;
}

async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithAuth(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await httpError(res, path);
  return (await res.json()) as T;
}

const q = (asof?: string) => (asof ? `?asof=${encodeURIComponent(asof)}` : '');

export function getGraph(contract: string, asof?: string): Promise<Schemas['GraphTopology']> {
  if (MOCK) return Promise.resolve(mockGraph(contract)); // per-contract mock so the DAG matches the answer
  return getJSON(`/v1/graph/${encodeURIComponent(contract)}${q(asof)}`);
}

/** The vintage-aware series behind a NUMBERS row's sparkline. `country` is NOT optional decoration: the
 *  number call that produced the row may have been country-scoped (silver_psd, exports, weather), and
 *  GET /v1/series takes the same filter -- omitting it returned a DIFFERENT, unscoped series under the same
 *  `[N#]` label (D-TW-9). It is part of the query identity for the cache too; see Numbers.tsx's key. */
export function getSeries(
  table: string,
  metric: string,
  opts: { commodity?: string; country?: string; asof?: string } = {},
): Promise<Schemas['Series']> {
  if (MOCK) return Promise.resolve(MOCK_SERIES);
  const p = new URLSearchParams();
  if (opts.commodity) p.set('commodity', opts.commodity);
  if (opts.country) p.set('country', opts.country);
  if (opts.asof) p.set('asof', opts.asof);
  const qs = p.toString();
  return getJSON(
    `/v1/series/${encodeURIComponent(table)}/${encodeURIComponent(metric)}${qs ? `?${qs}` : ''}`,
  );
}

// ── 6.6 profile / settings / onboarding (auth-gated per-user) ──────────────────────────────────────
export type Profile = Schemas['Profile'];
export type ProfileUpdate = Schemas['ProfileUpdate'];

/** The signed-in user's own profile (identity + facts + onboarding flag). `VITE_MOCK=1` routes to the mock. */
export function getProfile(): Promise<Profile> {
  if (MOCK) return import('./mock').then((m) => m.mockGetProfile());
  return getJSON(`/v1/profile`);
}

/** Update facts and/or the onboarding flag (a partial update). Returns the fresh, server-normalized profile. */
export function putProfile(update: ProfileUpdate): Promise<Profile> {
  if (MOCK) return import('./mock').then((m) => m.mockPutProfile(update));
  return putJSON(`/v1/profile`, update);
}

// ── 6.5 PDF click-to-page (auth rides fetchWithAuth via getJSON; gated server-side by GRAPHRAG_PDF_LINKS) ──
// `PdfPage` is defined in ./schema (a leaf module) so the mock can name it without importing this file.
/** Resolve a citation's source PDF + page. `snippet`/`charStart`/`offsetKind` come off the chip's doc
 *  locator (6.5): a char offset resolves an EXACT page for new/E4 props, the snippet drives server-side
 *  fuzzy-match for legacy props. `VITE_MOCK=1` routes to the in-repo mock. The kill-switch 404s when off;
 *  the rejection surfaces to the modal's error state (which keeps the raw-download escape). */
export function getPdfPage(
  sourceKey: string,
  snippet?: string,
  charStart?: number,
  offsetKind?: string,
): Promise<PdfPage> {
  if (MOCK) return import('./mock').then((m) => m.mockGetPdfPage(sourceKey, snippet, charStart, offsetKind));
  const p = new URLSearchParams({ source_key: sourceKey });
  if (snippet) p.set('snippet', snippet);
  if (charStart != null) p.set('char_start', String(charStart));
  if (offsetKind) p.set('offset_kind', offsetKind);
  return getJSON(`/v1/citation/pdf?${p.toString()}`);
}

// ── 6.2 query suggester (decoupled; fired once per completed turn / thread start) ──────────────────
export type SuggestPacket = Schemas['SuggestRequest'];

export function suggest(packet: SuggestPacket): Promise<Schemas['SuggestResponse']> {
  if (MOCK) return import('./mock').then((m) => m.mockSuggest(packet));
  return postJSON(`/v1/suggest`, packet);
}

// ── P3 Track D: daily-digest notifications (auth-gated + kill-switched server-side) ─────────────────
/** The signed-in user's notification digest, newest-first. `VITE_MOCK=1` routes to the in-repo mock so the
 *  bell + badge render without a backend. */
export function listNotifications(): Promise<NotificationItem[]> {
  if (MOCK) return import('./mock').then((m) => m.mockListNotifications());
  return getJSON(`/v1/notifications`);
}

/** Mark one notification read (drops it from the unseen badge on the next refetch). Mock is a no-op. */
export function markNotificationSeen(id: string): Promise<{ ok: boolean }> {
  if (MOCK) return Promise.resolve({ ok: true });
  return postJSON(`/v1/notifications/${encodeURIComponent(id)}/seen`, {});
}

// ── durable threads (per-user; requires auth in prod) ──────────────────────────────────────────────
export interface ThreadItem {
  id: string;
  title?: string;
  title_auto?: boolean;
  created_at?: string;
  updated_at?: string;
}

export function getThreadTurns(threadId: string): Promise<Schemas['ThreadTurns']> {
  if (MOCK) return import('./mock').then((m) => m.mockThreadTurns(threadId));
  return getJSON(`/v1/threads/${encodeURIComponent(threadId)}/turns`);
}

export function listThreads(): Promise<{ items: ThreadItem[] }> {
  if (MOCK) return import('./mock').then((m) => m.mockListThreads());
  return getJSON(`/v1/threads`);
}

/** Rename a thread. put_item overwrites the whole body, so resend everything the client knows; keep the
 *  EXISTING updated_at (a rename must not reorder the list) and set title_auto so the server's Haiku
 *  auto-title can never overwrite a user's rename. */
export function renameThread(item: ThreadItem, title: string): Promise<void> {
  if (MOCK) return Promise.resolve();
  const body = {
    title,
    title_auto: true,
    created_at: item.created_at,
    updated_at: item.updated_at ?? new Date().toISOString(),
  };
  return postJSON<{ id: string }>(`/v1/threads`, { id: item.id, body }).then(() => undefined);
}

/** Delete a thread (the server purges its durable turns first). */
export async function deleteThread(id: string): Promise<void> {
  if (MOCK) return;
  const path = `/v1/threads/${encodeURIComponent(id)}`;
  const res = await fetchWithAuth(`${BASE}${path}`, { method: 'DELETE' });
  if (!res.ok) throw await httpError(res, `DELETE ${path}`);
}
