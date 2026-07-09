import { beforeEach, describe, expect, it } from 'vitest';
import { tabKey } from './tabs';
import { useUI } from './ui';

const graphTab = (contract: string, asof = '2026-07-01') =>
  ({ kind: 'graph', title: contract, params: { contract, asof } }) as const;

describe('tabs slice (P1.5 T1 — dedupe-focus, close-neighbor, key normalization)', () => {
  beforeEach(() => {
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('openTab appends + activates; same tabKey focuses the existing tab instead of duplicating', () => {
    useUI.getState().openTab(graphTab('corn'));
    useUI.getState().openTab(graphTab('arabica_coffee'));
    expect(useUI.getState().tabs).toHaveLength(2);
    expect(useUI.getState().activeTabId).toBe('graph:arabica_coffee:2026-07-01');
    // reopen corn -> focus, no dup
    useUI.getState().openTab(graphTab('corn'));
    expect(useUI.getState().tabs).toHaveLength(2);
    expect(useUI.getState().activeTabId).toBe('graph:corn:2026-07-01');
  });

  it('reopening a pdf tab refreshes params (page jump) without duplicating', () => {
    useUI.getState().openTab({ kind: 'pdf', title: 'WASDE', params: { sourceKey: 's3://k', snippet: 'a' } });
    useUI.getState().openTab({ kind: 'pdf', title: 'WASDE', params: { sourceKey: 's3://k', snippet: 'b' } });
    const tabs = useUI.getState().tabs;
    expect(tabs).toHaveLength(1);
    expect((tabs[0]!.params as { snippet?: string }).snippet).toBe('b');
  });

  it('closeTab hands focus to the neighbor; closing the last tab nulls active', () => {
    useUI.getState().openTab(graphTab('corn'));
    useUI.getState().openTab(graphTab('raw_sugar'));
    useUI.getState().openTab(graphTab('rice'));
    useUI.getState().setActiveTab('graph:raw_sugar:2026-07-01');
    useUI.getState().closeTab('graph:raw_sugar:2026-07-01');
    expect(useUI.getState().activeTabId).toBe('graph:rice:2026-07-01'); // right neighbor
    useUI.getState().closeTab('graph:rice:2026-07-01');
    useUI.getState().closeTab('graph:corn:2026-07-01');
    expect(useUI.getState().tabs).toHaveLength(0);
    expect(useUI.getState().activeTabId).toBeNull();
  });

  it('setActiveTab ignores unknown ids (a stale persisted activeTabId cannot select nothing)', () => {
    useUI.getState().openTab(graphTab('corn'));
    useUI.getState().setActiveTab('graph:nope:');
    expect(useUI.getState().activeTabId).toBe('graph:corn:2026-07-01');
  });

  it('tabKey normalizes asof ?? "" — identical to the graphQ query key family', () => {
    expect(tabKey('graph', { contract: 'corn' })).toBe('graph:corn:');
    expect(tabKey('graph', { contract: 'corn', asof: '' })).toBe('graph:corn:');
  });
});
