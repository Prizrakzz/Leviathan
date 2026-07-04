import { MOCK_CONVERGENCE, MOCK_GRAPH, MOCK_REGIMES, MOCK_SERIES, mockRespondStream } from './mock';
import { openRespondStream, type StreamHandlers } from './sse';
import type { components } from './types.gen';

type Schemas = components['schemas'];

const BASE = import.meta.env.VITE_API_BASE ?? '';
const MOCK = import.meta.env.VITE_MOCK === '1';

/** Stream a turn. `VITE_MOCK=1` routes to the in-repo mock so the whole UI runs without the backend. */
export function respondStream(
  params: { question: string; asof?: string; sessionId?: string },
  h: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return MOCK ? mockRespondStream(params, h) : openRespondStream(BASE, params, h, signal);
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
  return (await res.json()) as T;
}

const q = (asof?: string) => (asof ? `?asof=${encodeURIComponent(asof)}` : '');

export function getConvergence(asof?: string): Promise<Schemas['ConvergenceMatrix']> {
  if (MOCK) return Promise.resolve(MOCK_CONVERGENCE);
  return getJSON(`/v1/convergence${q(asof)}`);
}

export function getGraph(contract: string, asof?: string): Promise<Schemas['GraphTopology']> {
  if (MOCK) return Promise.resolve(MOCK_GRAPH);
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
