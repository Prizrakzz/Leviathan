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

// Max time the note waits on the reveal before force-settling — matches the rAF 5× drain budget, so the
// visible-tab animation always finishes first and this only fires when rAF is paused (S2.1 fix).
const DRAIN_MS = 800;

export function useTypewriter(draft: string, status: TurnStatus): { shown: string; settled: boolean } {
  const [shownLen, setShownLen] = useState(0);
  const [settled, setSettled] = useState(false);
  const raf = useRef<number | null>(null);
  const shownRef = useRef(0); // authoritative cursor; state mirrors it for rendering
  const state = useRef({ draftLen: 0, done: false });
  state.current.draftLen = draft.length;
  state.current.done = status !== 'streaming';

  // A new turn (draft reset to empty) rewinds the cursor.
  useEffect(() => {
    if (draft.length === 0) {
      shownRef.current = 0;
      setShownLen(0);
      setSettled(false);
    }
  }, [draft.length === 0]); // eslint-disable-line react-hooks/exhaustive-deps

  // Also rewind whenever the turn ENTERS streaming — `status` flips to 'streaming' once per turn, so this
  // resets a stale `settled` even across two back-to-back token-less turns where the draft never left ''
  // (the `draft.length===0` dep above wouldn't toggle) (S2.1 review).
  useEffect(() => {
    if (status === 'streaming') {
      shownRef.current = 0;
      setShownLen(0);
      setSettled(false);
    }
  }, [status]);

  useEffect(() => {
    if (status === 'idle') return;
    let cancelled = false;
    const tick = () => {
      if (cancelled) return;
      const backlog = state.current.draftLen - shownRef.current;
      if (backlog <= 0) {
        // Caught up. While streaming, keep polling (more tokens may arrive). Once the turn is DONE and
        // fully revealed, STOP scheduling — otherwise the rAF spins a no-op setState forever (audit 5.7).
        if (state.current.done) return;
      } else {
        const base = Math.max(2, Math.ceil(backlog / 30));
        shownRef.current = Math.min(
          shownRef.current + (state.current.done ? base * 5 : base),
          state.current.draftLen,
        );
        setShownLen(shownRef.current);
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      if (raf.current != null) cancelAnimationFrame(raf.current);
    };
  }, [status]);

  // Visibility-independent settle FLOOR (S2.1). `requestAnimationFrame` is PAUSED in a backgrounded/hidden
  // tab, so the reveal loop above can never flip `settled` there — and AnswerView gates the ENTIRE answer
  // (Note + causal map + Numbers) on `settled`, so during the ~26–60s turn a user who looks away returns to
  // a completed pipeline and an empty answer body: the "streams, then blacks out on finish" bug. When the
  // turn ends, force-complete the reveal within DRAIN_MS regardless of rAF; if the tab is already hidden,
  // settle immediately (no point animating an invisible tab). The rAF 5× drain still wins first when the tab
  // is visible, so the smooth reveal is unchanged.
  useEffect(() => {
    if (status === 'idle' || status === 'streaming') return;
    const finish = () => {
      shownRef.current = state.current.draftLen;
      setShownLen(state.current.draftLen);
      setSettled(true);
    };
    // No document (SSR/test env) or the tab is already hidden → settle at once (nothing to animate).
    if (typeof document === 'undefined' || status === 'error' || document.hidden) {
      finish();
      return;
    }
    const timer = setTimeout(finish, DRAIN_MS);
    // If the tab is backgrounded WHILE draining, settle at once so a later refocus shows a complete note.
    const onHide = () => {
      if (document.hidden) finish();
    };
    document.addEventListener('visibilitychange', onHide);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', onHide);
    };
  }, [status]);

  // Settled = the turn is done AND the reveal has drained (or nothing was ever streamed).
  useEffect(() => {
    if (status === 'done' && shownLen >= draft.length) setSettled(true);
    if (status === 'error') setSettled(true);
  }, [status, shownLen, draft.length]);

  return { shown: draft.slice(0, Math.min(shownLen, draft.length)), settled };
}
