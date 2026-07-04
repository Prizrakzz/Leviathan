import type { TurnState } from '@/api/useTurn';
import { Pipeline } from '@/shell/Pipeline';

/** Answer view (design §4.1) — Phase 2 renders the streamed pipeline + the note text + a stub integrity
 *  strip. The live cascade DAG, receipts drawer, and terminal sparklines are Phase 3. */
export function AnswerView({ turn }: { turn: TurnState }) {
  const done = turn.status === 'done';
  const r = turn.result;
  return (
    <div>
      {turn.status !== 'idle' && (
        <div className="mb-4 rounded-panel border border-line bg-bg-1 p-3">
          <Pipeline stages={turn.stages} done={done} />
        </div>
      )}

      {done && r && (
        <article className="max-w-3xl">
          <div className="whitespace-pre-wrap font-sans text-14 leading-relaxed text-text">{r.answer}</div>
          <div className="mt-4 border-t border-line pt-2 font-mono text-11 text-text-dim">
            INTEGRITY&nbsp; as-of<span className="text-pos">✓</span> · served-by {String(r.model ?? '?')} ·
            graph <span className="text-amber">{String(r.trace?.graph_version ?? '?')}</span>
          </div>
        </article>
      )}

      {turn.status === 'error' && (
        <div className="font-mono text-12 text-neg">error: {turn.error}</div>
      )}

      {turn.status === 'idle' && (
        <div className="font-mono text-12 text-text-faint">
          the cascade DAG, receipts, sparklines, and integrity strip render here — Phase 3.
        </div>
      )}
    </div>
  );
}
