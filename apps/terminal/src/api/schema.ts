/**
 * Hand-typed shapes for the STREAMING surface, which isn't in the backend OpenAPI: the SSE `stage` events
 * and the full `respond()` payload (the rich orchestrator dict — deliberately untyped server-side). Every
 * OTHER endpoint's types come from the generated `types.gen.ts` (design §6). Keep this in sync with
 * `orchestrator.respond` + `answer._emit` stage names.
 */

/** Granular pipeline stages emitted over SSE (server.py / answer._emit). `token` carries a synthesis delta
 *  (the note streaming token-by-token) rather than a pipeline milestone. The union stays open
 *  (`string & {}`) so a newer backend's stages never crash an older bundle. */
export type StageName =
  | 'accepted'
  | 'planning'
  | 'walking'
  | 'retrieving'
  | 'numbers'
  | 'synthesizing'
  | 'verifying'
  | 'floor'
  | 'token'
  | (string & {});

export interface StageEvent {
  stage: StageName;
  intent?: string;
  contracts?: string[];
  nodes?: number;
  regimes?: number;
  props?: number;
  calls?: number;
  checked?: number;
  stripped?: number;
  done?: number; // retrieving progress: nodes filled so far
  total?: number; // retrieving progress: eligible nodes
  running?: boolean; // numbers progress tick (vs the final completion event)
  table?: string; // numbers progress: the table just looked up
  text?: string; // stage === 'token': a synthesis delta (partial tool-input JSON)
}

export interface RespondTrace {
  graph_version?: string | null;
  degraded_model?: string;
  floor?: string;
  fired_regimes?: unknown[];
  [k: string]: unknown;
}

export interface RespondResult {
  answer: string;
  structured?: {
    tldr?: string;
    mechanism?: string;
    diagram_mermaid?: string;
    sources?: unknown[];
  } | null;
  contract?: string | null;
  contracts?: string[];
  citations?: unknown[];
  evidence?: unknown[];
  number_calls?: unknown[];
  intent?: string;
  model?: string;
  trace?: RespondTrace;
  asof?: string;
  [k: string]: unknown;
}
