import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { TurnState } from '@/api/useTurn';
import { useSession } from '@/store/session';
import { useUI } from '@/store/ui';
import { ThreadSidebar } from './ThreadSidebar';

const idleTurn = { status: 'idle', stages: [], draft: '' } as TurnState;

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThreadSidebar turn={idleTurn} />
    </QueryClientProvider>,
  );
}

describe('ThreadSidebar collapse chevron (W1.6)', () => {
  beforeEach(() => {
    // authEnabled=false defaults session ready=true → the live GET /v1/threads query would fire in jsdom.
    // Gate it off: this test is about the chevron wiring, not the thread list.
    useSession.setState({ ready: false });
    useUI.setState({ threadCollapsed: false });
  });
  afterEach(() => {
    useSession.setState({ ready: true });
  });

  it('the header chevron flips threadCollapsed (same state the Ctrl+\\ hotkey toggles)', async () => {
    mount();
    expect(useUI.getState().threadCollapsed).toBe(false);
    await userEvent.click(screen.getByLabelText('collapse threads'));
    expect(useUI.getState().threadCollapsed).toBe(true);
  });
});
