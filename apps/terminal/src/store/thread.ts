import { create } from 'zustand';

/** A fresh, collision-resistant thread id. Used as the turn `session_id` so the backend carries multi-turn
 *  coreference memory AND appends each turn to this thread's durable history (pk=user, sk=turn#<id>#…). */
export function newThreadId(): string {
  const raw = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}${Math.random()}`;
  return `t-${raw.replace(/[^a-z0-9]/gi, '').slice(0, 20)}`;
}

/**
 * The active conversation thread (design §3.1). One thread = one `session_id`; a turn carries it so the
 * backend threads coreference ("it", "that contract") within the thread and persists the turn.
 *
 * A THREAD IS THE CONTEXT BOUNDARY (5.8, user decision): a new thread is a new session and carries NOTHING
 * from any other thread — so context can only ever cross turns you deliberately keep in the same thread.
 * This store is NOT persisted: every page load / visit starts a FRESH thread (module init picks a new id),
 * so opening the app is always a clean session. Past threads live server-side and re-open from the sidebar
 * via `openThread` (which re-loads their durable turns AND rebinds the backend session by id). Navigating
 * within the SPA does not reload the module, so a thread survives clicking around — only a real visit/reload
 * resets it. `newThread` starts a clean context on demand (the "+ new" button).
 */
export interface ThreadState {
  threadId: string;
  title: string | null; // thread label (server auto-titles via Haiku; fallback = first question)
  newThread: () => void;
  openThread: (id: string, title?: string | null) => void;
  setTitleIfEmpty: (t: string) => void;
}

export const useThread = create<ThreadState>()((set) => ({
  threadId: newThreadId(),
  title: null,
  newThread: () => set({ threadId: newThreadId(), title: null }),
  openThread: (id, title = null) => set({ threadId: id, title }),
  setTitleIfEmpty: (t) => set((s) => (s.title ? s : { title: t })),
}));
