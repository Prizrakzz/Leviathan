import { useCallback, useEffect, useRef } from 'react';
import { DEFAULT_PANEL_PX, MIN_PANEL_PX, TAB_STRIP_MIN_PX } from '@/store/tabs';
import { useUI } from '@/store/ui';

/** Clamp a candidate chat-panel height into [MIN_PANEL_PX, container - TAB_STRIP_MIN_PX]. Pure — unit-tested. */
export function clampPanelPx(candidate: number, containerH: number): number {
  const max = Math.max(MIN_PANEL_PX, containerH - TAB_STRIP_MIN_PX);
  return Math.min(Math.max(candidate, MIN_PANEL_PX), max);
}

/** Panel height from a pointer's clientY: the chat panel spans from the pointer to the container bottom. */
export function pxFromPointer(clientY: number, containerBottom: number, containerH: number): number {
  return clampPanelPx(containerBottom - clientY, containerH);
}

/**
 * P1.5-T4: the ONE drag handle — pointer-capture resize of the bottom chat panel.
 *
 * STOMP RULE (the load-bearing design constraint): during a drag the height is written to the panel
 * element DIRECTLY (rAF-coalesced `style.height`), and the store is committed ONCE on pointerup. The
 * panel's JSX must NOT bind `style={{height: panelPx}}` — the streaming transcript re-renders ~per frame,
 * and a JSX-bound height would snap the panel back to the committed value mid-drag. The hook owns the
 * element's height for its whole life: it applies the persisted value on mount and after each commit.
 */
export function usePanelDrag(
  containerRef: React.RefObject<HTMLElement | null>,
  panelRef: React.RefObject<HTMLElement | null>,
  enabled = true,
) {
  const draggingRef = useRef(false);
  const rafRef = useRef<number | null>(null);
  const pendingY = useRef(0);

  // The hook owns the panel's height: apply the persisted value outside drags (mount, external set, reset).
  // Disabled (zero tabs) => clear the inline height so the panel's flex-1 full-height styling wins.
  const panelPx = useUI((s) => s.panelPx);
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    if (!enabled) {
      panel.style.height = '';
      return;
    }
    if (!draggingRef.current)
      panel.style.height = `${clampPanelPx(panelPx, containerRef.current?.getBoundingClientRect().height ?? Infinity)}px`;
  }, [panelPx, panelRef, containerRef, enabled]);

  // Window resize clamps DOWN (a panel sized on a tall screen must not swallow a short viewport).
  useEffect(() => {
    const onResize = () => {
      const c = containerRef.current;
      const p = panelRef.current;
      if (!c || !p || draggingRef.current) return;
      const clamped = clampPanelPx(p.getBoundingClientRect().height, c.getBoundingClientRect().height);
      p.style.height = `${clamped}px`;
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [containerRef, panelRef]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      const handle = e.currentTarget;
      const container = containerRef.current;
      const panel = panelRef.current;
      if (!container || !panel) return;
      e.preventDefault();
      draggingRef.current = true;
      handle.setPointerCapture(e.pointerId);
      const rect = container.getBoundingClientRect();

      const apply = () => {
        rafRef.current = null;
        if (!draggingRef.current) return;
        panel.style.height = `${pxFromPointer(pendingY.current, rect.bottom, rect.height)}px`;
      };
      const onMove = (ev: PointerEvent) => {
        pendingY.current = ev.clientY;
        rafRef.current ??= requestAnimationFrame(apply); // coalesce: one write per frame
      };
      const onUp = (ev: PointerEvent) => {
        draggingRef.current = false;
        if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
        handle.releasePointerCapture(ev.pointerId);
        handle.removeEventListener('pointermove', onMove);
        handle.removeEventListener('pointerup', onUp);
        // ONE store commit -> persisted via the ui v4 partialize (rounded: fractional px persists ugly)
        useUI.getState().setPanelPx(Math.round(pxFromPointer(ev.clientY, rect.bottom, rect.height)));
      };
      handle.addEventListener('pointermove', onMove);
      handle.addEventListener('pointerup', onUp);
    },
    [containerRef, panelRef],
  );

  const onDoubleClick = useCallback(() => useUI.getState().setPanelPx(DEFAULT_PANEL_PX), []);

  // Keyboard a11y: arrow keys nudge the committed height (no rAF path needed at keyboard speed).
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      e.preventDefault();
      const c = containerRef.current?.getBoundingClientRect().height ?? Infinity;
      const cur = panelRef.current?.getBoundingClientRect().height ?? useUI.getState().panelPx;
      useUI.getState().setPanelPx(clampPanelPx(cur + (e.key === 'ArrowUp' ? 24 : -24), c));
    },
    [containerRef, panelRef],
  );

  return { onPointerDown, onDoubleClick, onKeyDown };
}
