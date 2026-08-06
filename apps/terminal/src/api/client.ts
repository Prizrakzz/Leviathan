import { fetchWithAuth } from '../auth/oidc';
import { httpError } from './errors';
import { MOCK_SERIES, mockGraph, mockRespondStream } from './mock';
import type {
  ArtifactItem,
  ContextAttachment,
  FrozenSnapshot,
  GalleryItem,
  NotificationItem,
  PdfPage,
  RespondResult,
} from './schema';
import { openRespondStream, type StreamHandlers } from './sse';
import type { components } from './types.gen';

type Schemas = components['schemas'];

const BASE = import.meta.env.VITE_API_BASE ?? '';
const MOCK = import.meta.env.VITE_MOCK === '1';

/** The transport-independent shape of one turn request. D-AM-14 added `mode`: it is a FREE-FORM string
 *  here, not the client's `ModeName` union, because the backend never 4xxs an unknown mode (it resolves to
 *  standard and stamps invalid) and a typed field at this seam would turn a fail-open contract into a
 *  client-side error. The omit-when-standard rule is applied by the transport, via `store/mode.modeParam`. */
export interface RespondParams {
  question: string;
  asof?: string;
  sessionId?: string;
  context?: ContextAttachment[];
  mode?: string;
}

/** Stream a turn. `VITE_MOCK=1` routes to the in-repo mock so the whole UI runs without the backend. */
export function respondStream(
  params: RespondParams,
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
 *  `[N#]` label (D-TW-9). It is part of the query identity for the cache too; see Numbers.tsx's key.
 *
 *  D-AM-21: `contractMonth` + `agg` are the CURVE read. A comma-separated month list at `agg='latest'`
 *  returns one row per expiry at ONE as-of -- the term structure -- instead of the interleaved multi-expiry
 *  series a futures card returns with no month named. Both are OMITTED when absent, so an ordinary sparkline
 *  fetch sends the exact URL it sent before this wave. `asof` is the caller's OWN as-of either way: a curve
 *  is read at the same point in time as the row it hangs off, never at a fresher one. */
export function getSeries(
  table: string,
  metric: string,
  opts: { commodity?: string; country?: string; asof?: string; contractMonth?: string; agg?: string } = {},
): Promise<Schemas['Series']> {
  if (MOCK) return Promise.resolve(MOCK_SERIES);
  const p = new URLSearchParams();
  if (opts.commodity) p.set('commodity', opts.commodity);
  if (opts.country) p.set('country', opts.country);
  if (opts.asof) p.set('asof', opts.asof);
  if (opts.contractMonth) p.set('contract_month', opts.contractMonth);
  if (opts.agg) p.set('agg', opts.agg);
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

// ── D-AM-16 deterministic prompt gallery (the suggester's opposite number) ─────────────────────────
export type { GalleryItem };

/** Curated starters for the empty state. FREE and deterministic: the server fills authored templates from
 *  the already-warm convergence catalog, so there is no model call and no quota behind this — unlike
 *  `suggest`, which spends both and therefore has no business firing on a landing page where nothing has
 *  been asked yet. Entries with `filled: false` carry unresolved `{slot}` blanks (cold catalog) and are not
 *  one-click starters; the caller filters them. */
export function getGallery(): Promise<{ items: GalleryItem[] }> {
  if (MOCK) return import('./mock').then((m) => m.mockGallery());
  return getJSON(`/v1/gallery`);
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

// ── D-AM-15 research artifacts (PRIVATE per-user) + share links (PUBLIC read) ───────────────────────
// Two deliberately different products off one freeze. An artifact is the user's own saved copy — it rides
// the per-user collection factory, so it is identity-gated like threads. A share is a public permalink at
// /s/{id} (ratified: POST /v1/share stays as it is). Both freeze SERVER-side: the client posts the turn it
// holds and the server mints the snapshot, so a browser can never author a pin.
export type { ArtifactItem, FrozenSnapshot };

export function listArtifacts(): Promise<{ items: ArtifactItem[] }> {
  if (MOCK) return import('./mock').then((m) => m.mockListArtifacts());
  return getJSON(`/v1/artifacts`);
}

/** Freeze the turn the browser is holding into a named artifact. The whole RespondResult goes over the
 *  wire — the point of an artifact is that reopening it reproduces THIS answer, not a re-run of the
 *  question against a graph that has moved on. `question` is passed explicitly rather than read off the
 *  result: the streamed payload does not always carry it, and it is what both readers title themselves by. */
export function saveArtifact(name: string, question: string, result: RespondResult): Promise<{ id: string }> {
  const body = { name, question, asof: result.asof ?? null, payload: result };
  if (MOCK) return import('./mock').then((m) => m.mockSaveArtifact(body));
  return postJSON(`/v1/artifacts`, { body });
}

export async function deleteArtifact(id: string): Promise<void> {
  if (MOCK) return import('./mock').then((m) => m.mockDeleteArtifact(id));
  const path = `/v1/artifacts/${encodeURIComponent(id)}`;
  const res = await fetchWithAuth(`${BASE}${path}`, { method: 'DELETE' });
  if (!res.ok) throw await httpError(res, `DELETE ${path}`);
}

/** Mint a PUBLIC permalink for a turn. Returns the server's own `{id, url}` — `url` is already the `/s/{id}`
 *  path the reader route serves, so callers prefix the origin rather than rebuilding the path. */
export function createShare(question: string, result: RespondResult): Promise<Schemas['ShareRef']> {
  const body = { question, asof: result.asof ?? null, payload: result as unknown as Record<string, unknown> };
  if (MOCK) return import('./mock').then((m) => m.mockCreateShare(body));
  return postJSON(`/v1/share`, body);
}

/** Read a share snapshot. PUBLIC (server.py: no auth dependency) — this is the one call the /s/:id reader
 *  makes, and it must work for a signed-out visitor who followed a forwarded link. */
export function getShare(id: string): Promise<FrozenSnapshot> {
  if (MOCK) return import('./mock').then((m) => m.mockGetShare(id));
  return getJSON(`/v1/share/${encodeURIComponent(id)}`);
}
