import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TurnState } from '@/api/useTurn';
import { DEFAULT_PANEL_PX } from '@/store/tabs';
import { useUI } from '@/store/ui';
import { Workspace } from './Workspace';

// The chat panel content is AnswerView — stubbed: this test guards the LAYOUT gate, not the conversation.
vi.mock('@/views/AnswerView', () => ({
  AnswerView: () => <div data-testid="answer-view-stub" />,
}));
vi.mock('./tabs/TabDocument', () => ({
  default: ({ tab }: { tab: { id: string } }) => <div data-testid="tab-document-stub">{tab.id}</div>,
}));

const idleTurn = { status: 'idle', stages: [], draft: '' } as TurnState;

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Workspace turn={idleTurn} question="" onAsk={() => {}} />
    </QueryClientProvider>,
  );
}

describe('Workspace layout gate (P1.5 T5 — the zero-regression guard)', () => {
  beforeEach(() => {
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('ZERO tabs = handle + empty-workspace hint reachable (S2: not a dead end); chat still full height', () => {
    mount();
    expect(screen.queryByTestId('tab-strip')).toBeNull(); // no strip until a tab exists
    // S2: the dock is now present at zero tabs — this replaces the assertion that codified the dead-end bug.
    expect(screen.getByTestId('drag-handle')).toBeTruthy();
    const doc = screen.getByTestId('document-area');
    expect(doc.textContent).toContain('fill the workspace'); // empty-state hint, not a tab body
    const panel = screen.getByTestId('chat-panel');
    expect(panel.className).toContain('flex-1'); // chat still owns the height by default (today's look)
    expect(panel.style.height).toBe(''); // hook height-ownership stays gated off at zero tabs — no inline px
    expect(screen.getByTestId('view')).toBeTruthy(); // the ViewContainer landmark carried over
  });

  it('with a tab: strip + document area + handle render, active tab body mounts, chat keeps its landmark', () => {
    useUI.getState().openTab({ kind: 'graph', title: 'corn', params: { contract: 'corn' } });
    mount();
    expect(screen.getByTestId('tab-strip')).toBeTruthy();
    expect(screen.getByTestId('drag-handle')).toBeTruthy();
    expect(screen.getByTestId('tab-document-stub').textContent).toBe('graph:corn:');
    expect(screen.getByTestId('answer-view-stub')).toBeTruthy(); // the chat survives alongside
    // fullSurface prerequisite: the document area is the sized flex child
    expect(screen.getByTestId('document-area').className).toContain('min-h-0');
  });
});

describe('Workspace zero-tab drag reachability (S2 — a new thread can resize before any tab exists)', () => {
  beforeEach(() => {
    useUI.setState({ tabs: [], activeTabId: null, panelPx: DEFAULT_PANEL_PX });
    // jsdom has no PointerEvent; the drag hook touches capture APIs + rAF + rects — shim exactly those.
    vi.stubGlobal('PointerEvent', MouseEvent);
    Element.prototype.setPointerCapture = vi.fn();
    Element.prototype.releasePointerCapture = vi.fn();
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      bottom: 900, height: 900, top: 0, left: 0, right: 0, width: 0, x: 0, y: 0, toJSON: () => ({}),
    } as DOMRect);
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 1; });
    vi.stubGlobal('cancelAnimationFrame', () => {});
  });

  it('a fresh (zero-tab) thread exposes the handle + hint, and dragging commits panelPx ONCE', () => {
    mount();
    // affordance present in a brand-new thread — the whole point of the fix
    const handle = screen.getByTestId('drag-handle');
    expect(handle).toBeTruthy();
    expect(screen.queryByTestId('tab-strip')).toBeNull();
    expect(screen.getByTestId('document-area').textContent).toContain('fill the workspace');
    // dragging from the zero-tab state is NOT a no-op: one clamped commit lands on pointerup
    fireEvent.pointerDown(handle, { pointerId: 1, clientY: 500 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientY: 600 });
    expect(useUI.getState().panelPx).toBe(DEFAULT_PANEL_PX); // not committed mid-drag
    fireEvent.pointerUp(handle, { pointerId: 1, clientY: 650 });
    expect(useUI.getState().panelPx).toBe(250); // 900 - 650, clamped + committed once
  });
});
