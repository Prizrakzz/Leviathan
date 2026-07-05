import { useEffect, useRef, useState } from 'react';
import type { TurnStatus } from '@/api/useTurn';

/**
 * Smooth typewriter reveal (5.6 W5). SSE `token` deltas arrive as BURSTY tool-input-JSON chunks; rendering
 * them raw makes the note jump in slabs ("stuck… slab… stuck"). This hook keeps a reveal cursor over the
 * accumulating draft and advances it per animation frame at a rate proportional to the backlog —
 * steady ~2 chars/frame (~120 chars/s) when caught up, catching a burst up within ~0.5s. When the turn
 * completes it drains 5× faster and flips `settled`, which is what AnswerView waits for before swapping
 * to the final verified note (no abrupt draft→final jump).
 */
export function useTypewriter(draft: string, status: TurnStatus): { shown: string; settled: boolean } {
  const [shownLen, setShownLen] = useState(0);
  const [settled, setSettled] = useState(false);
  const raf = useRef<number | null>(null);
  const state = useRef({ draftLen: 0, done: false });
  state.current.draftLen = draft.length;
  state.current.done = status !== 'streaming';

  // A new turn (draft reset to empty) rewinds the cursor.
  useEffect(() => {
    if (draft.length === 0) {
      setShownLen(0);
      setSettled(false);
    }
  }, [draft.length === 0]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (status === 'idle') return;
    let cancelled = false;
    const tick = () => {
      if (cancelled) return;
      setShownLen((n) => {
        const backlog = state.current.draftLen - n;
        if (backlog <= 0) return n;
        const base = Math.max(2, Math.ceil(backlog / 30));
        return n + (state.current.done ? base * 5 : base);
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      if (raf.current != null) cancelAnimationFrame(raf.current);
    };
  }, [status]);

  // Settled = the turn is done AND the reveal has drained (or nothing was ever streamed).
  useEffect(() => {
    if (status === 'done' && shownLen >= draft.length) setSettled(true);
    if (status === 'error') setSettled(true);
  }, [status, shownLen, draft.length]);

  return { shown: draft.slice(0, Math.min(shownLen, draft.length)), settled };
}
