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
 *  picks that scratch node up as a phantom first tick. Scoped to `.visx-axis-bottom` for a second reason
 *  since D-UX-5: the chart now draws a LEFT axis too, and an svg-wide `text` query returns both axes'
 *  labels interleaved -- which is what these assertions would silently start passing over. */
const ticks = (name: string) =>
  [...screen.getByRole('img', { name }).querySelectorAll('.visx-axis-bottom text')].map((t) => t.textContent);

/** The y-axis tick labels of one chart -- the magnitudes M.l reserved room for since the first commit. */
const yTicks = (name: string) =>
  [...screen.getByRole('img', { name }).querySelectorAll('.visx-axis-left text')].map((t) => t.textContent);

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
    // `stroke-asof` / `fill-asof` are the as-of line and the known-at-as-of dot (D-UX-5 moved them off
    // `--cyan`, the swappable accent). Neither means anything on an expiry axis: there is no "what was
    // known then" ordering among delivery months, and no as-of legend either.
    render(<SeriesChart series={CURVE} asof={ASOF} axis="curve" />);
    expect(document.querySelectorAll('.stroke-asof, .fill-asof')).toHaveLength(0);
    expect(screen.queryByTestId('series-asof-legend')).not.toBeInTheDocument();
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

describe('SeriesChart D-UX-5 — magnitudes, the mono token, and a NAMED as-of line', () => {
  it('draws the LEFT axis M.l reserved room for -- a shape with no magnitudes is not a chart', () => {
    render(<SeriesChart series={TIME} asof={ASOF} />);
    // 10.0 -> 12.0 over a `nice()` domain: the reader can now read the level off the picture instead of
    // recovering it from the [N#] row above.
    const labels = yTicks('exports series');
    expect(labels.length).toBeGreaterThan(0);
    expect(labels.every((t) => /^-?[\d.]+[kMB]?$/.test(t ?? ''))).toBe(true);
  });

  it('the curve axis gets the same left axis (its magnitudes are prices)', () => {
    render(<SeriesChart series={CURVE} asof={ASOF} axis="curve" />);
    expect(yTicks('settle curve').length).toBeGreaterThan(0);
  });

  it('every tick label is drawn in the MONO TOKEN, never the platform `monospace`', () => {
    // The three hard-coded `fontFamily: 'monospace'` sites bypassed the IBM Plex Mono stack, so a chart's
    // numerals were a different face from the [N#] row beside them.
    render(<SeriesChart series={TIME} asof={ASOF} />);
    const label = screen.getByRole('img', { name: 'exports series' }).querySelector('text');
    expect(label?.getAttribute('font-family') ?? (label as SVGTextElement).style.fontFamily).toContain(
      'IBM Plex Mono',
    );
  });

  it('NAMES the as-of line, so the marker is not read as a vintage', () => {
    // /v1/series has already collapsed to the latest vintage <= asof, so this line lands on the last point
    // of essentially every time chart -- drawn bare it reads as "this point was revised", which is the one
    // thing it does not mean.
    render(<SeriesChart series={TIME} asof={ASOF} />);
    const legend = screen.getByTestId('series-asof-legend');
    expect(legend.textContent).toContain('as-of line');
    expect(legend.textContent).toContain(ASOF);
    expect(legend.textContent).toContain('not a vintage marker');
    // and the same sentence rides the line itself for a reader who hovers it
    const line = screen.getByRole('img', { name: 'exports series' }).querySelector('line.stroke-asof title');
    expect(line?.textContent).toContain('not a revision marker');
  });

  it('the as-of ink is a DATA token, not the swappable accent', () => {
    render(<SeriesChart series={TIME} asof={ASOF} />);
    const svg = screen.getByRole('img', { name: 'exports series' });
    expect(svg.querySelectorAll('line.stroke-asof')).toHaveLength(1);
    expect(svg.querySelectorAll('.stroke-cyan, .fill-cyan')).toHaveLength(0);
  });
});
