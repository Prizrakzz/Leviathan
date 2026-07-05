import type { RespondResult } from '@/api/schema';

export interface Integrity {
  verified: number;
  stripped: number;
  lookedUp: number;
  requested: number;
  notYetPub: number;
  model: string;
  graphVersion: string;
  degraded?: string;
  floor?: string;
}

/** Compute the answer-integrity readout (design §4.6) from the turn's trace + number statuses. Pure. */
export function computeIntegrity(r: RespondResult): Integrity {
  const trace = (r.trace ?? {}) as {
    citation_verifier?: { checked?: number; stripped?: number };
    graph_version?: string;
    degraded_model?: string;
    floor?: string;
  };
  const cv = trace.citation_verifier;
  const calls = (r.number_calls ?? []) as { status?: string }[];
  const notYetPub = calls.filter((c) => c.status === 'not_yet_pub').length;
  return {
    verified: cv?.checked ?? 0,
    stripped: cv?.stripped ?? 0,
    lookedUp: calls.length - notYetPub,
    requested: calls.length,
    notYetPub,
    model: String(r.model ?? '?'),
    graphVersion: String(trace.graph_version ?? '?'),
    degraded: trace.degraded_model,
    floor: trace.floor,
  };
}
