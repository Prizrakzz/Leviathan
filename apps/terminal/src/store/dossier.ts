import type { DossierEvent, DossierState, DossierStatus, DossierSubquery } from '@/api/schema';

/**
 * D-DR-3 — the dossier job as the FE holds it, and the pure reduction of its stage stream.
 *
 * Deliberately a plain reducer over a plain shape (no store, no transport): the job is owned by the Shell
 * for exactly as long as it runs (api/useDossier), and everything durable about it lives in the frozen
 * ARTIFACT the server minted — not here. Keeping the reduction pure is what lets the SSE contract be tested
 * event-by-event without a socket, a timer or a component.
 *
 * THREE HONESTY RULES are baked in:
 *  1. The reducer never invents a row. `plan` carries the roster; a `subquery` event for an unplanned index
 *     APPENDS rather than being dropped (a plan event we missed must not silently erase work that ran), and
 *     the roster is never padded to `n` with blank titles we were not given.
 *  2. A terminal event never rewrites the sub-query rows. If the job ends `partial` with row 3 still shown
 *     as running, that is the truth of what the server told us; the surface labels it "no result reported"
 *     rather than the reducer marking it failed on a guess.
 *  3. `reached` is tracked separately from `status`, because a terminal status says the job is OVER without
 *     saying which stages it got to. A dossier that died in planning must not render three ticked stages.
 */

export type SubqueryStatus = 'pending' | 'running' | 'done' | 'failed';

export interface SubqueryRow {
  /** 1-indexed position in the plan. */
  i: number;
  title: string;
  status: SubqueryStatus;
}

/** How far the STREAM said it got. Monotonic. A plain const object rather than an enum: `isolatedModules`
 *  is on, and this is the cheapest shape that gives both the names and the ordering comparison. */
export const Reached = {
  Submitted: 0,
  Planned: 1,
  SubQueried: 2,
  Synthesizing: 3,
} as const;
export type Reached = (typeof Reached)[keyof typeof Reached];

export interface DossierJob {
  id: string;
  /** The question as submitted -- kept so a 429/failure can hand it back to the composer verbatim. */
  question: string;
  status: DossierStatus;
  /** The plan size the server declared (`n`), which can exceed `rows.length` before the plan lands. */
  planned: number;
  rows: SubqueryRow[];
  reached: Reached;
  /** Free-text stage label from the newest event, when it carried one. */
  stage?: string;
  artifactId?: string;
  error?: string;
}

/** A job the instant it is accepted: an id, the question, and nothing claimed about the plan yet. */
export function newDossierJob(id: string, question: string): DossierJob {
  return { id, question, status: 'planning', planned: 0, rows: [], reached: Reached.Submitted };
}

const ROW_STATUSES: readonly string[] = ['pending', 'running', 'done', 'failed'];

function rowStatus(v: unknown, fallback: SubqueryStatus): SubqueryStatus {
  return typeof v === 'string' && ROW_STATUSES.includes(v) ? (v as SubqueryStatus) : fallback;
}

function toRow(s: DossierSubquery, fallback: SubqueryStatus = 'pending'): SubqueryRow {
  return { i: s.i, title: s.title ?? '', status: rowStatus(s.status, fallback) };
}

/** Upsert one row by its 1-indexed position, preserving plan order. A title arriving empty on a later event
 *  does NOT blank the planned title -- the plan is where titles come from, the per-row events are progress. */
function upsert(rows: SubqueryRow[], next: SubqueryRow): SubqueryRow[] {
  const at = rows.findIndex((r) => r.i === next.i);
  if (at < 0) return [...rows, next].sort((a, b) => a.i - b.i);
  const prev = rows[at]!;
  const merged: SubqueryRow = { i: prev.i, title: next.title || prev.title, status: next.status };
  return rows.map((r, k) => (k === at ? merged : r));
}

/** The reduction. Unknown event types are IGNORED (a newer backend must never break an older bundle). */
export function reduceDossierEvent(job: DossierJob, e: DossierEvent): DossierJob {
  const stage = typeof e.stage === 'string' && e.stage ? e.stage : job.stage;
  const reach = (r: Reached): Reached => (Math.max(job.reached, r) as Reached);
  switch (e.type) {
    case 'plan': {
      const listed = Array.isArray(e.subqueries) ? e.subqueries : [];
      // The plan replaces the roster, but only when it HAS one: a bare `{type:'plan', n:6}` announces the
      // size and leaves the rows to the per-sub-query events.
      const rows = listed.length ? listed.map((s) => toRow(s)).sort((a, b) => a.i - b.i) : job.rows;
      const planned = typeof e.n === 'number' ? e.n : (listed[0]?.n ?? rows.length);
      return {
        ...job,
        status: 'running',
        stage,
        planned: Math.max(planned, rows.length),
        rows,
        reached: reach(Reached.Planned),
      };
    }
    case 'subquery': {
      if (typeof e.i !== 'number') return { ...job, stage };
      const rows = upsert(job.rows, toRow({ i: e.i, n: e.n ?? 0, title: e.title ?? '', status: e.status }, 'running'));
      const planned = Math.max(job.planned, typeof e.n === 'number' ? e.n : 0, rows.length);
      return { ...job, status: 'running', stage, planned, rows, reached: reach(Reached.SubQueried) };
    }
    case 'synthesis':
      return { ...job, status: 'synthesizing', stage, reached: reach(Reached.Synthesizing) };
    case 'done':
      return { ...job, status: 'done', stage, artifactId: e.artifact_id ?? job.artifactId };
    case 'partial':
      // A partial is a SUCCESS shape (D-DR-1 honest-partial): it still lands as an artifact, and the gap is
      // declared inside it. The `error` here is the gap note, not a failure sentence.
      return { ...job, status: 'partial', stage, artifactId: e.artifact_id ?? job.artifactId, error: e.error };
    case 'failed':
    case 'error':
      return { ...job, status: 'failed', stage, error: e.error ?? job.error ?? 'the dossier failed' };
    default:
      return { ...job, stage };
  }
}

/** Fold a POLLED state (GET /v1/dossier/{id}) onto the job -- the reconnect path, same shape, no stream. */
export function applyDossierState(job: DossierJob, s: DossierState): DossierJob {
  const listed = Array.isArray(s.subqueries) ? s.subqueries : [];
  const rows = listed.length ? listed.map((r) => toRow(r)).sort((a, b) => a.i - b.i) : job.rows;
  // The poll reports WHERE the job is, not which events it emitted, so `reached` is inferred conservatively
  // from what the state PROVES: a roster proves the plan landed, a row off `pending` proves a sub-query ran,
  // `synthesizing` proves the composition pass started.
  const inferred: Reached =
    s.status === 'synthesizing'
      ? Reached.Synthesizing
      : rows.some((r) => r.status !== 'pending')
        ? Reached.SubQueried
        : rows.length
          ? Reached.Planned
          : Reached.Submitted;
  return {
    ...job,
    status: s.status,
    stage: s.stage ?? job.stage,
    planned: Math.max(job.planned, listed[0]?.n ?? 0, rows.length),
    rows,
    reached: Math.max(job.reached, inferred) as Reached,
    artifactId: s.artifact_id ?? job.artifactId,
    error: s.error ?? job.error,
  };
}

/** Is the job over? The three terminal statuses -- `partial` included, because a partial dossier HAS landed. */
export function isTerminal(job: DossierJob): boolean {
  return job.status === 'done' || job.status === 'partial' || job.status === 'failed';
}

/** k of N, for the "sub-queries 3/6" line. `total` prefers the declared plan size over the rows in hand, so
 *  a roster still filling in never reads as "2 of 2". */
export function dossierProgress(job: DossierJob): { done: number; total: number } {
  return {
    done: job.rows.filter((r) => r.status === 'done').length,
    total: Math.max(job.planned, job.rows.length),
  };
}

// ── the three named stages ──────────────────────────────────────────────────────────────────────────
export type StageKey = 'plan' | 'subqueries' | 'synthesis';
export const STAGE_ORDER: readonly StageKey[] = ['plan', 'subqueries', 'synthesis'] as const;

/** `stopped` and `unreached` are the honest states a three-tick progress bar normally lacks: `stopped` is
 *  where a failed job died, `unreached` is everything after it. Without them a dossier that fell over in
 *  planning would render three ticks -- the D-DR-1 honest-partial doctrine applied to the progress card. */
export type StageMark = 'pending' | 'active' | 'done' | 'stopped' | 'unreached';

const RANK: Record<StageKey, number> = { plan: 1, subqueries: 2, synthesis: 3 };

/** The stage a live job is IN. Submission means planning is under way; a landed plan means the sub-queries
 *  are (whether or not the first one has reported); a synthesis event means the composition pass is. */
function frontier(job: DossierJob): number {
  return job.reached === Reached.Submitted ? RANK.plan : Math.max(job.reached, RANK.subqueries);
}

export function stageState(job: DossierJob, key: StageKey): StageMark {
  // An ARTIFACT is proof the whole pipeline ran, whatever the stream found time to announce: a `done` or
  // `partial` landing ticks every stage even when the synthesis event never reached this browser.
  if (job.status === 'done' || job.status === 'partial') return 'done';
  const r = RANK[key];
  const f = frontier(job);
  if (job.status === 'failed') return r < f ? 'done' : r === f ? 'stopped' : 'unreached';
  return r < f ? 'done' : r === f ? 'active' : 'pending';
}
