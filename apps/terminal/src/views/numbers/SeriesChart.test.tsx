import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { components } from '@/api/types.gen';
import { SeriesChart } from './SeriesChart';

type Series = components['schemas']['Series'];

const SESSION = '2026-06-05';
const ASOF = '2026-06-08';

/** A corn term structure at ONE session, as the curve read returns it: one row per delivery month, no
 *  `period` alias anywhere (silver_futures_eod does not surface one) and the session on `knowledge_date`. */
const CURVE: Series = {
  table: 'silver_futures_eod',
  metric: 'settle',
  commodity: 'corn_cbot',
  asof: ASOF,
  unit: 'US cents/bushel',
  points: [
    { contract_month: '2027-03', value: '461.5', knowledge_date: SESSION },
    { contract_month: '2026-07', value: '417.5', knowledge_date: SESSION },
    { contract_month: '2026-12', value: '446.0', knowledge_date: SESSION },
    { contract_month: '2026-09', value: '427.0', knowledge_date: SESSION },
  ],
};

/** The pre-wave shape: a PSD series with marketing-year periods. */
const TIME: Series = {
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

/** The x-axis tick LABELS of one chart. Scoped to the chart's own `<svg>` on purpose: @visx/text measures
 *  strings by rendering them into a throwaway svg it appends to the document, so a document-wide query
 *  picks that scratch node up as a phantom first tick. */
const ticks = (name: string) =>
  [...screen.getByRole('img', { name }).querySelectorAll('text')].map((t) => t.textContent);

describe('SeriesChart time axis (unchanged)', () => {
  it('draws the period axis and the vintage marker, with no curve header', () => {
    render(<SeriesChart series={TIME} asof={ASOF} />);
    expect(screen.getByRole('img', { name: 'exports series' })).toBeInTheDocument();
    expect(ticks('exports series')).toEqual(['2022', '2023']);
    expect(screen.queryByTestId('curve-chart')).not.toBeInTheDocument();
  });

  it('omitting `axis` is the same render as passing the default', () => {
    // The pre-wave call site passes no `axis`; it must keep drawing the exact markup it drew before.
    const { container, unmount } = render(<SeriesChart series={TIME} asof={ASOF} />);
    const bare = container.innerHTML;
    unmount();
    const { container: c2 } = render(<SeriesChart series={TIME} asof={ASOF} axis="time" />);
    expect(c2.innerHTML).toBe(bare);
  });

  it('still draws nothing below two points', () => {
    const { container } = render(
      <SeriesChart series={{ ...TIME, points: [TIME.points[0]!] }} asof={ASOF} />,
    );
    expect(container.innerHTML).toBe('');
  });
});

describe('SeriesChart curve axis (D-AM-21)', () => {
  it('domains the x axis on the ORDERED delivery months, not on time', () => {
    // The whole point of the mode: nearest -> deferred left to right, so a rising line reads as carry and
    // a falling one as backwardation. The fixture arrives out of order to prove the chart orders it.
    render(<SeriesChart series={CURVE} asof={ASOF} axis="curve" />);
    expect(ticks('settle curve')).toEqual(['2026-07', '2026-09', '2026-12', '2027-03']);
  });

  it('labels the as-of in the header, taken from the ROWS rather than the caller', () => {
    // The as-of is a PIT cutoff (2026-06-08); the session is what the exchange actually printed on or
    // before it (2026-06-05). A curve has no time axis, so the header is the only place this can be said.
    render(<SeriesChart series={CURVE} asof={ASOF} axis="curve" />);
    const header = screen.getByTestId('curve-chart').firstChild as HTMLElement;
    expect(header.textContent).toContain(SESSION);
    expect(header.textContent).toContain('4 expiries');
    expect(header.textContent).toContain('US cents/bushel');
    expect(header.textContent).not.toContain(ASOF);
  });

  it('takes the unit off the ROWS when the envelope has none, and only when they agree', () => {
    // silver_futures_eod's `settle` declares no registry unit: its serving unit is the per-contract
    // override the server stamps onto each row. Ten currencies share the card, so an unlabelled 446.0 is
    // exactly the figure the card's notes forbid quoting.
    const rows = CURVE.points.map((p) => ({ ...p, unit: 'US cents/bushel' }));
    render(<SeriesChart series={{ ...CURVE, unit: '', points: rows }} asof={ASOF} axis="curve" />);
    expect(screen.getByTestId('curve-chart').textContent).toContain('US cents/bushel');
  });

  it('shows NO unit when the rows disagree, rather than picking one', () => {
    const rows = CURVE.points.map((p, i) => ({ ...p, unit: i ? 'US cents/bushel' : 'USD/bushel' }));
    const { container } = render(
      <SeriesChart series={{ ...CURVE, unit: '', points: rows }} asof={ASOF} axis="curve" />,
    );
    expect(container.textContent).not.toContain('bushel');
  });

  it('says MIXED SESSIONS rather than labelling the picture with a date true of only some of it', () => {
    const mixed = {
      ...CURVE,
      points: [CURVE.points[0]!, { ...CURVE.points[1]!, knowledge_date: '2026-06-04' }],
    };
    render(<SeriesChart series={mixed} asof={ASOF} axis="curve" />);
    expect(screen.getByTestId('curve-chart').textContent).toContain('MIXED sessions');
  });

  it('carries a curve-labelled role so the picture is never read as a time series', () => {
    render(<SeriesChart series={CURVE} asof={ASOF} axis="curve" />);
    expect(screen.getByRole('img', { name: 'settle curve' })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'settle series' })).not.toBeInTheDocument();
  });

  it('draws no vintage marker -- every point is the same session', () => {
    // `stroke-cyan` / `fill-cyan` are the vintage line and the known-at-as-of dot. Neither means anything
    // on an expiry axis: there is no "what was known then" ordering among delivery months.
    render(<SeriesChart series={CURVE} asof={ASOF} axis="curve" />);
    expect(document.querySelectorAll('.stroke-cyan, .fill-cyan')).toHaveLength(0);
    expect(document.querySelectorAll('svg circle')).toHaveLength(4);
  });

  it('draws nothing when fewer than two expiries survive', () => {
    const { container } = render(
      <SeriesChart series={{ ...CURVE, points: [CURVE.points[0]!] }} asof={ASOF} axis="curve" />,
    );
    expect(container.innerHTML).toBe('');
  });

  it('drops rows with no delivery month rather than stacking them on one x', () => {
    // The two CEPEA cash references carry a NULL contract_month by design; they are not curve points.
    const withCash = { ...CURVE, points: [...CURVE.points, { value: '9.9', knowledge_date: SESSION }] };
    render(<SeriesChart series={withCash} asof={ASOF} axis="curve" />);
    expect(ticks('settle curve')).toEqual(['2026-07', '2026-09', '2026-12', '2027-03']);
    expect(document.querySelectorAll('svg circle')).toHaveLength(4);
  });
});
