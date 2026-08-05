import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MOCK_RESULT } from '@/api/mock';
import type { RespondResult } from '@/api/schema';
import type { GraphTabParams } from '@/store/tabs';
import { useUI } from '@/store/ui';
import { ReceiptsDrawer } from './ReceiptsDrawer';

/** D-TW-16: the drawer's outbound leg — a fired driver opens the causal map CENTRED on it. The wiring is
 *  what these assert (openTab payload + tab identity), not React Flow, which never mounts here. */
describe('ReceiptsDrawer driver chips (D-TW-16)', () => {
  beforeEach(() => {
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('opens the graph tab focused on the clicked driver and closes the drawer', async () => {
    const onClose = vi.fn();
    render(<ReceiptsDrawer result={MOCK_RESULT} open onClose={onClose} />);

    await userEvent.click(screen.getByRole('button', { name: /low stocks/ }));

    const [tab] = useUI.getState().tabs;
    expect(tab?.kind).toBe('graph');
    const p = tab?.params as GraphTabParams;
    expect(p.contract).toBe('arabica_coffee');
    expect(p.focus).toBe('low_stocks'); // the RAW node id, not the display label
    expect(p.asof).toBe('2021-07-20');
    expect(p.drivers).toEqual(['frost', 'low_stocks']); // the firing overlay rides along, as from the answer
    // The drawer is modal: leaving it open would hide the map behind its scrim.
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('a second driver RE-CENTRES the same tab (identical tabKey) — never a second graph tab', async () => {
    const { rerender } = render(<ReceiptsDrawer result={MOCK_RESULT} open onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /frost/ }));
    rerender(<ReceiptsDrawer result={MOCK_RESULT} open onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /low stocks/ }));

    expect(useUI.getState().tabs).toHaveLength(1);
    expect((useUI.getState().tabs[0]?.params as GraphTabParams).focus).toBe('low_stocks');
  });

  it('no contract (a floor/refused turn) => no chips at all — GraphTab cannot render without one', () => {
    const floor = { ...MOCK_RESULT, contract: null, contracts: [] } as RespondResult;
    render(<ReceiptsDrawer result={floor} open onClose={() => {}} />);
    expect(screen.queryByTestId('receipts-drivers')).toBeNull();
  });
});

/** D-TW-23 (pin leg): once the chips are wired, the drawer has to resolve the handle they fire. A prose chip
 *  fires its TYPED display handle ([E5]/[N1]/legacy bare [5]); a receipt row's ref is `citation.ref ?? id`,
 *  and the two live wire shapes disagree -- the serving `Citation` model carries only the typed `id`, while
 *  `structured.sources` (and the mock fixture) number refs as bare integers. Unpinned = the drawer opens on
 *  the full list, which reads as "the click did something random". */
describe('ReceiptsDrawer pin resolution (D-TW-23)', () => {
  /** Prod shape: `id` only, no `ref` — so `partitionReceipts` rows come out ref='E5' / 'N1'. */
  const typedResult = {
    ...MOCK_RESULT,
    structured: { ...MOCK_RESULT.structured, sources: [{ ref: 5, source: 'USDA WASDE', date: '2021-07-12', source_key: 's3://wasde/2021-07' }] },
    citations: [
      { kind: 'evidence', id: 'E5', source: 'usda_wasde', date: '2021-07-12',
        locator: { kind: 'doc', source_key: 's3://wasde/2021-07', snippet: 'wasde snippet' } },
      { kind: 'evidence', id: 'E6', source: 'usda_gain_coffee', date: '2021-07-20',
        locator: { kind: 'doc', source_key: 's3://gain/kc-2021-07-20', snippet: 'gain snippet' } },
    ],
  } as unknown as RespondResult;

  it('typed handle vs typed row id: [E5] pins its own document', () => {
    render(<ReceiptsDrawer result={typedResult} open onClose={() => {}} pinnedRef="E5" />);
    expect(screen.getByRole('button', { name: /pinned \[E5\]/ })).toBeTruthy();
    expect(screen.getByTestId('receipts').textContent).toContain('1 cited');
  });

  it('typed handle vs BARE-INTEGER row ref: [E2] still pins row [2] (the mock/`sources` convention)', () => {
    render(<ReceiptsDrawer result={MOCK_RESULT} open onClose={() => {}} pinnedRef="E2" />);
    expect(screen.getByRole('button', { name: /pinned \[E2\]/ })).toBeTruthy();
    expect(screen.getByTestId('receipts').textContent).toContain('1 cited');
  });

  it('a NUMBER handle never digit-falls-back: [N1] must not pin evidence row [1]', () => {
    // MOCK_RESULT rows: E1 -> ref '1' (gain), E2 -> ref '2' (wasde), N1 -> ref 'N1' (no source_key).
    // Exact match finds the number row, which has no document to filter by -> the full list stays.
    render(<ReceiptsDrawer result={MOCK_RESULT} open onClose={() => {}} pinnedRef="N1" />);
    expect(screen.queryByRole('button', { name: /pinned/ })).toBeNull();
    expect(screen.getByTestId('receipts').textContent).toContain('3 cited');
  });

  it('an unresolvable handle degrades to the unfiltered list, never an empty drawer', () => {
    render(<ReceiptsDrawer result={MOCK_RESULT} open onClose={() => {}} pinnedRef="E99" />);
    expect(screen.getByTestId('receipts').textContent).toContain('3 cited');
  });
});
