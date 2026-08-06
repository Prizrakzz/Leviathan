import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Only the series fetch is mocked; the row, its key and its expansion states are the real component.
const h = vi.hoisted(() => ({ getSeries: vi.fn() }));
vi.mock('@/api/client', () => ({ getSeries: h.getSeries }));

import { useUI } from '@/store/ui';
import { Numbers } from './Numbers';

const ASOF = '2024-06-01';
const SERIES = {
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

/** One NUMBERS row as the engine emits it: a `[N#]` ref, the observed row, and the query that produced it. */
function numCall(ref: string, query: Record<string, string> = {}) {
  return {
    ref,
    status: 'ok',
    rows: [{ value: '12.0', z: '0.2' }],
    query: { table: 'silver_psd', metric: 'exports', commodity: 'soybeans', ...query },
  };
}

function mount(calls: unknown[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Numbers calls={calls} asof={ASOF} />
    </QueryClientProvider>,
  );
}

const row = (ref: string) => screen.getByRole('button', { name: new RegExp(`\\[${ref}\\]`) });

describe('Numbers row expansion states (D-TW-9)', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(SERIES);
  });

  it('an in-flight series says so instead of expanding to nothing', async () => {
    h.getSeries.mockReturnValue(new Promise(() => {})); // never settles -- the row must not look inert
    mount([numCall('N1')]);
    await userEvent.click(row('N1'));
    expect(await screen.findByText(/loading series/i)).toBeInTheDocument();
  });

  it('a failed series offers a retry that refetches', async () => {
    h.getSeries.mockRejectedValue(new Error('502'));
    mount([numCall('N1')]);
    await userEvent.click(row('N1'));
    expect(await screen.findByText(/couldn't load this series/i)).toBeInTheDocument();

    h.getSeries.mockResolvedValue(SERIES);
    await userEvent.click(screen.getByRole('button', { name: 'retry' }));
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('img', { name: /exports series/i })).toBeInTheDocument();
  });

  it('a series too short to plot says so rather than expanding into a void', async () => {
    h.getSeries.mockResolvedValue({ ...SERIES, points: [SERIES.points[0]] });
    mount([numCall('N1')]);
    await userEvent.click(row('N1'));
    expect(await screen.findByText(/no series to plot/i)).toBeInTheDocument();
  });
});

describe('Numbers country scoping (D-TW-9)', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(SERIES);
  });

  it("sends the call's country, so the sparkline is the scoped series the row was read from", async () => {
    mount([numCall('N1', { country: 'Brazil' })]);
    await userEvent.click(row('N1'));
    await waitFor(() =>
      expect(h.getSeries).toHaveBeenCalledWith('silver_psd', 'exports', {
        commodity: 'soybeans',
        country: 'Brazil',
        asof: ASOF,
      }),
    );
  });

  it('an ordinary row sends NO curve parameters -- the pre-wave request, unchanged', async () => {
    mount([numCall('N1')]);
    await userEvent.click(row('N1'));
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(1));
    const opts = h.getSeries.mock.calls[0]![2] as Record<string, unknown>;
    expect(Object.keys(opts).sort()).toEqual(['asof', 'commodity', 'country']);
  });

  it('two calls differing ONLY by country are two cache entries, not one', async () => {
    mount([numCall('N1', { country: 'Brazil' }), numCall('N2', { country: 'Argentina' })]);
    await userEvent.click(row('N1'));
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(1));
    await userEvent.click(row('N2'));
    // Pre-fix the key omitted country: the second row hit Brazil's cache entry and drew Brazil's line.
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(2));
    expect(h.getSeries.mock.calls.map((c) => (c[2] as { country?: string }).country)).toEqual([
      'Brazil',
      'Argentina',
    ]);
  });
});

// ── D-AM-21: the curve (carry / backwardation) view ────────────────────────────────────────────────
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
    { contract_month: '2027-03', value: '461.5', knowledge_date: SESSION },
  ],
};

/** A futures NUMBERS row: the engine's curve read, with the expiries on the query AND on the rows. */
function futuresCall(ref: string, query: Record<string, string> = {}) {
  return {
    ref,
    status: 'ok',
    rows: CURVE.points.map((p) => ({ value: p.value, contract_month: p.contract_month })),
    query: {
      table: 'silver_futures_eod',
      metric: 'settle',
      commodity: 'corn_cbot',
      contract_month: '2026-07,2026-12,2027-03',
      ...query,
    },
  };
}

describe('Numbers curve view (D-AM-21)', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(CURVE);
  });

  it('offers the axis switch on a futures row and NOT on an ordinary one', async () => {
    mount([numCall('N1'), futuresCall('N2')]);
    await userEvent.click(row('N1'));
    expect(screen.queryByRole('button', { name: 'curve' })).not.toBeInTheDocument();
    await userEvent.click(row('N2'));
    expect(screen.getByRole('button', { name: 'curve' })).toBeInTheDocument();
  });

  it('hides the switch until the row is expanded, so the collapsed list is unchanged', () => {
    mount([futuresCall('N1')]);
    expect(screen.queryByRole('button', { name: 'curve' })).not.toBeInTheDocument();
  });

  it('fetches the tracked expiries at agg=latest, at the ROW\'S OWN as-of', async () => {
    mount([futuresCall('N1')]);
    await userEvent.click(row('N1'));
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(1)); // the time series, as before
    await userEvent.click(screen.getByRole('button', { name: 'curve' }));
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(2));
    expect(h.getSeries.mock.calls[1]).toEqual([
      'silver_futures_eod',
      'settle',
      {
        commodity: 'corn_cbot',
        country: undefined,
        asof: ASOF,               // PIT: the same as-of the view already threads, never a fresher one
        contractMonth: '2026-07,2026-12,2027-03',
        agg: 'latest',
      },
    ]);
  });

  it('renders the curve chart, then goes back to the time series', async () => {
    mount([futuresCall('N1')]);
    await userEvent.click(row('N1'));
    await userEvent.click(screen.getByRole('button', { name: 'curve' }));
    expect(await screen.findByRole('img', { name: /settle curve/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'time' }));
    expect(await screen.findByRole('img', { name: /settle series/i })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /settle curve/i })).not.toBeInTheDocument();
  });

  it('falls back to the expiries on the ROWS when the call named no month scope', async () => {
    const call = futuresCall('N1');
    delete (call.query as Record<string, unknown>).contract_month;
    mount([call]);
    await userEvent.click(row('N1'));
    await userEvent.click(screen.getByRole('button', { name: 'curve' }));
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(2));
    expect((h.getSeries.mock.calls[1]![2] as { contractMonth?: string }).contractMonth).toBe(
      '2026-07,2026-12,2027-03',
    );
  });

  it('a failed curve says so and offers its own retry', async () => {
    h.getSeries.mockResolvedValueOnce(CURVE).mockRejectedValueOnce(new Error('502'));
    mount([futuresCall('N1')]);
    await userEvent.click(row('N1'));
    await userEvent.click(screen.getByRole('button', { name: 'curve' }));
    expect(await screen.findByText(/couldn't load this curve/i)).toBeInTheDocument();

    h.getSeries.mockResolvedValue(CURVE);
    await userEvent.click(screen.getByRole('button', { name: 'retry' }));
    expect(await screen.findByRole('img', { name: /settle curve/i })).toBeInTheDocument();
  });

  it('a curve too short to plot says so rather than expanding into a void', async () => {
    h.getSeries.mockResolvedValue({ ...CURVE, points: [CURVE.points[0]] });
    mount([futuresCall('N1')]);
    await userEvent.click(row('N1'));
    await userEvent.click(screen.getByRole('button', { name: 'curve' }));
    expect(await screen.findByText(/no curve to plot/i)).toBeInTheDocument();
  });
});

// ── D-UX-2: the ALWAYS-VISIBLE chart entry point ───────────────────────────────────────────────────
// The defect this fixes: the D-AM-21 curve view was real, shipped and effectively invisible -- reachable
// only by expanding a row and then noticing a switch that exists on futures cards alone. The rule the
// tests below pin is the plan's: the AFFORDANCE is never data-gated, the OPTIONS are.
describe('Numbers chart affordance (D-UX-2)', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(SERIES);
    useUI.setState({ tabs: [], activeTabId: null });
  });

  const chartBtn = (metric = 'exports') => screen.getByRole('button', { name: `open ${metric} chart` });

  it('is visible on a COLLAPSED row -- no expansion required to discover it', () => {
    mount([numCall('N1')]);
    expect(screen.getByTestId('chart-affordance')).toBeInTheDocument();
    expect(chartBtn()).toBeInTheDocument();
  });

  it('is visible on an ORDINARY (non-futures) row too, and fetches nothing on its own', () => {
    mount([numCall('N1')]);
    expect(chartBtn()).toBeInTheDocument();
    expect(h.getSeries).not.toHaveBeenCalled(); // the affordance is a link, not a read
  });

  it('opens a chart TAB carrying the row\'s locator, including its country scope', async () => {
    mount([numCall('N1', { country: 'Brazil' })]);
    await userEvent.click(chartBtn());
    const tabs = useUI.getState().tabs;
    expect(tabs).toHaveLength(1);
    expect(tabs[0]!.kind).toBe('chart');
    expect(tabs[0]!.params).toEqual({
      table: 'silver_psd',
      metric: 'exports',
      commodity: 'soybeans',
      country: 'Brazil', // D-TW-9 again: without it the tab draws a different series under this row's name
      axis: 'time',
      asof: ASOF,
    });
  });

  it('offers the CURVE option only on a row that tracks two or more delivery months', () => {
    mount([numCall('N1'), futuresCall('N2')]);
    expect(screen.queryByRole('button', { name: 'open exports curve chart' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'open settle curve chart' })).toBeInTheDocument();
    // ...and the plain chart option is on BOTH -- the affordance itself is never data-gated
    expect(chartBtn()).toBeInTheDocument();
    expect(chartBtn('settle')).toBeInTheDocument();
  });

  it('the curve option opens a curve-axis tab naming the months the call already tracked', async () => {
    mount([futuresCall('N1')]);
    await userEvent.click(screen.getByRole('button', { name: 'open settle curve chart' }));
    expect(useUI.getState().tabs[0]!.params).toEqual({
      table: 'silver_futures_eod',
      metric: 'settle',
      commodity: 'corn_cbot',
      axis: 'curve',
      asof: ASOF, // the ROW's own as-of -- the curve the answer was standing on
      contract_month: '2026-07,2026-12,2027-03',
    });
  });

  it('a not-yet-published row offers NO chart -- there is no series to draw at this as-of', () => {
    mount([{ ...numCall('N1'), status: 'not_yet_pub' }]);
    expect(screen.queryByTestId('chart-affordance')).not.toBeInTheDocument();
  });

  it('does not collide with the D-AM-21 axis switch inside the expansion', async () => {
    // Both live on the same row; the switch's buttons are literally named 'time' and 'curve'. The
    // affordance carries aria-labels so neither control can be selected by the other's name.
    h.getSeries.mockResolvedValue(CURVE);
    mount([futuresCall('N1')]);
    await userEvent.click(row('N1'));
    expect(screen.getAllByRole('button', { name: 'curve' })).toHaveLength(1); // the switch, only
    expect(screen.getAllByRole('button', { name: 'open settle curve chart' })).toHaveLength(1);
  });
});
