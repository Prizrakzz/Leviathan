import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { deleteThread, listThreads, renameThread, type ThreadItem } from '@/api/client';
import type { TurnState } from '@/api/useTurn';
import { relTime } from '@/lib/time';
import { useSession } from '@/store/session';
import { useThread } from '@/store/thread';
import { useUI } from '@/store/ui';

/**
 * The thread sidebar (5.6 W2) — a full-height, ChatGPT-style list of the user's saved threads (newest
 * first, from GET /v1/threads; the server registers threads itself on every saved turn). Click opens a
 * thread (its durable turns render in the answer column); hover exposes rename (inline) and delete
 * (two-click confirm; the server purges the thread's turns). Replaces the old ThreadPane, whose past-turn
 * log moved into the answer column and whose thread list was a 128px afterthought strip.
 */
export function ThreadSidebar({ turn }: { turn: TurnState }) {
  const threadId = useThread((s) => s.threadId);
  const title = useThread((s) => s.title);
  const newThread = useThread((s) => s.newThread);
  const openThread = useThread((s) => s.openThread);
  const ready = useSession((s) => s.ready);
  const qc = useQueryClient();

  const threadsQ = useQuery({
    queryKey: ['threads'],
    queryFn: listThreads,
    enabled: ready,
    staleTime: 30_000,
  });

  // The backend appends the turn + registers/bumps the thread index as the turn completes.
  useEffect(() => {
    if (turn.status === 'done') {
      void qc.invalidateQueries({ queryKey: ['threads'] });
      void qc.invalidateQueries({ queryKey: ['thread-turns', threadId] });
    }
  }, [turn.status, threadId, qc]);

  const items = [...(threadsQ.data?.items ?? [])].sort((a, b) =>
    (b.updated_at ?? '').localeCompare(a.updated_at ?? ''),
  );
  const activeSaved = items.some((t) => t.id === threadId);

  const openIt = (t: ThreadItem) => {
    openThread(t.id, t.title ?? null);
    useUI.getState().setView('answer');
  };

  return (
    <aside className="flex w-[300px] shrink-0 flex-col overflow-hidden border-r border-line bg-bg-0">
      <div className="flex items-center justify-between border-b border-line px-4 py-2">
        <div className="font-mono text-11 uppercase tracking-wider text-text-dim">threads</div>
        <button
          className="shrink-0 rounded-chip border border-line px-1.5 font-mono text-11 text-cyan hover:bg-bg-1"
          onClick={() => {
            newThread();
            useUI.getState().setView('answer');
          }}
          aria-label="new thread"
        >
          + new
        </button>
      </div>

      <div className="flex-1 space-y-0.5 overflow-auto p-2" data-testid="thread-list">
        {!activeSaved && (
          <div className="rounded-panel border border-cyan/40 bg-bg-1 px-2 py-1.5">
            <div className="truncate font-sans text-12 text-text">{title || 'new thread'}</div>
            <div className="font-mono text-11 text-text-faint">
              {turn.status === 'streaming' ? 'streaming…' : 'unsaved — ask to start'}
            </div>
          </div>
        )}

        {items.map((t) => (
          <ThreadRow
            key={t.id}
            item={t}
            active={t.id === threadId}
            streaming={t.id === threadId && turn.status === 'streaming'}
            onOpen={() => openIt(t)}
            onDeleted={() => {
              if (t.id === threadId) newThread();
              void qc.invalidateQueries({ queryKey: ['threads'] });
            }}
            onRenamed={() => void qc.invalidateQueries({ queryKey: ['threads'] })}
          />
        ))}

        {ready && !threadsQ.isLoading && items.length === 0 && activeSaved === false && (
          <div className="px-2 py-1 font-sans text-12 text-text-faint">
            no saved threads yet — ask a question to start one.
          </div>
        )}
        {!ready && <div className="px-2 py-1 font-mono text-11 text-text-faint">signing in…</div>}
        {threadsQ.isError && (
          <div className="px-2 py-1 font-mono text-11 text-neg">couldn't load threads — retrying</div>
        )}
      </div>
    </aside>
  );
}

function ThreadRow({
  item,
  active,
  streaming,
  onOpen,
  onDeleted,
  onRenamed,
}: {
  item: ThreadItem;
  active: boolean;
  streaming: boolean;
  onOpen: () => void;
  onDeleted: () => void;
  onRenamed: () => void;
}) {
  const [mode, setMode] = useState<'idle' | 'renaming' | 'confirm-delete'>('idle');
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (mode === 'renaming') inputRef.current?.focus();
  }, [mode]);

  const rename = useMutation({
    mutationFn: (t: string) => renameThread(item, t),
    onSettled: () => {
      setMode('idle');
      onRenamed();
    },
  });
  const del = useMutation({
    mutationFn: () => deleteThread(item.id),
    onSettled: () => {
      setMode('idle');
      onDeleted();
    },
  });

  if (mode === 'renaming')
    return (
      <div className="rounded-panel bg-bg-1 px-2 py-1.5">
        <input
          ref={inputRef}
          defaultValue={item.title ?? ''}
          aria-label="rename thread"
          className="w-full rounded-chip border border-line bg-bg-0 px-1.5 py-0.5 font-sans text-12 text-text focus:border-cyan"
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              const v = e.currentTarget.value.trim();
              if (v) rename.mutate(v);
              else setMode('idle');
            }
            if (e.key === 'Escape') setMode('idle');
          }}
          onBlur={() => setMode('idle')}
        />
      </div>
    );

  return (
    <div
      className={`group flex items-center gap-1 rounded-panel px-2 py-1.5 hover:bg-bg-1 ${
        active ? 'border border-cyan/40 bg-bg-1' : 'border border-transparent'
      }`}
      data-testid="thread-row"
    >
      <button onClick={onOpen} className="min-w-0 flex-1 text-left" title={item.title ?? item.id}>
        <div className="truncate font-sans text-12 text-text">{item.title || item.id}</div>
        <div className="font-mono text-11 text-text-faint">
          {streaming ? 'streaming…' : relTime(item.updated_at)}
        </div>
      </button>
      {mode === 'confirm-delete' ? (
        <button
          aria-label="confirm delete"
          className="shrink-0 rounded-chip border border-neg px-1.5 font-mono text-11 text-neg"
          onClick={() => del.mutate()}
          onBlur={() => setMode('idle')}
        >
          sure?
        </button>
      ) : (
        <div className="hidden shrink-0 gap-1 group-hover:flex">
          <button
            aria-label="rename thread"
            className="rounded-chip border border-line px-1 font-mono text-11 text-text-dim hover:text-cyan"
            onClick={() => setMode('renaming')}
          >
            ✎
          </button>
          <button
            aria-label="delete thread"
            className="rounded-chip border border-line px-1 font-mono text-11 text-text-dim hover:text-neg"
            onClick={() => setMode('confirm-delete')}
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}
