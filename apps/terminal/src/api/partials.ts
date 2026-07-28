/**
 * F7 — the validating boundary between the RAW SSE wire event (`StageEvent`, permissive by design) and the
 * STRUCTURED findings state the UI renders (`Findings`). Two pure halves, both React-free so both unit-test
 * without a DOM:
 *
 *   parsePartial(e)      unknown wire event -> a narrowed `PartialStage`, or NULL for an unknown/malformed
 *                        kind. This is invariant 3 in one function: an older SPA meets a newer server, does
 *                        not recognise the kind, and drops it — no throw, no junk row.
 *   reduceFindings(f, p) fold one partial into the accumulated findings. Upserts by identity key (a
 *                        re-emitted regime updates its row in place instead of duplicating it), returns the
 *                        SAME object when nothing changed (no wasted render), and advances `phase`
 *                        MONOTONICALLY so a late partial can never drag the UI back out of `drafting`.
 *
 * Nothing here is LLM prose: every field is deterministic engine output (slugs, table names, numbers,
 * dates), which is why it needs no verifier reconciliation and can be rendered the instant it lands.
 */

import type { PartialStage, RegimeBasis } from './schema';

// ── wire validation ────────────────────────────────────────────────────────────────────────────────
const isStr = (v: unknown): v is string => typeof v === 'string';
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const str = (v: unknown, fallback = ''): string => (isStr(v) ? v : fallback);
const num = (v: unknown, fallback = 0): number => (isNum(v) ? v : fallback);
const strArr = (v: unknown): string[] => (Array.isArray(v) ? v.filter(isStr) : []);

/** `{driver: {date, source}}` — only string-valued date/source survive; anything else is dropped. */
function parseBasis(v: unknown): Record<string, RegimeBasis> {
  const out: Record<string, RegimeBasis> = {};
  if (!v || typeof v !== 'object' || Array.isArray(v)) return out;
  for (const [driver, raw] of Object.entries(v as Record<string, unknown>)) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
      out[driver] = {};
      continue;
    }
    const b = raw as Record<string, unknown>;
    const entry: RegimeBasis = {};
    if (isStr(b.date)) entry.date = b.date;
    if (isStr(b.source)) entry.source = b.source;
    out[driver] = entry;
  }
  return out;
}

/**
 * Narrow one wire event to a content-bearing partial, or NULL.
 *
 * NULL means "ignore this event": an unknown kind (a newer server), a milestone tick (`planning`/`token`/…
 * — those keep their own path), or a known kind whose REQUIRED fields are missing/mistyped. Dropping a
 * malformed event is deliberate: a half-populated finding row is worse than no row, and this surface is
 * provenance the analyst is asked to trust.
 */
export function parsePartial(e: unknown): PartialStage | null {
  if (!e || typeof e !== 'object' || Array.isArray(e)) return null;
  const w = e as Record<string, unknown>;
  switch (w.stage) {
    case 'plan':
      if (!isStr(w.intent)) return null;
      return { stage: 'plan', intent: w.intent, contracts: strArr(w.contracts) };
    case 'walk':
      if (!isNum(w.nodes)) return null;
      return { stage: 'walk', nodes: w.nodes, depth: num(w.depth) };
    case 'regime':
      if (!isStr(w.contract) || !isStr(w.regime)) return null;
      return {
        stage: 'regime',
        contract: w.contract,
        regime: w.regime,
        direction: str(w.direction),
        basis: parseBasis(w.basis),
      };
    case 'number':
      if (!isStr(w.table) || !isStr(w.metric)) return null;
      // A resolved number, or nothing: `0` is a value, `''` is a lookup that did not resolve, and a row
      // that renders a metric with no number beside it is exactly the junk invariant 3 forbids.
      if (!isNum(w.value) && (!isStr(w.value) || w.value.trim() === '')) return null;
      return {
        stage: 'number',
        table: w.table,
        metric: w.metric,
        value: w.value,
        unit: isStr(w.unit) ? w.unit : null,
        asof: str(w.asof),
      };
    case 'chain':
      if (!isStr(w.chain_id)) return null;
      return { stage: 'chain', chain_id: w.chain_id, hops: strArr(w.hops) };
    case 'evidence':
      if (!isStr(w.node)) return null;
      return { stage: 'evidence', node: w.node, kept: num(w.kept) };
    case 'drafting':
      return { stage: 'drafting' };
    case 'verified':
      return { stage: 'verified', strips: num(w.strips) };
    default:
      return null; // unknown kind (or a milestone tick) -> ignored, never rendered
  }
}

// ── accumulated findings ───────────────────────────────────────────────────────────────────────────
/** Where the turn is. Monotonic: `idle -> planning -> walking -> drafting -> verified`, never backwards. */
export type TurnPhase = 'idle' | 'planning' | 'walking' | 'drafting' | 'verified';

const PHASE_RANK: Record<TurnPhase, number> = { idle: 0, planning: 1, walking: 2, drafting: 3, verified: 4 };

/** `to` only if it is strictly later than `from` — a straggler regime after `drafting` keeps the phase. */
function advance(from: TurnPhase, to: TurnPhase): TurnPhase {
  return PHASE_RANK[to] > PHASE_RANK[from] ? to : from;
}

/** Every finding carries a stable `key` (identity, for upsert) and `seq` (arrival order, for React keys +
 *  the enter animation — an upserted row keeps its original seq so it does not re-animate). */
interface Stamped {
  key: string;
  seq: number;
}

export interface PlanFinding extends Stamped {
  intent: string;
  contracts: string[];
}
export interface WalkFinding extends Stamped {
  nodes: number;
  depth: number;
}
export interface RegimeFinding extends Stamped {
  contract: string;
  regime: string;
  direction: string;
  basis: { driver: string; date?: string; source?: string }[];
}
export interface NumberFinding extends Stamped {
  table: string;
  metric: string;
  value: number | string;
  unit: string | null;
  asof: string;
}
export interface ChainFinding extends Stamped {
  chain_id: string;
  hops: string[];
}
export interface EvidenceFinding extends Stamped {
  node: string;
  kept: number;
}

export interface Findings {
  phase: TurnPhase;
  plan: PlanFinding | null;
  walk: WalkFinding | null;
  regimes: RegimeFinding[];
  numbers: NumberFinding[];
  chains: ChainFinding[];
  evidence: EvidenceFinding[];
  /** Total props kept across every `evidence` partial seen (the feed's one aggregate). */
  keptTotal: number;
  /** Unbacked citations the verifier removed; null until `verified` lands. */
  strips: number | null;
  /**
   * THE anti-half-measure flag. The streamed draft is PRE-verifier, so a `[N]` handle rendered as a live,
   * clickable citation during streaming can be stripped out from under the user. Handles stay INERT while
   * this is false and are activated only on `verified` / the terminal `result` — so nothing a user could
   * click ever disappears.
   */
  citationsLive: boolean;
  /** Monotonic arrival counter across all finding lists. */
  seq: number;
}

export const EMPTY_FINDINGS: Findings = {
  phase: 'idle',
  plan: null,
  walk: null,
  regimes: [],
  numbers: [],
  chains: [],
  evidence: [],
  keptTotal: 0,
  strips: null,
  citationsLive: false,
  seq: 0,
};

/** True once ANY partial has landed — the whole F7 surface is gated on this, so a server that emits none
 *  (an older deployment) renders EXACTLY as before. */
export function hasFindings(f: Partial<Findings> | null | undefined): boolean {
  if (!f) return false;
  return (
    (f.phase != null && f.phase !== 'idle') ||
    f.plan != null ||
    f.walk != null ||
    !!f.regimes?.length ||
    !!f.numbers?.length ||
    !!f.chains?.length ||
    !!f.evidence?.length
  );
}

/** Shallow value-equality over a finding, ignoring `seq` (identity fields already matched via `key`). */
function same(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)].filter((k) => k !== 'seq'));
  for (const k of keys) {
    const x = a[k];
    const y = b[k];
    if (Array.isArray(x) && Array.isArray(y)) {
      if (x.length !== y.length) return false;
      for (let i = 0; i < x.length; i++) {
        const xi = x[i];
        const yi = y[i];
        if (typeof xi === 'object' && xi && typeof yi === 'object' && yi) {
          if (!same(xi as Record<string, unknown>, yi as Record<string, unknown>)) return false;
        } else if (xi !== yi) return false;
      }
      continue;
    }
    if (x !== y) return false;
  }
  return true;
}

/** Append, or replace in place when the key is already present. Returns the SAME array on a no-op re-emit. */
function upsert<T extends Stamped>(list: T[], item: T): T[] {
  const at = list.findIndex((x) => x.key === item.key);
  if (at < 0) return [...list, item];
  const prev = list[at] as T;
  if (same(prev as unknown as Record<string, unknown>, item as unknown as Record<string, unknown>)) return list;
  const next = list.slice();
  next[at] = { ...item, seq: prev.seq }; // keep the original arrival slot: no re-animation, no reorder
  return next;
}

/**
 * Fold one partial into the findings. Generic over the carrier so a caller (useTurn) can keep its own
 * fields alongside: the returned object is the carrier with the findings fields replaced.
 *
 * Returns `f` UNCHANGED (same reference) when the event moves nothing — an identical re-emit costs no
 * render.
 */
export function reduceFindings<T extends Findings>(f: T, p: PartialStage): T {
  const seq = f.seq + 1;
  switch (p.stage) {
    case 'plan': {
      const plan: PlanFinding = { key: 'plan', seq: f.plan?.seq ?? seq, intent: p.intent, contracts: p.contracts };
      const phase = advance(f.phase, 'planning');
      if (f.plan && same(f.plan as unknown as Record<string, unknown>, plan as unknown as Record<string, unknown>) && phase === f.phase)
        return f;
      return { ...f, phase, plan, seq: f.plan ? f.seq : seq };
    }
    case 'walk': {
      const walk: WalkFinding = { key: 'walk', seq: f.walk?.seq ?? seq, nodes: p.nodes, depth: p.depth };
      const phase = advance(f.phase, 'walking');
      if (f.walk && same(f.walk as unknown as Record<string, unknown>, walk as unknown as Record<string, unknown>) && phase === f.phase)
        return f;
      return { ...f, phase, walk, seq: f.walk ? f.seq : seq };
    }
    case 'regime': {
      const item: RegimeFinding = {
        key: `${p.contract}|${p.regime}`,
        seq,
        contract: p.contract,
        regime: p.regime,
        direction: p.direction,
        basis: Object.entries(p.basis).map(([driver, b]) => ({ driver, ...b })),
      };
      const regimes = upsert(f.regimes, item);
      if (regimes === f.regimes) return f;
      return { ...f, regimes, seq };
    }
    case 'number': {
      const item: NumberFinding = {
        // The pinned `number` contract carries NO disambiguator — commodity/country/period stay in the note
        // — so two lookups off the SAME table+metric+vintage are told apart ONLY by their value. That is
        // not an edge case: one WASDE release answers corn AND wheat ending stocks (and two marketing
        // years) at one knowledge_date, and a cross-commodity turn asks for exactly that. Without `value`
        // in the key the second finding silently REPLACED the first. Two rows agreeing on all five fields
        // render identically, so collapsing THOSE is still right.
        key: `${p.table}|${p.metric}|${p.asof}|${p.value}`,
        seq,
        table: p.table,
        metric: p.metric,
        value: p.value,
        unit: p.unit,
        asof: p.asof,
      };
      const numbers = upsert(f.numbers, item);
      if (numbers === f.numbers) return f;
      return { ...f, numbers, seq };
    }
    case 'chain': {
      const item: ChainFinding = { key: p.chain_id, seq, chain_id: p.chain_id, hops: p.hops };
      const chains = upsert(f.chains, item);
      if (chains === f.chains) return f;
      return { ...f, chains, seq };
    }
    case 'evidence': {
      const item: EvidenceFinding = { key: p.node, seq, node: p.node, kept: p.kept };
      const evidence = upsert(f.evidence, item);
      if (evidence === f.evidence) return f;
      // keptTotal is recomputed (not summed) so a re-emitted node corrects the aggregate instead of
      // double-counting it.
      return { ...f, evidence, keptTotal: evidence.reduce((n, x) => n + x.kept, 0), seq };
    }
    case 'drafting': {
      const phase = advance(f.phase, 'drafting');
      return phase === f.phase ? f : { ...f, phase };
    }
    case 'verified': {
      const phase = advance(f.phase, 'verified');
      if (phase === f.phase && f.strips === p.strips && f.citationsLive) return f;
      // The one place citation handles are allowed to go live mid-stream.
      return { ...f, phase, strips: p.strips, citationsLive: true };
    }
  }
}

/**
 * The terminal `result` landed. Citations go live here too: a server that never emits `verified` (an older
 * deployment, or a turn whose verifier is skipped) must still end with clickable, resolved citations —
 * activation is "verified OR result", never "verified only".
 */
export function finalizeFindings<T extends Findings>(f: T): T {
  const phase = f.phase === 'idle' ? f.phase : advance(f.phase, 'verified');
  if (f.citationsLive && phase === f.phase) return f;
  return { ...f, phase, citationsLive: true };
}
