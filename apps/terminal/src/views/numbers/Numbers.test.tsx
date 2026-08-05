import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Only the series fetch is mocked; the row, its key and its expansion states are the real component.
const h = vi.hoisted(() => ({ getSeries: vi.fn() }));
vi.mock('@/api/client', () => ({ getSeries: h.getSeries }));

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
