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
    return () => el.removeEventListener('scroll', onScroll);
  }, [ref]);

  useEffect(() => {
    const el = ref.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [ref, dep]);
}
