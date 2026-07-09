import { useEffect, useRef, type RefObject } from 'react';

/**
 * Pin-to-bottom auto-scroll for the conversation column (5.6 W5). While the reader is at (or near) the
 * bottom, new streamed content keeps the view pinned; scrolling up RELEASES the pin (read in peace);
 * scrolling back to within 48px of the bottom re-pins. `dep` should change whenever content grows
 * (revealed text length, stage count).
 */
export function useAutoScroll(ref: RefObject<HTMLElement | null>, dep: unknown): void {
  const pinned = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    // P1.5: the transcript now lives in a height-VARIABLE panel (drag handle, tab open/close, window
    // resize). Content growth is covered by `dep`; CONTAINER shrink/grow needs its own re-pin or a pinned
    // reader drifts off the bottom every drag. jsdom lacks ResizeObserver — the guard matches vitest.setup.
    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => {
        if (pinned.current) el.scrollTop = el.scrollHeight;
      });
      ro.observe(el);
    }
    return () => {
      el.removeEventListener('scroll', onScroll);
      ro?.disconnect();
    };
  }, [ref]);

  useEffect(() => {
    const el = ref.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [ref, dep]);
}
