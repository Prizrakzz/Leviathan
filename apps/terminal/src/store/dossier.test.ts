import { describe, expect, it } from 'vitest';
import type { DossierEvent } from '@/api/schema';
import {
  applyDossierState,
  type DossierJob,
  dossierProgress,
  isTerminal,
  newDossierJob,
  reduceDossierEvent,
  STAGE_ORDER,
  stageState,
} from './dossier';

/** Fold a whole scripted stream, the way api/useDossier does. */
const run = (job: DossierJob, events: DossierEvent[]) => events.reduce(reduceDossierEvent, job);

const start = () => newDossierJob('d1', 'how tight is the corn balance?');

const PLAN: DossierEvent = {
  type: 'plan',
  subqueries: [
    { i: 1, n: 3, title: 'balance: stocks-to-use vs its own history' },
    { i: 2, n: 3, title: 'curve: what does the term structure price' },
    { i: 3, n: 3, title: 'episodes: dated windows that look like this' },
  ],
};

describe('reduceDossierEvent (D-DR-3 — the stage stream, reduced)', () => {
  it('a fresh job claims nothing about the plan', () => {
    const j = start();
    expect(j.status).toBe('planning');
    expect(j.rows).toEqual([]);
    expect(dossierProgress(j)).toEqual({ done: 0, total: 0 });
    expect(isTerminal(j)).toBe(false);
  });

  it('the plan event lands the roster, in order, all pending', () => {
    const j = reduceDossierEvent(start(), PLAN);
    expect(j.status).toBe('running');
    expect(j.rows.map((r) => r.i)).toEqual([1, 2, 3]);
    expect(j.rows.map((r) => r.status)).toEqual(['pending', 'pending', 'pending']);
    expect(j.rows[0]?.title).toContain('stocks-to-use');
    expect(dossierProgress(j)).toEqual({ done: 0, total: 3 });
  });

  it('sub-query events walk k/N without ever losing the planned titles', () => {
    let j = run(start(), [PLAN, { type: 'subquery', i: 1, n: 3, status: 'running' }]);
    expect(j.rows[0]?.status).toBe('running');
    expect(j.rows[0]?.title).toContain('stocks-to-use'); // an event with no title does NOT blank the plan's
    expect(dossierProgress(j)).toEqual({ done: 0, total: 3 });

    j = run(j, [
      { type: 'subquery', i: 1, n: 3, status: 'done' },
      { type: 'subquery', i: 2, n: 3, status: 'done' },
    ]);
    expect(dossierProgress(j)).toEqual({ done: 2, total: 3 });
  });

  it('a sub-query for an index the plan never mentioned is APPENDED, not dropped', () => {
    // A plan event we missed (reconnect, dropped block) must never erase work that actually ran.
    const j = run(start(), [{ type: 'subquery', i: 2, n: 4, title: 'positioning', status: 'running' }]);
    expect(j.rows.map((r) => r.i)).toEqual([2]);
    expect(j.planned).toBe(4); // the declared plan size still governs the k/N line
    expect(dossierProgress(j)).toEqual({ done: 0, total: 4 });
  });

  it('a bare plan event (size only) announces N and leaves the rows to the per-sub-query events', () => {
    const j = run(start(), [{ type: 'plan', n: 6 }]);
    expect(j.rows).toEqual([]); // never padded with blank titles we were not given
    expect(dossierProgress(j)).toEqual({ done: 0, total: 6 });
  });

  it('synthesis, then done with the artifact id', () => {
    const j = run(start(), [
      PLAN,
      { type: 'subquery', i: 1, n: 3, status: 'done' },
      { type: 'subquery', i: 2, n: 3, status: 'done' },
      { type: 'subquery', i: 3, n: 3, status: 'done' },
      { type: 'synthesis', stage: 'composing' },
      { type: 'done', artifact_id: 'art-9' },
    ]);
    expect(j.status).toBe('done');
    expect(j.artifactId).toBe('art-9');
    expect(isTerminal(j)).toBe(true);
    expect(dossierProgress(j)).toEqual({ done: 3, total: 3 });
  });

  it('a PARTIAL is a landing, not a failure: it still carries an artifact', () => {
    const j = run(start(), [
      PLAN,
      { type: 'subquery', i: 1, n: 3, status: 'done' },
      { type: 'subquery', i: 2, n: 3, status: 'failed' },
      { type: 'partial', artifact_id: 'art-partial', error: 'the curve leg returned no dated rows' },
    ]);
    expect(j.status).toBe('partial');
    expect(j.artifactId).toBe('art-partial');
    expect(j.error).toContain('curve leg');
    expect(isTerminal(j)).toBe(true);
  });

  it('a terminal event NEVER rewrites the rows — an unreported row stays as the server left it', () => {
    const j = run(start(), [
      PLAN,
      { type: 'subquery', i: 1, n: 3, status: 'done' },
      { type: 'subquery', i: 2, n: 3, status: 'running' },
      { type: 'partial', artifact_id: 'art-partial' },
    ]);
    // Row 2 is still `running` and row 3 still `pending`: the reducer does not mark them failed on a guess
    // (the surface labels them "no result reported", which is the true statement).
    expect(j.rows.map((r) => r.status)).toEqual(['done', 'running', 'pending']);
  });

  it('failed/error carry a sentence; an unknown type is ignored', () => {
    expect(run(start(), [{ type: 'failed', error: 'wall clock exceeded' }]).error).toBe('wall clock exceeded');
    expect(run(start(), [{ type: 'error' }]).status).toBe('failed');
    const j = run(start(), [PLAN, { type: 'quantum_leap', i: 99 } as DossierEvent]);
    expect(j.status).toBe('running'); // a newer backend's event must never break an older bundle
    expect(j.rows).toHaveLength(3);
  });

  it('a garbage row status falls back rather than landing on the store shape', () => {
    const j = run(start(), [{ type: 'subquery', i: 1, n: 1, title: 't', status: 'weird' }]);
    expect(j.rows[0]?.status).toBe('running');
  });
});

describe('applyDossierState (the reconnect path)', () => {
  it('folds a polled state onto the job', () => {
    const j = applyDossierState(start(), {
      status: 'partial',
      stage: 'synthesis',
      subqueries: [
        { i: 1, n: 2, title: 'a', status: 'done' },
        { i: 2, n: 2, title: 'b', status: 'failed' },
      ],
      artifact_id: 'art-7',
    });
    expect(j.status).toBe('partial');
    expect(j.stage).toBe('synthesis');
    expect(j.artifactId).toBe('art-7');
    expect(dossierProgress(j)).toEqual({ done: 1, total: 2 });
  });
});

describe('stageState (plan -> sub-queries -> synthesis)', () => {
  it('names all three stages, in order, always', () => {
    expect([...STAGE_ORDER]).toEqual(['plan', 'subqueries', 'synthesis']);
  });

  it('walks the three stages as the stream arrives', () => {
    const j0 = start();
    expect(STAGE_ORDER.map((k) => stageState(j0, k))).toEqual(['active', 'pending', 'pending']);

    const j1 = reduceDossierEvent(j0, PLAN);
    expect(STAGE_ORDER.map((k) => stageState(j1, k))).toEqual(['done', 'active', 'pending']);

    // A sub-query reporting in does NOT advance the frontier past the sub-query stage.
    const j1b = reduceDossierEvent(j1, { type: 'subquery', i: 1, n: 3, status: 'running' });
    expect(STAGE_ORDER.map((k) => stageState(j1b, k))).toEqual(['done', 'active', 'pending']);

    const j2 = reduceDossierEvent(j1b, { type: 'synthesis' });
    expect(STAGE_ORDER.map((k) => stageState(j2, k))).toEqual(['done', 'done', 'active']);

    const j3 = reduceDossierEvent(j2, { type: 'done', artifact_id: 'a' });
    expect(STAGE_ORDER.map((k) => stageState(j3, k))).toEqual(['done', 'done', 'done']);
  });

  it('a job that FAILED in planning ticks NOTHING — it stopped where it stopped', () => {
    const j = reduceDossierEvent(start(), { type: 'failed', error: 'planner unavailable' });
    expect(STAGE_ORDER.map((k) => stageState(j, k))).toEqual(['stopped', 'unreached', 'unreached']);
    expect(j.status).toBe('failed');
    expect(j.rows).toEqual([]);
  });

  it('a job that failed DURING the sub-queries keeps the plan ticked and stops there', () => {
    const j = run(start(), [
      PLAN,
      { type: 'subquery', i: 1, n: 3, status: 'done' },
      { type: 'failed', error: 'wall clock exceeded' },
    ]);
    expect(STAGE_ORDER.map((k) => stageState(j, k))).toEqual(['done', 'stopped', 'unreached']);
  });

  it('a landing ticks every stage even when the synthesis event never reached this browser', () => {
    // The ARTIFACT is the proof the pipeline ran; a dropped block in the middle of the stream must not
    // leave the card claiming the dossier we are looking at was never composed.
    const j = run(start(), [PLAN, { type: 'partial', artifact_id: 'art-1' }]);
    expect(STAGE_ORDER.map((k) => stageState(j, k))).toEqual(['done', 'done', 'done']);
  });
});
