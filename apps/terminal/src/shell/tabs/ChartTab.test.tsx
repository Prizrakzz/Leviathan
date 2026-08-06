import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ getSeries: vi.fn() }));
vi.mock('@/api/client', () => ({ getSeries: h.getSeries }));

import type { ChartTabParams } from '@/store/tabs';
import { tabKey } from '@/store/tabs';
import { useUI } from '@/store/ui';
import ChartTab from './ChartTab';

const ASOF = '2026-06-08';
const SESSION = '2026-06-05';

const CURVE = {
  table: 'silver_futures_eod',
  metric: 'settle',
  commodity: 'corn_cbot',
  asof: ASOF,
  unit: 'US cents/bushel',
  points: [
    { contract_month: '2026-07', value: '417.5', knowledge_date: SESSION },
    { contract_month: '2026-12', value: '446.0', knowledge_date: SESSION },
  ],
};
const TIME = {
  table: 'silver_psd',
  metric: 'exports',
  commodity: 'soybeans',
  asof: ASOF,
  unit: 'kt',
  points: [
    { period: '2022', value: '10.0', knowledge_date: '2022-06-10' },
    { period: '2023', value: '12.0', knowledge_date: '2023-06-10' },
  ],
};

const TIME_PARAMS: ChartTabParams = {
  table: 'silver_psd',
  metric: 'exports',
  commodity: 'soybeans',
  country: 'Brazil',
  axis: 'time',
  asof: ASOF,
};
const CURVE_PARAMS: ChartTabParams = {
  table: 'silver_futures_eod',
  metric: 'settle',
  commodity: 'corn_cbot',
  contract_month: '2026-07,2026-12',
  axis: 'curve',
  asof: ASOF,
};

function mount(params: ChartTabParams, qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={qc}>
      <ChartTab params={params} />
    </QueryClientProvider>,
  );
}

describe('ChartTab (D-UX-2)', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(TIME);
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('renders a time chart from its locator, pinned to the locator\'s as-of', async () => {
    mount(TIME_PARAMS);
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(1));
    expect(h.getSeries.mock.calls[0]).toEqual([
      'silver_psd',
      'exports',
      { commodity: 'soybeans', country: 'Brazil', asof: ASOF },
    ]);
    expect(await screen.findByRole('img', { name: /exports series/i })).toBeInTheDocument();
    expect(screen.getByTestId('chart-tab-head').textContent).toContain('as of 2026-06-08');
  });

  it('renders a CURVE chart when the locator says so, with the named months at agg=latest', async () => {
    h.getSeries.mockResolvedValue(CURVE);
    mount(CURVE_PARAMS);
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(1));
    expect(h.getSeries.mock.calls[0]![2]).toEqual({
      commodity: 'corn_cbot',
      country: undefined,
      asof: ASOF,
      contractMonth: '2026-07,2026-12',
      agg: 'latest',
    });
    expect(await screen.findByRole('img', { name: /settle curve/i })).toBeInTheDocument();
  });

  it('says it is loading rather than sitting inert', () => {
    h.getSeries.mockReturnValue(new Promise(() => {}));
    mount(TIME_PARAMS);
    expect(screen.getByTestId('chart-tab-loading')).toBeInTheDocument();
  });

  it('a failed fetch offers a retry that refetches', async () => {
    h.getSeries.mockRejectedValue(new Error('502'));
    mount(TIME_PARAMS);
    expect(await screen.findByText(/couldn.t load this chart/i)).toBeInTheDocument();
    h.getSeries.mockResolvedValue(TIME);
    await userEvent.click(screen.getByRole('button', { name: 'retry' }));
    expect(await screen.findByRole('img', { name: /exports series/i })).toBeInTheDocument();
  });

  it('a STALE locator degrades to a plain line, never a crash', async () => {
    // A renamed metric or a delivery month that no longer resolves comes back empty; the tab is
    // locator-only, so this is the only place that truth can surface.
    h.getSeries.mockResolvedValue({ ...TIME, points: [] });
    mount(TIME_PARAMS);
    expect(await screen.findByTestId('chart-tab-empty')).toBeInTheDocument();
  });

  it('REHYDRATES from params alone: a fresh mount off the stored tab refetches and draws', async () => {
    // The persistence contract (store/tabs.ts): tabs carry locators, never points. Opening, "reloading"
    // (a brand-new QueryClient + a brand-new mount) and drawing again must need nothing but the params.
    useUI.getState().openTab({ kind: 'chart', title: 'soybeans exports', params: TIME_PARAMS });
    const stored = useUI.getState().tabs[0]!;
    expect(stored.params).toEqual(TIME_PARAMS); // no fetched content smuggled into the store
    const { unmount } = mount(stored.params as ChartTabParams);
    expect(await screen.findByRole('img', { name: /exports series/i })).toBeInTheDocument();
    unmount();
    mount(stored.params as ChartTabParams, new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    expect(await screen.findByRole('img', { name: /exports series/i })).toBeInTheDocument();
    expect(h.getSeries).toHaveBeenCalledTimes(2);
  });
});

describe('chart tabKey (D-UX-2 identity)', () => {
  beforeEach(() => {
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('every locator field rides the key — the D-TW-9 lesson at the tab layer', () => {
    const base = tabKey('chart', TIME_PARAMS);
    // table : metric : commodity : country : contract_month : axis : asof
    expect(base).toBe('chart:silver_psd:exports:soybeans:Brazil::time:2026-06-08');
    // two reads differing ONLY by country are two tabs, not one drawing the other's line
    expect(tabKey('chart', { ...TIME_PARAMS, country: 'Argentina' })).not.toBe(base);
    // ...and the axis, the months and the as-of each split identity too
    expect(tabKey('chart', { ...TIME_PARAMS, axis: 'curve' })).not.toBe(base);
    expect(tabKey('chart', { ...TIME_PARAMS, contract_month: '2026-12' })).not.toBe(base);
    expect(tabKey('chart', { ...TIME_PARAMS, asof: '2026-06-07' })).not.toBe(base);
  });

  it('reopening the SAME chart focuses the open tab instead of duplicating it', () => {
    useUI.getState().openTab({ kind: 'chart', title: 'a', params: TIME_PARAMS });
    useUI.getState().openTab({ kind: 'chart', title: 'a', params: TIME_PARAMS });
    expect(useUI.getState().tabs).toHaveLength(1);
    useUI.getState().openTab({ kind: 'chart', title: 'b', params: CURVE_PARAMS });
    expect(useUI.getState().tabs).toHaveLength(2);
    expect(useUI.getState().activeTabId).toBe(tabKey('chart', CURVE_PARAMS));
  });
});
