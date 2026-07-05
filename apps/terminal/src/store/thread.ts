import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/** A fresh, collision-resistant thread id. Used as the turn `session_id` so the backend carries multi-turn
 *  coreference memory AND appends each turn to this thread's durable history (pk=user, sk=turn#<id>#…). */
export function newThreadId(): string {
  const raw = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}${Math.random()}`;
  return `t-${raw.replace(/[^a-z0-9]/gi, '').slice(0, 20)}`;
}

/**
 * The active conversation thread (design §3.1). One thread = one `session_id`; a turn carries it so the
 * backend threads coreference ("it", "that contract") and persists the turn. `newThread` starts a clean
 * context; `openThread` switches to a saved one (its durable turns re-load from the backend). The active
 * thread persists across reloads (5.6 W3, localStorage `lv-thread`); a fresh interactive LOGIN starts a
 * new thread instead (App.tsx callback).
 */
export interface ThreadState {
  threadId: string;
  title: string | null; // thread label (server auto-titles via Haiku; fallback = first question)
  newThread: () => void;
  openThread: (id: string, title?: string | null) => void;
  setTitleIfEmpty: (t: string) => void;
}

export const useThread = create<ThreadState>()(
  persist(
    (set) => ({
      threadId: newThreadId(),
      title: null,
      newThread: () => set({ threadId: newThreadId(), title: null }),
      openThread: (id, title = null) => set({ threadId: id, title }),
      setTitleIfEmpty: (t) => set((s) => (s.title ? s : { title: t })),
    }),
    { name: 'lv-thread', partialize: (s) => ({ threadId: s.threadId, title: s.title }) },
  ),
);
