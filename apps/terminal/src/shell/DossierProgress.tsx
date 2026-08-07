import type { DossierToast } from '@/api/useDossier';
import { utcDay } from '@/lib/time';
import {
  type DossierJob,
  dossierProgress,
  isTerminal,
  STAGE_ORDER,
  type StageKey,
  type StageMark,
  stageState,
  type SubqueryRow,
} from '@/store/dossier';
import { useUI } from '@/store/ui';

/**
 * D-DR-3 — the dossier job surface: a strip under the top bar, above the workspace.
 *
 * NOT a chat bubble, and not inside the conversation column, because a dossier is not a turn: it is a job
 * that outlives the question that started it, survives thread switches (the workspace is global), and lands
 * somewhere else entirely — a frozen artifact tab. Putting its progress in the transcript would promise that
 * the answer arrives there, which is exactly the wrong expectation to set for 5-20 minutes.
 *
 * HONEST STATES, in the D-DR-1 vocabulary:
 *  - `partial` is rendered as a LANDING, not a failure: the dossier exists, with its gaps declared inside it.
 *  - a row the server never reported on reads "no result reported" once the job is over — the reducer does
 *    not mark it failed on a guess (store/dossier), and neither does this.
 *  - the quota toast carries the reset DATE. A weekly allowance refused without a date is unactionable.
 */

const STAGE_LABEL: Record<StageKey, string> = {
  plan: 'plan',
  subqueries: 'sub-queries',
  synthesis: 'synthesis',
};

const MARK: Record<StageMark, string> = {
  pending: '·',
  active: '▸',
  done: '✓',
  stopped: '×', // where a failed job died
  unreached: '·', // everything after it -- rendered faint, never ticked
};

const MARK_CLASS: Record<StageMark, string> = {
  pending: 'text-text-faint',
  active: 'text-cyan',
  done: 'text-text-dim',
  stopped: 'text-neg',
  unreached: 'text-text-faint line-through',
};

/** What a row says, given the job it sits in. A running row in a FINISHED job never reported back. */
function rowLabel(row: SubqueryRow, job: DossierJob): string {
  if (row.status === 'done') return 'done';
  if (row.status === 'failed') return 'failed';
  if (isTerminal(job)) return 'no result reported';
  return row.status === 'running' ? 'running' : 'queued';
}

export function DossierProgress({
  job,
  toast,
  onDismiss,
  onDismissToast,
}: {
  job: DossierJob | null;
  toast: DossierToast | null;
  onDismiss: () => void;
  onDismissToast: () => void;
}) {
  if (!job && !toast) return null;

  return (
    <div className="shrink-0 border-b border-line bg-bg-0 px-4 py-2" data-testid="dossier-surface">
      {toast && <Toast toast={toast} onDismiss={onDismissToast} />}
      {job && <JobCard job={job} onDismiss={onDismiss} />}
    </div>
  );
}

/** Non-destructive: it reports, it does not take the question away (api/useDossier hands the words back to
 *  the composer on the same path that raises this). */
function Toast({ toast, onDismiss }: { toast: DossierToast; onDismiss: () => void }) {
  const day = utcDay(toast.resetAt);
  return (
    <div
      role="status"
      data-testid="dossier-toast"
      className={`mb-2 flex items-start gap-2 rounded-panel border px-2 py-1.5 font-mono text-11 ${
        toast.kind === 'quota' ? 'border-amber text-amber' : 'border-neg text-neg'
      }`}
    >
      <span className="min-w-0 flex-1">
        {toast.text}
        {toast.kind === 'quota' && day && (
          <span data-testid="dossier-toast-reset"> — resets {day} (UTC)</span>
        )}
        <span className="block text-text-faint">your question is still in the box</span>
      </span>
      <button
        aria-label="dismiss"
        onClick={onDismiss}
        className="shrink-0 rounded-chip border border-line px-1 text-text-dim hover:text-cyan"
      >
        ×
      </button>
    </div>
  );
}

function JobCard({ job, onDismiss }: { job: DossierJob; onDismiss: () => void }) {
  const { done, total } = dossierProgress(job);
  const landed = job.status === 'done' || job.status === 'partial';

  const focusArtifact = () => {
    if (!job.artifactId) return;
    // openTab is open-OR-FOCUS on a stable key, so this is the same call the landing made: it focuses the
    // tab that already exists rather than minting a second one.
    useUI.getState().openTab({
      kind: 'artifact',
      title: job.question.slice(0, 60) || 'dossier',
      params: { artifactId: job.artifactId },
    });
  };

  return (
    <div className="rounded-panel border border-line bg-bg-1 px-3 py-2" data-testid="dossier-progress">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-11 uppercase tracking-wider text-cyan">deep research</span>
        <span className="min-w-0 flex-1 truncate font-sans text-12 text-text" title={job.question}>
          {job.question}
        </span>
        <span className="shrink-0 font-mono text-11 text-text-faint" data-testid="dossier-status">
          {job.status}
        </span>
        <button
          aria-label="dismiss dossier progress"
          onClick={onDismiss}
          className="shrink-0 rounded-chip border border-line px-1 font-mono text-11 text-text-dim hover:text-cyan"
        >
          ×
        </button>
      </div>

      {/* plan -> sub-queries k/N -> synthesis. The three stages are ALWAYS all three, so the reader can see
          what has not happened yet as clearly as what has. */}
      <div className="mt-1 flex flex-wrap items-center gap-3 font-mono text-11" data-testid="dossier-stages">
        {STAGE_ORDER.map((k) => {
          const st = stageState(job, k);
          return (
            <span
              key={k}
              data-testid={`dossier-stage-${k}`}
              data-state={st}
              className={MARK_CLASS[st]}
            >
              {MARK[st]} {STAGE_LABEL[k]}
              {k === 'subqueries' && total > 0 ? ` ${done}/${total}` : ''}
            </span>
          );
        })}
      </div>

      {job.rows.length > 0 && (
        <ol className="mt-1.5 space-y-0.5" data-testid="dossier-subqueries">
          {job.rows.map((r) => (
            <li
              key={r.i}
              data-testid={`dossier-subquery-${r.i}`}
              className="flex items-baseline gap-2 font-sans text-11 leading-snug"
            >
              <span className="shrink-0 font-mono text-text-faint">{r.i}.</span>
              <span className={`min-w-0 flex-1 ${r.status === 'done' ? 'text-text-dim' : 'text-text-faint'}`}>
                {r.title || '(untitled sub-question)'}
              </span>
              <span className="shrink-0 font-mono text-text-faint">{rowLabel(r, job)}</span>
            </li>
          ))}
        </ol>
      )}

      {job.status === 'partial' && (
        <div className="mt-1.5 font-sans text-11 text-amber" data-testid="dossier-partial">
          partial dossier — {job.error || 'at least one sub-question came back empty'}; the gap is declared
          inside it.
        </div>
      )}
      {job.status === 'failed' && (
        <div className="mt-1.5 font-mono text-11 text-neg" data-testid="dossier-failed">
          {job.error || 'the dossier failed'}
        </div>
      )}

      {landed && (
        <div className="mt-1.5 flex items-center gap-2">
          <span className="font-sans text-11 text-text-faint">
            {job.artifactId ? 'saved as an artifact — opened in a tab' : 'the job finished without an artifact'}
          </span>
          {job.artifactId && (
            <button
              data-testid="dossier-open-tab"
              onClick={focusArtifact}
              className="rounded-chip border border-line px-2 py-0.5 font-mono text-11 text-cyan hover:bg-bg-2"
            >
              open in tab
            </button>
          )}
        </div>
      )}
    </div>
  );
}
