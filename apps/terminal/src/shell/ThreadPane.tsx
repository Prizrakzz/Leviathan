import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { getThreadTurns, listThreads } from '@/api/client';
import type { components } from '@/api/types.gen';
import type { TurnState } from '@/api/useTurn';
import { useThread } from '@/store/thread';

type TurnRecord = components['schemas']['TurnRecord'];

function turnSnippet(t: TurnRecord): string {
  const s = t.structured as { tldr?: string } | null;
  return (s?.tldr || t.answer || '').slice(0, 160);
}

/** The Thread (design §3.1) — the durable multi-turn conversation log for the active thread plus the live
 *  streaming turn, with a thread switcher and a new-thread control. Past turns re-load from the backend
 *  (GET /v1/threads/{id}/turns — PIT-safe conclusions only, never evidence). The turn's `session_id` is the
 *  thread id, so the backend carries coreference across turns. */
export function ThreadPane({ turn, question }: { turn: TurnState; question: string }) {
  const threadId = useThread((s) => s.threadId);
  const title = useThread((s) => s.title);
  const newThread = useThread((s) => s.newThread);
  const openThread = useThread((s) => s.openThread);
  const qc = useQueryClient();

  const turnsQ = useQuery({
    queryKey: ['thread-turns', threadId],
    queryFn: () => getThreadTurns(threadId),
    staleTime: 10_000,
  });
  const threadsQ = useQuery({ queryKey: ['threads'], queryFn: listThreads, staleTime: 30_000 });

  // The backend appends the turn as it completes -> refresh the durable log + the switcher.
  useEffect(() => {
    if (turn.status === 'done') {
      void qc.invalidateQueries({ queryKey: ['thread-turns', threadId] });
      void qc.invalidateQueries({ queryKey: ['threads'] });
    }
  }, [turn.status, threadId, qc]);

  const past = turnsQ.data?.turns ?? [];
  const others = (threadsQ.data?.items ?? []).filter((t) => t.id !== threadId);
  const lastPastQ = past.length ? past[past.length - 1]!.question : null;
  // Show the active turn while it streams/errors; once done, keep it only until the refetch pulls it into
  // `past` (matched by question) — avoids a flicker where the just-finished turn briefly disappears.
  const showActive =
    !!question &&
    (turn.status === 'streaming' || turn.status === 'error' || (turn.status === 'done' && lastPastQ !== question));
  const activeStatus =
    turn.status === 'streaming'
      ? 'streaming…'
      : turn.status === 'done'
        ? 'note ready'
        : turn.status === 'error'
          ? `error: ${turn.error ?? ''}`
          : '';

  return (
    <aside className="flex w-[360px] shrink-0 flex-col overflow-hidden border-r border-line bg-bg-0">
      <div className="flex items-center justify-between border-b border-line px-4 py-2">
        <div
          className="truncate font-mono text-11 uppercase tracking-wider text-text-dim"
          title={title ?? undefined}
        >
          {title || 'thread'}
        </div>
        <button
          className="shrink-0 rounded-chip border border-line px-1.5 font-mono text-11 text-cyan hover:bg-bg-1"
          onClick={() => newThread()}
          aria-label="new thread"
        >
          + new
        </button>
      </div>

      <div className="flex-1 space-y-2 overflow-auto p-4">
        {past.length === 0 && !question && (
          <div className="font-sans text-12 text-text-faint">ask a question to start a thread.</div>
        )}

        {past.map((t, i) => (
          <div key={i} className="border-b border-line pb-2" data-testid="past-turn">
            <div className="font-mono text-12 text-cyan">▸ {t.question}</div>
            {turnSnippet(t) && <div className="mt-1 font-sans text-12 text-text-dim">{turnSnippet(t)}</div>}
            {t.asof && <div className="mt-0.5 font-mono text-11 text-text-faint">as of {t.asof}</div>}
          </div>
        ))}

        {showActive && (
          <div>
            <div className="font-mono text-12 text-cyan">▸ {question}</div>
            <div className="mt-1 font-mono text-11 text-text-dim">{activeStatus}</div>
          </div>
        )}
      </div>

      {others.length > 0 && (
        <div className="border-t border-line p-2">
          <div className="mb-1 font-mono text-11 uppercase tracking-wider text-text-faint">threads</div>
          <div className="max-h-32 space-y-0.5 overflow-auto">
            {others.map((t) => (
              <button
                key={t.id}
                onClick={() => openThread(t.id, t.title ?? null)}
                className="block w-full truncate text-left font-mono text-11 text-text-dim hover:text-cyan"
              >
                {t.title || t.id}
              </button>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}
