import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TurnStatus } from '@/api/useTurn';
import { useTypewriter } from './useTypewriter';

let out: { shown: string; settled: boolean };
function Harness({ draft, status }: { draft: string; status: TurnStatus }) {
  out = useTypewriter(draft, status);
  return null;
}

// Drive rAF manually so the reveal is deterministic.
let rafQueue: FrameRequestCallback[] = [];
function flushFrames(n: number) {
  for (let i = 0; i < n; i++) {
    const q = rafQueue;
    rafQueue = [];
    act(() => q.forEach((cb) => cb(performance.now())));
  }
}

beforeEach(() => {
  rafQueue = [];
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    rafQueue.push(cb);
    return rafQueue.length;
  });
  vi.stubGlobal('cancelAnimationFrame', () => {});
});
afterEach(() => vi.unstubAllGlobals());

describe('useTypewriter', () => {
  it('reveals a burst gradually, not all at once', () => {
    const burst = 'x'.repeat(600);
    const { rerender } = render(<Harness draft="" status="streaming" />);
    rerender(<Harness draft={burst} status="streaming" />);
    flushFrames(1);
    expect(out.shown.length).toBeGreaterThan(0);
    expect(out.shown.length).toBeLessThan(burst.length); // NOT the whole slab in one frame
    flushFrames(120);
    expect(out.shown.length).toBe(burst.length); // catches up
    expect(out.settled).toBe(false); // still streaming
  });

  it('drains fast and settles when the turn completes', () => {
    const text = 'y'.repeat(400);
    const { rerender } = render(<Harness draft="" status="streaming" />);
    rerender(<Harness draft={text} status="streaming" />);
    flushFrames(2);
    rerender(<Harness draft={text} status="done" />);
    flushFrames(60);
    expect(out.shown).toBe(text);
    expect(out.settled).toBe(true);
  });

  it('settles immediately on error', () => {
    render(<Harness draft="partial" status="error" />);
    expect(out.settled).toBe(true);
  });
});
