import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { useUI } from '@/store/ui';
import { TabStrip } from './TabStrip';

const graphTab = (contract: string) =>
  ({ kind: 'graph', title: contract, params: { contract, asof: '2026-07-01' } }) as const;

describe('TabStrip (P1.5 T2)', () => {
  beforeEach(() => {
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('renders nothing with zero tabs (chat panel owns the full height)', () => {
    render(<TabStrip />);
    expect(screen.queryByTestId('tab-strip')).toBeNull();
  });

  it('renders tablist with aria-selected on the active tab; click activates', async () => {
    useUI.getState().openTab(graphTab('corn'));
    useUI.getState().openTab(graphTab('rice'));
    render(<TabStrip />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(2);
    expect(tabs[1]!.getAttribute('aria-selected')).toBe('true'); // last opened = active
    await userEvent.click(screen.getByRole('button', { name: 'corn' }));
    expect(useUI.getState().activeTabId).toBe('graph:corn:2026-07-01');
  });

  it('the ✕ closes its tab and focus falls to the neighbor', async () => {
    useUI.getState().openTab(graphTab('corn'));
    useUI.getState().openTab(graphTab('rice'));
    render(<TabStrip />);
    await userEvent.click(screen.getByLabelText('close rice'));
    expect(useUI.getState().tabs).toHaveLength(1);
    expect(useUI.getState().activeTabId).toBe('graph:corn:2026-07-01');
  });
});
