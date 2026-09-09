import * as Tooltip from '@radix-ui/react-tooltip';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { tabKey } from '@/store/tabs';
import { useUI } from '@/store/ui';
import { seriesQueryKey } from '@/views/numbers/chartTriggers';
import { CitationChip } from './CitationChip';
import type { ResolvedCite } from './citations';

const ASOF = '2026-06-08';

/** The number citation the server mints (citations.py:1564): the read's own query, scope included. */
const NUMBER: ResolvedCite = {
  source: 'USDA PSD',
  date: '2026-06-11',
  locator: {
    kind: 'number',
    table: 'silver_psd',
    metric: 'exports',
    commodity: 'soybeans',
    country: 'Brazil',
    period: '2023',
    asof: ASOF,
  },
};

function mount(refId: string, resolved: ResolvedCite) {
  return render(
    <Tooltip.Provider delayDuration={0}>
      <CitationChip refId={refId} resolved={resolved} onOpen={null} />
    </Tooltip.Provider>,
  );
}

/** Hovering the chip is what reveals the tooltip's actions (the Radix content is portalled on open).
 *  Returns the VISIBLE content node: Radix also renders a screen-reader duplicate of the same children, so
 *  every assertion below is scoped to this element rather than to the document. */
async function tip(refId: string, resolved: ResolvedCite) {
  const user = userEvent.setup();
  mount(refId, resolved);
  await user.hover(screen.getByTestId('cite-chip'));
  return screen.findByRole('tooltip');
}

describe('D-UX-5 — an [N] chip opens the chart it was read from', () => {
  beforeEach(() => useUI.setState({ tabs: [], activeTabId: null }));

  it('opens the SAME series the row was read from — scope and as-of included', async () => {
    const user = userEvent.setup();
    const t = await tip('N4', NUMBER);
    await user.click(within(t).getByTestId('cite-open-chart'));

    const tabs = useUI.getState().tabs;
    expect(tabs).toHaveLength(1);
    expect(tabs[0]!.kind).toBe('chart');
    // country RIDES (D-TW-9): the row's value came from a Brazil-scoped read, and an unscoped series is a
    // different series under the same [N#]. `period` and `kind` are citation fields, not series arguments.
    expect(tabs[0]!.params).toEqual({
      table: 'silver_psd',
      metric: 'exports',
      commodity: 'soybeans',
      country: 'Brazil',
      axis: 'time',
      asof: ASOF, // PIT: the read's own cutoff, never today
    });
    expect(tabs[0]!.id).toBe(tabKey('chart', tabs[0]!.params));
  });

  it('is the SAME fetch the Numbers row makes — one locator builder, one cache entry', () => {
    // The parity that makes this a third click site rather than a second definition of "a series read":
    // the chip's locator resolves to the key family Numbers.tsx and ChartTab already share.
    const loc = {
      table: 'silver_psd',
      metric: 'exports',
      commodity: 'soybeans',
      country: 'Brazil',
      axis: 'time',
      asof: ASOF,
    } as const;
    expect(seriesQueryKey(loc)).toEqual(['series', 'silver_psd', 'exports', 'soybeans', 'Brazil', ASOF]);
  });

  it('draws the LEVEL series when the row wore a synthesized reader-word metric', async () => {
    // citations.py rides `source_metric` "so a client can draw the level series instead": the reader-word
    // metric is declared by no card and /v1/series 400s on it.
    const user = userEvent.setup();
    const t = await tip('N7', {
      ...NUMBER,
      locator: { ...NUMBER.locator, metric: 'monthly benchmark change', source_metric: 'price_nominal' },
    });
    await user.click(within(t).getByTestId('cite-open-chart'));
    expect((useUI.getState().tabs[0]!.params as { metric: string }).metric).toBe('price_nominal');
  });

  it('opens the CURVE when the quoted row named several delivery months', async () => {
    const user = userEvent.setup();
    const t = await tip('N9', {
      ...NUMBER,
      locator: {
        kind: 'number',
        table: 'silver_futures_eod',
        metric: 'settle',
        commodity: 'corn_cbot',
        contract_month: '2026-07,2026-12',
        asof: ASOF,
      },
    });
    await user.click(within(t).getByTestId('cite-open-chart'));
    expect(useUI.getState().tabs[0]!.params).toEqual({
      table: 'silver_futures_eod',
      metric: 'settle',
      commodity: 'corn_cbot',
      contract_month: '2026-07,2026-12',
      axis: 'curve',
      asof: ASOF,
    });
  });

  it('a row with NO drawable series keeps today’s behaviour: no button, not a dead one', async () => {
    // compute_stat is the belt's pseudo-table -- a computed figure with no table, no scope and nothing to
    // fetch. Same for a locator carrying no as-of: an unpinned chart would draw the current vintage.
    const t1 = await tip('N2', { ...NUMBER, locator: { kind: 'number', table: 'compute_stat', metric: 'window_change', asof: ASOF } });
    expect(within(t1).queryByTestId('cite-open-chart')).toBeNull();
    expect(t1.textContent).toContain('compute_stat'); // the provenance line is untouched
    cleanup();

    // ...and a locator carrying no as-of: an unpinned chart would draw the CURRENT vintage under a figure
    // the answer stated at some other horizon.
    const t2 = await tip('N3', { ...NUMBER, locator: { kind: 'number', table: 'silver_psd', metric: 'exports' } });
    expect(within(t2).queryByTestId('cite-open-chart')).toBeNull();
  });

  it('an EVIDENCE chip is untouched: it opens its PDF and offers no chart', async () => {
    const t = await tip('4', {
      source: 'USDA FAS GAIN Report',
      date: '2021-07-20',
      text: 'a damaging frost',
      locator: { kind: 'doc', source_key: 's3://gain/kc', snippet: 'a damaging frost' },
    });
    expect(t.textContent).toContain('open PDF');
    expect(within(t).queryByTestId('cite-open-chart')).toBeNull();
  });
});
