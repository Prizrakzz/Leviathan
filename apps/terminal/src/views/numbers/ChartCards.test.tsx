import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ getSeries: vi.fn() }));
vi.mock('@/api/client', () => ({ getSeries: h.getSeries }));

import { useUI } from '@/store/ui';
import { ChartCards } from './ChartCards';

const ASOF = '2026-06-08';
const SESSION = '2026-06-05';

const CURVE_SERIES = {
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
const TIME_SERIES = {
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

const CURVE_LOOKUP = {
  ref: 'N1',
  handle: 'L1',
  status: 'ok',
  query: {
    table: 'silver_futures_eod',
    metric: 'settle',
    commodity: 'corn_cbot',
    contract_month: '2026-07,2026-12,2027-03',
    agg: 'latest',
  },
  rows: CURVE_SERIES.points.map((p) => ({ value: p.value, contract_month: p.contract_month })),
};
const SPREAD = {
  query: { table: 'compute_stat', metric: 'spread' },
  rows: [{ value: '44.0', unit: 'spread' }],
  status: 'ok',
  stat_provenance: { stat: 'spread', params: {}, input_handles: ['L1'] },
};
const PERIOD_LOOKUP = {
  ref: 'N2',
  handle: 'L2',
  status: 'ok',
  query: { table: 'silver_psd', metric: 'exports', commodity: 'soybeans', agg: 'series' },
  rows: [{ value: '12.0', period: '2023' }],
};
const WINDOW = {
  query: { table: 'compute_stat', metric: 'window_change' },
  rows: [{ value: '2.0', unit: 'kt' }],
  status: 'ok',
  stat_provenance: { stat: 'window_change', params: {}, input_handles: ['L2'] },
};

const comoveCall = (commodity: string, period: string, value: string, unit = '%') => ({
  query: { commodity, metric: 'su_ratio_world', period, asof: ASOF },
  rows: [{ value, unit }],
  status: 'ok',
});
const COMOVE = {
  number_calls: [
    comoveCall('soybean_oil_cbot', 'MY2018', '14.8'),
    comoveCall('soybean_oil_cbot', 'MY2020', '11.2'),
    comoveCall('soybean_oil_cbot', 'MY2020', '-3.6', 'pp'),
    comoveCall('malaysian_crude_palm_oil_cme', 'MY2018', '12.1'),
    comoveCall('malaysian_crude_palm_oil_cme', 'MY2020', '9.4'),
  ],
  trace: {
    quantify_comove: {
      commodityA: 'soybean_oil_cbot',
      commodityB: 'malaysian_crude_palm_oil_cme',
      window: 'MY2018-MY2020',
      comove: true,
    },
  },
};

function mount(result: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ChartCards result={result} asof={ASOF} />
    </QueryClientProvider>,
  );
}

describe('ChartCards — zero triggers is ZERO bytes (D-UX-3)', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(TIME_SERIES);
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('renders literally nothing, and fetches nothing, when the turn earned no chart', () => {
    // The byte-identity guarantee: this component contributes no DOM node at all, so an answer with no
    // chartable leg is exactly the answer that rendered before this wave.
    const { container } = mount({ number_calls: [PERIOD_LOOKUP], trace: {} });
    expect(container.innerHTML).toBe('');
    expect(h.getSeries).not.toHaveBeenCalled();
  });

  it('the same holds for a turn with no numbers at all', () => {
    expect(mount({ number_calls: [], trace: {} }).container.innerHTML).toBe('');
    expect(mount(null).container.innerHTML).toBe('');
  });
});

describe('ChartCards — the curve/carry card', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(CURVE_SERIES);
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('fetches the curve at the TURN\'S as-of and draws it', async () => {
    mount({ number_calls: [CURVE_LOOKUP, SPREAD], trace: {} });
    await waitFor(() => expect(h.getSeries).toHaveBeenCalledTimes(1));
    expect(h.getSeries.mock.calls[0]).toEqual([
      'silver_futures_eod',
      'settle',
      {
        commodity: 'corn_cbot',
        country: undefined,
        asof: ASOF, // PIT: the same rows the answer cited, never a fresher read
        contractMonth: '2026-07,2026-12,2027-03',
        agg: 'latest',
      },
    ]);
    expect(await screen.findByRole('img', { name: /settle curve/i })).toBeInTheDocument();
  });

  it('collapses without unmounting the answer around it', async () => {
    mount({ number_calls: [CURVE_LOOKUP, SPREAD], trace: {} });
    expect(await screen.findByRole('img', { name: /settle curve/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { expanded: true }));
    expect(screen.queryByRole('img', { name: /settle curve/i })).not.toBeInTheDocument();
    expect(screen.getByTestId('chart-card')).toBeInTheDocument();
  });

  it('"open in tab" pushes a chart tab carrying the card\'s own locator', async () => {
    mount({ number_calls: [CURVE_LOOKUP, SPREAD], trace: {} });
    await userEvent.click(await screen.findByTestId('chart-card-open-tab'));
    const tabs = useUI.getState().tabs;
    expect(tabs).toHaveLength(1);
    expect(tabs[0]!.kind).toBe('chart');
    expect(tabs[0]!.params).toEqual({
      table: 'silver_futures_eod',
      metric: 'settle',
      commodity: 'corn_cbot',
      axis: 'curve',
      asof: ASOF,
      contract_month: '2026-07,2026-12,2027-03',
    });
  });

  it('a failed card says so and retries in place', async () => {
    h.getSeries.mockRejectedValue(new Error('502'));
    mount({ number_calls: [CURVE_LOOKUP, SPREAD], trace: {} });
    expect(await screen.findByText(/couldn.t load this chart/i)).toBeInTheDocument();
    h.getSeries.mockResolvedValue(CURVE_SERIES);
    await userEvent.click(screen.getByRole('button', { name: 'retry' }));
    expect(await screen.findByRole('img', { name: /settle curve/i })).toBeInTheDocument();
  });

  it('a card whose fetch comes back too short says so rather than showing an empty frame', async () => {
    h.getSeries.mockResolvedValue({ ...CURVE_SERIES, points: [CURVE_SERIES.points[0]] });
    mount({ number_calls: [CURVE_LOOKUP, SPREAD], trace: {} });
    expect(await screen.findByText(/nothing to plot/i)).toBeInTheDocument();
  });
});

describe('ChartCards — the series card', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(TIME_SERIES);
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('draws the period series the window stat walked, with its as-of marker', async () => {
    mount({ number_calls: [PERIOD_LOOKUP, WINDOW], trace: {} });
    expect(await screen.findByRole('img', { name: /exports series/i })).toBeInTheDocument();
    // the vintage line is the as-of marker SeriesChart draws on the time axis
    expect(document.querySelectorAll('svg line.stroke-cyan').length).toBeGreaterThan(0);
    expect(h.getSeries.mock.calls[0]![2]).toEqual({
      commodity: 'soybeans',
      country: undefined,
      asof: ASOF,
    });
  });
});

describe('ChartCards — the co-move overlay card', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(TIME_SERIES);
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('draws both legs and fetches NOTHING — the rows are the turn\'s own', async () => {
    mount(COMOVE);
    expect(await screen.findByTestId('overlay-chart')).toBeInTheDocument();
    expect(h.getSeries).not.toHaveBeenCalled();
  });

  it('offers no tab, and says why, rather than minting a locator that does not exist', () => {
    // World stocks-to-use is synthesized across countries (no stored World row), so any locator here would
    // open either an empty tab or a per-country blob wearing the World label.
    mount(COMOVE);
    expect(screen.queryByTestId('chart-card-open-tab')).toBeNull();
    expect(screen.getByTestId('overlay-no-tab').textContent).toMatch(/synthesized across countries/);
  });
});

describe('ChartCards — cap + priority under one answer', () => {
  beforeEach(() => {
    h.getSeries.mockReset().mockResolvedValue(CURVE_SERIES);
    useUI.setState({ tabs: [], activeTabId: null });
  });

  it('never renders more than two cards, curve first', async () => {
    mount({
      number_calls: [CURVE_LOOKUP, SPREAD, PERIOD_LOOKUP, WINDOW, ...COMOVE.number_calls],
      trace: COMOVE.trace,
    });
    const cards = await screen.findAllByTestId('chart-card');
    expect(cards).toHaveLength(2);
    expect(cards.map((c) => c.getAttribute('data-kind'))).toEqual(['curve', 'overlay']);
  });
});
