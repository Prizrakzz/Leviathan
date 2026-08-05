import { beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_PANEL_PX } from './tabs';
import { useUI } from './ui';

describe('ui store (persist migration — 5.6 view-prune, finished in D-TW-15)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('drops a v1 persisted view (deep/convergence) and contract on boot', async () => {
    // A returning user whose localStorage still holds a now-deleted view + a stale contract.
    localStorage.setItem(
      'lv-ui',
      JSON.stringify({ state: { view: 'deep', contract: 'corn', accent: 'amber' }, version: 1 }),
    );

    // rehydrate reruns the persist pipeline (version bump -> migrate) against the stored blob.
    await useUI.persist.rehydrate();

    const s = useUI.getState();
    expect(s.accent).toBe('amber'); // an unrelated persisted field survives the migration
    // Both dead fields are gone from the store SHAPE — persist shallow-merges, so a migrate that only
    // coerced `view` would still graft the key back on for every pre-v5 user.
    expect('view' in s).toBe(false);
    expect('contract' in s).toBe(false);
  });

  it('drops a v4 persisted view too (the value was always the single-member `answer`)', async () => {
    localStorage.setItem(
      'lv-ui',
      JSON.stringify({ state: { view: 'answer', accent: 'cyan' }, version: 4 }),
    );
    await useUI.persist.rehydrate();
    expect('view' in useUI.getState()).toBe(false);
  });

  it('v2→3: backfills threadCollapsed=false for a pre-v3 blob (W1.6)', async () => {
    localStorage.setItem(
      'lv-ui',
      JSON.stringify({ state: { view: 'answer', accent: 'cyan' }, version: 2 }),
    );
    await useUI.persist.rehydrate();
    expect(useUI.getState().threadCollapsed).toBe(false);
  });

  it('v3: a persisted collapsed sidebar survives reload (W1.6)', async () => {
    localStorage.setItem(
      'lv-ui',
      JSON.stringify({ state: { view: 'answer', accent: 'cyan', threadCollapsed: true }, version: 3 }),
    );
    await useUI.persist.rehydrate();
    expect(useUI.getState().threadCollapsed).toBe(true);
  });

  it('v3→4: backfills tabs=[], activeTabId=null, panelPx=default for a pre-v4 blob (P1.5)', async () => {
    localStorage.setItem(
      'lv-ui',
      JSON.stringify({ state: { view: 'answer', accent: 'cyan', threadCollapsed: true }, version: 3 }),
    );
    await useUI.persist.rehydrate();
    const s = useUI.getState();
    expect(s.tabs).toEqual([]);
    expect(s.activeTabId).toBeNull();
    expect(s.panelPx).toBe(DEFAULT_PANEL_PX);
    expect(s.threadCollapsed).toBe(true); // v3 backfill still intact through the v4 migrate
  });

  it('v5: a persisted workspace (tabs + active + panel) survives reload (P1.5)', async () => {
    const tab = { id: 'graph:corn:', kind: 'graph', title: 'corn', params: { contract: 'corn' } };
    localStorage.setItem(
      'lv-ui',
      JSON.stringify({
        state: { accent: 'cyan', threadCollapsed: false, tabs: [tab], activeTabId: tab.id, panelPx: 480 },
        version: 5,
      }),
    );
    await useUI.persist.rehydrate();
    const s = useUI.getState();
    expect(s.tabs).toHaveLength(1);
    expect(s.activeTabId).toBe('graph:corn:');
    expect(s.panelPx).toBe(480);
  });
});
