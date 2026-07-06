import { getIdToken } from '../auth/oidc';
import { MOCK_CONVERGENCE, MOCK_EVENTS, MOCK_REGIMES, MOCK_SERIES, mockGraph, mockRespondStream } from './mock';
import { openRespondStream, type StreamHandlers } from './sse';
import type { components } from './types.gen';

type Schemas = components['schemas'];

const BASE = import.meta.env.VITE_API_BASE ?? '';
const MOCK = import.meta.env.VITE_MOCK === '1';

/** Bearer header when signed in (Cognito ID token); empty when auth is off/unauthenticated. */
async function authHeaders(): Promise<Record<string, string>> {
  const token = await getIdToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Stream a turn. `VITE_MOCK=1` routes to the in-repo mock so the whole UI runs without the backend. */
export function respondStream(
  params: { question: string; asof?: string; sessionId?: string },
  h: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return MOCK ? mockRespondStream(params, h) : openRespondStream(BASE, params, h, signal);
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
  return (await res.json()) as T;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
  return (await res.json()) as T;
}

const q = (asof?: string) => (asof ? `?asof=${encodeURIComponent(asof)}` : '');

export function getConvergence(asof?: string): Promise<Schemas['ConvergenceMatrix']> {
  if (MOCK) return Promise.resolve(MOCK_CONVERGENCE);
  return getJSON(`/v1/convergence${q(asof)}`);
}

export function getGraph(contract: string, asof?: string): Promise<Schemas['GraphTopology']> {
  if (MOCK) return Promise.resolve(mockGraph(contract)); // per-contract mock so the DAG matches the answer
  return getJSON(`/v1/graph/${encodeURIComponent(contract)}${q(asof)}`);
}

export function getRegimes(contract: string, asof?: string): Promise<Schemas['ConvergenceRow']> {
  if (MOCK) return Promise.resolve(MOCK_REGIMES);
  return getJSON(`/v1/regimes/${encodeURIComponent(contract)}${q(asof)}`);
}

export function getSeries(
  table: string,
  metric: string,
  opts: { commodity?: string; asof?: string } = {},
): Promise<Schemas['Series']> {
  if (MOCK) return Promise.resolve(MOCK_SERIES);
  const p = new URLSearchParams();
  if (opts.commodity) p.set('commodity', opts.commodity);
  if (opts.asof) p.set('asof', opts.asof);
  const qs = p.toString();
  return getJSON(
    `/v1/series/${encodeURIComponent(table)}/${encodeURIComponent(metric)}${qs ? `?${qs}` : ''}`,
  );
}

export function getEvents(contract?: string, asof?: string): Promise<Schemas['EventsFeed']> {
  if (MOCK) return Promise.resolve(MOCK_EVENTS);
  const p = new URLSearchParams();
  if (contract) p.set('contract', contract);
  if (asof) p.set('asof', asof);
  const qs = p.toString();
  return getJSON(`/v1/events${qs ? `?${qs}` : ''}`);
}

// ── 6.2 query suggester (decoupled; fired once per completed turn / thread start) ──────────────────
export type SuggestPacket = Schemas['SuggestRequest'];

export function suggest(packet: SuggestPacket): Promise<Schemas['SuggestResponse']> {
  if (MOCK) return import('./mock').then((m) => m.mockSuggest(packet));
  return postJSON(`/v1/suggest`, packet);
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
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE', headers: await authHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status} on DELETE ${path}`);
}
