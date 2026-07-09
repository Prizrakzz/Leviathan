import { fireEvent, render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DragHandle } from '@/shell/DragHandle';
import { DEFAULT_PANEL_PX, MIN_PANEL_PX } from '@/store/tabs';
import { useUI } from '@/store/ui';
import { clampPanelPx, pxFromPointer, usePanelDrag } from './usePanelDrag';

describe('clamp/geometry math (pure)', () => {
  it('clamps into [MIN, container - strip]', () => {
    expect(clampPanelPx(50, 800)).toBe(MIN_PANEL_PX);
    expect(clampPanelPx(400, 800)).toBe(400);
    expect(clampPanelPx(2000, 800)).toBe(800 - 48);
  });

  it('degenerate container never inverts the range', () => {
    expect(clampPanelPx(400, 100)).toBe(MIN_PANEL_PX); // max floors at MIN
  });

  it('pxFromPointer: panel spans pointer -> container bottom', () => {
    expect(pxFromPointer(600, 900, 900)).toBe(300);
    expect(pxFromPointer(880, 900, 900)).toBe(MIN_PANEL_PX); // dragged to the bottom -> MIN
  });
});

// jsdom lacks PointerEvent capture APIs — shim what the hook touches.
function Harness() {
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const h = usePanelDrag(containerRef, panelRef);
  return (
    <div ref={containerRef}>
      <DragHandle {...h} />
      <div ref={panelRef} data-testid="panel" />
    </div>
  );
}

describe('usePanelDrag (jsdom pointer sim)', () => {
  beforeEach(() => {
    useUI.setState({ panelPx: DEFAULT_PANEL_PX });
    // jsdom has no PointerEvent: alias to MouseEvent so fireEvent.pointer* carries clientY to NATIVE listeners
    vi.stubGlobal('PointerEvent', MouseEvent);
    Element.prototype.setPointerCapture = vi.fn();
    Element.prototype.releasePointerCapture = vi.fn();
    // container: bottom=900, height=900 (jsdom rects are all-zero by default)
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      bottom: 900, height: 900, top: 0, left: 0, right: 0, width: 0, x: 0, y: 0, toJSON: () => ({}),
    } as DOMRect);
    // rAF flushes synchronously so the live height write is observable
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 1; });
    vi.stubGlobal('cancelAnimationFrame', () => {});
  });

  it('drag writes the panel height live and commits ONCE to the store on pointerup', () => {
    render(<Harness />);
    const handle = screen.getByTestId('drag-handle');
    const panel = screen.getByTestId('panel');
    fireEvent.pointerDown(handle, { pointerId: 1, clientY: 500 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientY: 600 });
    expect(panel.style.height).toBe('300px'); // 900 - 600, live DOM write
    expect(useUI.getState().panelPx).toBe(DEFAULT_PANEL_PX); // NOT committed mid-drag
    fireEvent.pointerUp(handle, { pointerId: 1, clientY: 650 });
    expect(useUI.getState().panelPx).toBe(250); // ONE clamped commit
  });

  it('double-click resets to the default; arrow keys nudge with clamp', () => {
    render(<Harness />);
    const handle = screen.getByTestId('drag-handle');
    fireEvent.doubleClick(handle);
    expect(useUI.getState().panelPx).toBe(DEFAULT_PANEL_PX);
    fireEvent.keyDown(handle, { key: 'ArrowDown' });
    // panel rect height mocked at 900 -> 900-24 clamps to container - strip = 852
    expect(useUI.getState().panelPx).toBe(852);
  });
});
