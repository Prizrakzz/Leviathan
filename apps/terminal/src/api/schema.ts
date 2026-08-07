/**
 * Hand-typed shapes for the STREAMING surface, which isn't in the backend OpenAPI: the SSE `stage` events
 * and the full `respond()` payload (the rich orchestrator dict — deliberately untyped server-side). Every
 * OTHER endpoint's types come from the generated `types.gen.ts` (design §6). Keep this in sync with
 * `orchestrator.respond` + `answer._emit` stage names.
 */

import type { components } from './types.gen';

/** The resolved source-PDF pointer: a presigned URL (~900s), the 1-indexed `page` the cited passage was
 *  found on (`null` when it couldn't be localized — the modal opens at the top), the raw `kind`
 *  (pdf/html/txt), and the presign TTL. Mirrors the backend `CitationPdf` model. Lives here (a leaf
 *  schema module) so `mock.ts` can name it without importing `client.ts` (breaks the client↔mock cycle). */
export type PdfPage = components['schemas']['CitationPdf'];

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
  // F7 content-bearing partials (see `PartialStage` below) — listed here too because they ride the SAME
  // `event: stage` transport, so they land in the raw `stages[]` feed alongside the milestone ticks.
  | 'plan'
  | 'walk'
  | 'regime'
  | 'number'
  | 'chain'
  | 'evidence'
  | 'drafting'
  | 'verified'
  | (string & {});

/** The RAW wire shape of one `event: stage` block. Deliberately permissive and fully optional beyond
 *  `stage`: SSE JSON is untrusted input, and an older bundle must survive a newer server's fields. Do NOT
 *  read the F7 content fields off this type — run the event through `parsePartial()` (api/partials.ts),
 *  the ONE validating boundary, and read the narrowed `PartialStage` instead. */
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
  table?: string; // numbers progress: the table just looked up — ALSO the `number` partial's table
  text?: string; // stage === 'token': a synthesis delta (partial tool-input JSON)
  // ── F7 partial fields (wire-level, unvalidated) ────────────────────────────────────────────────────
  depth?: number; // 'walk'
  contract?: string; // 'regime'
  regime?: string; // 'regime'
  direction?: string; // 'regime'
  basis?: Record<string, { date?: string; source?: string }>; // 'regime'
  metric?: string; // 'number'
  value?: number | string; // 'number'
  unit?: string | null; // 'number'
  asof?: string; // 'number'
  chain_id?: string; // 'chain'
  hops?: string[]; // 'chain'
  node?: string; // 'evidence'
  kept?: number; // 'evidence'
  strips?: number; // 'verified'
}

/* ── F7 · the content-bearing partials ────────────────────────────────────────────────────────────────
 * Everything before synthesis (dispatch, the walk, the regime probes, the quantify seam) is finished and
 * correct LONG before the writer starts, and today it is invisible: time-to-first-substance is ~156s p95.
 * These kinds stream that engine output as it lands. They are sourced from DETERMINISTIC engine output —
 * never LLM prose — which is why they need no verifier reconciliation: an engine cannot fabricate its own
 * firing. Each kind is a strict member of the `PartialStage` discriminated union, so `switch (p.stage)`
 * narrows to exactly the fields that kind carries; unknown kinds are dropped by `parsePartial()` rather
 * than typed here (invariant 3: an older SPA WILL meet a newer server).
 */

/** Dispatch decided: the intent it routed to and the contracts in scope. */
export interface PlanStage {
  stage: 'plan';
  intent: string;
  contracts: string[];
}

/** The cascade walk's shape (how much graph the answer stands on). */
export interface WalkStage {
  stage: 'walk';
  nodes: number;
  depth: number;
}

/** The dated provenance of ONE driver behind a regime firing (`{driver: {date, source}}`). */
export interface RegimeBasis {
  date?: string;
  source?: string;
}

/** A regime fired, with the dated basis that fired it. */
export interface RegimeStage {
  stage: 'regime';
  contract: string;
  regime: string;
  direction: string;
  basis: Record<string, RegimeBasis>;
}

/** A number resolved at the quantify seam (observed value, never a model estimate). */
export interface NumberStage {
  stage: 'number';
  table: string;
  metric: string;
  value: number | string;
  unit: string | null;
  asof: string;
}

/** A transmission chain grounded end-to-end. */
export interface ChainStage {
  stage: 'chain';
  chain_id: string;
  hops: string[];
}

/** Evidence kept for one node after the ≤ as-of filter. */
export interface EvidenceStage {
  stage: 'evidence';
  node: string;
  kept: number;
}

/** Synthesis has started — the UI switches from the findings feed to prose. */
export interface DraftingStage {
  stage: 'drafting';
}

/** The verifier finished (`strips` unbacked citations removed). ONLY here may the UI activate citation
 *  handles: the streamed draft is PRE-verifier, so a handle rendered live during streaming could be
 *  stripped out from under the user (StripCount p50 1, p90 7, max 16). */
export interface VerifiedStage {
  stage: 'verified';
  strips: number;
}

export type PartialStage =
  | PlanStage
  | WalkStage
  | RegimeStage
  | NumberStage
  | ChainStage
  | EvidenceStage
  | DraftingStage
  | VerifiedStage;

/** The kinds this bundle understands. Anything else is an unknown kind → ignored (never rendered). */
export type PartialKind = PartialStage['stage'];

/** D-AM-9 — the reasoning-mode stamp, on EVERY turn (every lane, dark and honored alike).
 *  `requested` is what the user asked for (null when the field was absent), `honored` is what actually
 *  governed the turn, `invalid` is true iff a non-empty request named no known mode. The names are plain
 *  strings, NOT the client's `ModeName` union: a newer backend may honor a mode this bundle has never
 *  heard of, and that must render as itself rather than crash the reader (the SectionKind posture). */
export interface ModeDecision {
  requested?: string | null;
  honored?: string;
  invalid?: boolean;
}

/** D-AM-11 — the RESOLVED knob values a honored non-standard mode actually ran, as stamped on the trace.
 *  ABSENT on standard turns, on dark turns, and on the exempt lanes (live / numbers_only) even when a mode
 *  is honored — those consume no knob, so a stamp there would claim a depth that never ran. That absence
 *  is exactly what gates the "what ran" chip. Open-ended: a newer backend's extra knob renders as a row. */
export interface ModeKnobs {
  node_budget?: number;
  depth?: number;
  max_seeds?: number;
  k_by_depth?: number[];
  evidence_cap?: number;
  probe_cap?: number;
  fetch_k?: number;
  silver_cap?: number;
  scaffold_max_bullets?: number;
  scaffold_max_absence?: number;
  budget_scale?: number;
  xc_force?: boolean;
  [k: string]: unknown;
}

export interface RespondTrace {
  graph_version?: string | null;
  degraded_model?: string;
  floor?: string;
  fired_regimes?: unknown[];
  attachment_note?: string; // P2 resolver: a future-dated @event was PIT-withheld (rendered as a banner)
  mode_knobs?: ModeKnobs; // D-AM-11 — present ONLY when a non-standard mode ran a knob-consuming lane
  [k: string]: unknown;
}

/** P2 typed context attachments — the wire shape the GET `context` param carries (hand-typed: the SSE
 *  request isn't in the OpenAPI surface). The event variant deliberately omits driver_id/mechanism:
 *  the backend code-maps the driver from event_type and looks mechanisms up in the graph, IGNORING any
 *  client value (injection posture).
 *
 *  D-UX-4 `series` is a CHART LOCATOR: the ChartTabParams fields MINUS `axis` and `asof`. Both omissions
 *  are the design, not an oversight — `axis` is how this reader draws it (not what the next question is
 *  about), and carrying no `asof` is what makes attaching a chart STEERING instead of data injection: the
 *  backend re-reads the series under the NEXT turn's own as-of, so an old chart can never drag its
 *  vintage (or its numbers) into a new answer. No points ever ride this. */
export type ContextAttachment =
  | { type: 'node'; contract: string; driver_id: string }
  | { type: 'edge'; contract: string; source: string; target: string }
  | { type: 'event'; event_type: string; commodity: string; date?: string; summary?: string; country?: string }
  | {
      type: 'series';
      table: string;
      metric: string;
      commodity?: string;
      country?: string;
      contract_month?: string;
    };

/** P3 Track D — a daily-digest notification item (GET /v1/notifications). The typed `event_type`/
 *  `commodity`/`date`/`summary`/`country` fields are exactly the projection that becomes a P2 event chip
 *  on row-click; `label` + `query` drive the display + composer prefill. `driver_id` is carried but
 *  deliberately DOES NOT flow into the chip (the backend code-maps the driver from event_type, ignoring
 *  any client value — same injection posture as the P2 event attachment). */
export type NotificationItem = {
  notif_id: string;
  created_at: string;
  seen: boolean;
  event_type: string;
  commodity: string;
  date?: string;
  summary?: string;
  country?: string;
  label: string;
  query: string;
  driver_id?: string;
};

/** P9-C typed sections — a DERIVED view of `mechanism` (backend `_sectionize`, flag GRAPHRAG_ANSWER_V2).
 *  The kind union stays open (`string & {}`) so a newer backend's kind renders as prose in an older
 *  bundle instead of crashing it — the StageName posture. `heading` is clean display text (no `## `). */
export type SectionKind = 'mechanism' | 'record' | 'disagreement' | 'watch' | 'other' | (string & {});

export interface Section {
  kind: SectionKind;
  heading: string;
  body: string;
}

/** D-AM-15 — the immutable freeze behind BOTH a saved research artifact and a public share link: one
 *  server-side `store.make_share` snapshot either way, so the two can never pin different things. `payload`
 *  is the whole RespondResult the turn produced, which is what lets a reader reproduce the exact answer
 *  under its own `asof`/`graph_version` instead of re-deriving it against a graph that has since moved.
 *  Declared here (the leaf schema module) so `mock.ts` can name it without importing `client.ts`. */
export interface FrozenSnapshot {
  id: string;
  question: string;
  asof?: string | null;
  graph_version?: string | null;
  created_at: string;
  payload: RespondResult;
}

/** One row of the private artifacts collection (GET /v1/artifacts). Everything past `id` is optional on the
 *  wire on purpose: a half-written or older item must still render as a row the user can delete, never blank
 *  the sidebar (the ThreadItem posture). */
export interface ArtifactItem {
  id: string;
  name?: string;
  snapshot?: FrozenSnapshot;
  created_at?: string;
  updated_at?: string;
}

/** D-AM-16 — one curated starter from GET /v1/gallery. `question` is an AUTHORED template already filled
 *  server-side from the warm convergence catalog, which is what makes the landing page deterministic and
 *  free (no model call, no quota — the split from /v1/suggest). `filled: false` means the catalog was cold
 *  and `question` still carries its `{contract}`/`{regime}`/`{pair}` blanks: readable, but NOT a one-click
 *  starter, so the renderer drops those. `rc_target` is the response contract the wording selects — server
 *  provenance for the eval lane, carried on the wire rather than rendered. Declared here (the leaf schema
 *  module) so `mock.ts` can name it without importing `client.ts`. */
export interface GalleryItem {
  id: string;
  category: string;
  question: string;
  rc_target?: string;
  filled?: boolean;
  /** D-UX-1 — the RAW authored wording, braces intact, and the values this row was filled with.
   *  `fillTemplate(template, slots) === question` server-side (pinned), which is what lets the template
   *  library re-fill the SAME sentence under an analyst's slot edit instead of composing a different one.
   *  Optional because the FE ships independently of the server image: an older backend omits both, and the
   *  library falls back to treating `question` as the template (a starter with no editable blanks). */
  template?: string;
  slots?: Record<string, string>;
}

/** D-UX-1 — the raw slot vocabularies behind the filled examples: the options each slot's combobox offers.
 *  `pairs` is the census-realizable set only (the same gate that fences the {pair} templates), and all three
 *  are empty on a cold catalog — an empty dropdown that still takes free typing, never an error. */
export interface GalleryVocab {
  contracts: string[];
  regimes: string[];
  pairs: string[];
}

export interface GalleryResponse {
  items: GalleryItem[];
  catalog_warm?: boolean;
  vocab?: GalleryVocab;
}

export interface RespondResult {
  answer: string;
  structured?: {
    tldr?: string;
    mechanism?: string;
    diagram_mermaid?: string;
    sources?: unknown[];
    sections?: Section[];
  } | null;
  contract?: string | null;
  contracts?: string[];
  citations?: unknown[];
  evidence?: unknown[];
  number_calls?: unknown[];
  intent?: string;
  model?: string;
  trace?: RespondTrace;
  /** The router's own decision record. D-AM-9 hangs the mode stamp off it on every turn; the rest of the
   *  dict (intent, response_contract, guardrail, …) stays untyped — this bundle reads only `mode`. */
  intent_decision?: { mode?: ModeDecision; [k: string]: unknown };
  asof?: string;
  [k: string]: unknown;
}

// ── D-DR — the deep-research dossier (a JOB, not a turn) ────────────────────────────────────────────
// Hand-typed for the same reason the streaming surface above is: the dossier's SSE events are not in the
// backend OpenAPI. Declared here (the leaf schema module) so both the transport (api/dossier.ts) and the
// pure reducer (store/dossier.ts) can name them without importing each other.

/** The job's lifecycle, as GET /v1/dossier/{id} reports it. `partial` is a FIRST-CLASS success shape, not a
 *  failure: a sub-query that fell over yields a dossier with the gap declared (D-DR-1 honest-partial), and
 *  it still lands as a frozen artifact. The union stays open so a newer backend's status never crashes an
 *  older bundle. */
export type DossierStatus =
  | 'planning'
  | 'running'
  | 'synthesizing'
  | 'done'
  | 'partial'
  | 'failed'
  | (string & {});

/** One planned sub-question. `i` is 1-indexed and `n` is the plan size, so a row states its own k-of-N
 *  without the reader having to hold the list. */
export interface DossierSubquery {
  i: number;
  n: number;
  title: string;
  status?: 'pending' | 'running' | 'done' | 'failed' | (string & {});
}

/** GET /v1/dossier/{id} — the poll shape (also what a reconnect reads back). */
export interface DossierState {
  status: DossierStatus;
  stage?: string;
  subqueries?: DossierSubquery[];
  artifact_id?: string;
  error?: string;
}

/** GET /v1/dossier/{id}/events — one stage event. The FE dispatches on `type` (not on the SSE `event:`
 *  name) because the locked contract puts the discriminator in the payload; the reducer treats every field
 *  besides `type` as optional, so a backend that enriches an event later cannot break an older bundle. */
export interface DossierEvent {
  type: 'plan' | 'subquery' | 'synthesis' | 'done' | 'partial' | 'failed' | 'error' | (string & {});
  stage?: string;
  /** `plan` carries the whole roster; `subquery` carries one row's worth of the same fields. */
  subqueries?: DossierSubquery[];
  i?: number;
  n?: number;
  title?: string;
  status?: string;
  /** The terminal event's payload: the frozen artifact this dossier landed as. */
  artifact_id?: string;
  error?: string;
}

/** GET /v1/dossier/quota — 3 per user per UTC week (D-DR-2). `reset_at` is an ISO instant. */
export interface DossierQuota {
  remaining: number;
  limit: number;
  reset_at?: string;
}

/** POST /v1/dossier — 202. The plan does not exist yet; the SSE stream delivers it. */
export interface DossierAccepted {
  dossier_id: string;
  plan_pending?: boolean;
}
