import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TurnState } from '@/api/useTurn';
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

  it("ZERO tabs = today's look: no strip, no handle, no document area — chat panel full height", () => {
    mount();
    expect(screen.queryByTestId('tab-strip')).toBeNull();
    expect(screen.queryByTestId('drag-handle')).toBeNull();
    expect(screen.queryByTestId('document-area')).toBeNull();
    const panel = screen.getByTestId('chat-panel');
    expect(panel.className).toContain('flex-1'); // full height
    expect(panel.style.height).toBe(''); // drag hook disabled — no inline height fighting flex-1
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
