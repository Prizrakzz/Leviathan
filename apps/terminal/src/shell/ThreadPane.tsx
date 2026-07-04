import type { TurnState } from '@/api/useTurn';

/** The Thread — the conversation log (design §3.1). Phase 2 shows the single active turn; the virtualized
 *  multi-turn log with coreference carry lands in Phase 3. */
export function ThreadPane({ turn, question }: { turn: TurnState; question: string }) {
  const status =
    turn.status === 'streaming'
      ? 'streaming…'
      : turn.status === 'done'
        ? 'note ready'
        : turn.status === 'error'
          ? `error: ${turn.error ?? ''}`
          : '';
  return (
    <aside className="w-[360px] shrink-0 overflow-auto border-r border-line bg-bg-0 p-4">
      <div className="font-mono text-11 uppercase tracking-wider text-text-dim">thread</div>
      {question ? (
        <div className="mt-3">
          <div className="font-mono text-12 text-cyan">▸ {question}</div>
          <div className="mt-1 font-mono text-11 text-text-dim">{status}</div>
        </div>
      ) : (
        <div className="mt-3 font-sans text-12 text-text-faint">ask a question to start a thread.</div>
      )}
    </aside>
  );
}
