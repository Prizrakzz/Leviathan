import { beforeEach, describe, expect, it } from 'vitest';
import { useUI } from './ui';

describe('ui store (persist migration — 5.6 view-prune)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('coerces a v1 persisted view (deep/convergence) to answer and drops contract on boot', async () => {
    // A returning user whose localStorage still holds a now-deleted view + a stale contract.
    localStorage.setItem(
      'lv-ui',
      JSON.stringify({ state: { view: 'deep', contract: 'corn', accent: 'amber' }, version: 1 }),
    );

    // rehydrate reruns the persist pipeline (version bump -> migrate) against the stored blob.
    await useUI.persist.rehydrate();

    const s = useUI.getState();
    expect(s.view).toBe('answer'); // migrated away from the deleted 'deep' view
    expect(s.accent).toBe('amber'); // an unrelated persisted field survives the migration
    expect('contract' in s).toBe(false); // the dead `contract` field is gone from the store shape
  });

  it('migrates a persisted convergence view to answer too', async () => {
    localStorage.setItem(
      'lv-ui',
      JSON.stringify({ state: { view: 'convergence', accent: 'cyan' }, version: 1 }),
    );
    await useUI.persist.rehydrate();
    expect(useUI.getState().view).toBe('answer');
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
});
