import { describe, expect, it } from 'vitest';
import { chartTitle, deriveChartCards, seriesQueryKey } from './chartTriggers';

const ASOF = '2026-06-08';

/** A LOOKUP call as the agent emits it: the echoed spec (which always carries `agg`), the rows, and the
 *  turn-scoped `handle` the agent mutates onto the same dict it appended to `calls`. */
function lookup(handle: string, query: Record<string, unknown>, rows: Record<string, unknown>[] = []) {
  return { ref: `N${handle.slice(1)}`, handle, status: 'ok', query: { agg: 'latest', ...query }, rows };
}

/** An INJECTED stat row: table=compute_stat, metric=the stat, and the provenance naming its input handles.
 *  It carries no handle of its own (the chaining handle rides the tool-result payload, not the [N] row). */
function stat(name: string, inputs: string[], value = '12.5') {
  return {
    query: { table: 'compute_stat', metric: name },
    rows: [{ value, unit: name === 'spread' ? 'spread' : 'kt' }],
    status: 'ok',
    stat_provenance: { stat: name, params: {}, input_handles: inputs },
  };
}

const CURVE_LOOKUP = lookup(
  'L1',
  {
    table: 'silver_futures_eod',
    metric: 'settle',
    commodity: 'corn_cbot',
    contract_month: '2026-07,2026-12,2027-03',
  },
  [
    { value: '417.5', contract_month: '2026-07' },
    { value: '446.0', contract_month: '2026-12' },
    { value: '461.5', contract_month: '2027-03' },
  ],
);

const PERIOD_LOOKUP = lookup(
  'L2',
  { table: 'silver_psd', metric: 'exports', commodity: 'soybeans', country: 'Brazil', agg: 'series' },
  [
    { value: '10.0', period: '2022' },
    { value: '12.0', period: '2023' },
  ],
);

describe('deriveChartCards — no trigger, no card (D-UX-3)', () => {
  it('a turn with no calls and no trace earns nothing', () => {
    expect(deriveChartCards({ number_calls: [], trace: {} }, ASOF)).toEqual([]);
    expect(deriveChartCards(null, ASOF)).toEqual([]);
    expect(deriveChartCards({}, ASOF)).toEqual([]);
  });

  it('ordinary lookups alone earn nothing — a read is not a computation', () => {
    // The rule the whole feature rests on: a chart appears because a deterministic LEG computed something,
    // not because the turn happened to touch a table with numbers in it.
    expect(deriveChartCards({ number_calls: [PERIOD_LOOKUP], trace: {} }, ASOF)).toEqual([]);
  });

  it('survives junk in number_calls rather than throwing under a finished answer', () => {
    expect(deriveChartCards({ number_calls: [null, 'nope', 7, {}], trace: {} }, ASOF)).toEqual([]);
    expect(deriveChartCards({ number_calls: 'not-an-array', trace: 'nope' }, ASOF)).toEqual([]);
  });
});

describe('deriveChartCards — curve/carry trigger', () => {
  it('a spread stat mints a curve card locating the read it was computed over', () => {
    const cards = deriveChartCards(
      { number_calls: [CURVE_LOOKUP, stat('spread', ['L1'])], trace: {} },
      ASOF,
    );
    expect(cards).toHaveLength(1);
    expect(cards[0]!.kind).toBe('curve');
    expect(cards[0]!.reason).toMatch(/spread/);
    expect((cards[0] as { locator: unknown }).locator).toEqual({
      table: 'silver_futures_eod',
      metric: 'settle',
      commodity: 'corn_cbot',
      axis: 'curve',
      asof: ASOF, // the TURN's as-of, never a fresher one
      contract_month: '2026-07,2026-12,2027-03',
    });
  });

  it('a bare multi-month agg=latest read is itself a curve card', () => {
    const cards = deriveChartCards({ number_calls: [CURVE_LOOKUP], trace: {} }, ASOF);
    expect(cards.map((c) => c.kind)).toEqual(['curve']);
    expect(cards[0]!.reason).toMatch(/term structure/);
  });

  it('the spread and its own source read collapse to ONE card, not two of the same picture', () => {
    const cards = deriveChartCards(
      { number_calls: [CURVE_LOOKUP, stat('spread', ['L1'])], trace: {} },
      ASOF,
    );
    expect(cards).toHaveLength(1);
  });

  it('an INTERLEAVED (agg=series) futures read is NOT a curve', () => {
    // Many expiries x many sessions is the curve-as-calendar shape query.py refuses to walk positionally;
    // drawn on a delivery-month axis it would stack a dozen sessions on each tick and read as a term
    // structure. Same rows, same months -- only `agg` distinguishes them, which is why it is checked.
    const blob = { ...CURVE_LOOKUP, query: { ...CURVE_LOOKUP.query, agg: 'series' } };
    expect(deriveChartCards({ number_calls: [blob], trace: {} }, ASOF)).toEqual([]);
  });

  it('a single named delivery month is not a term structure', () => {
    const one = lookup(
      'L1',
      { table: 'silver_futures_eod', metric: 'settle', commodity: 'corn_cbot', contract_month: '2026-12' },
      [{ value: '446.0', contract_month: '2026-12' }],
    );
    expect(deriveChartCards({ number_calls: [one], trace: {} }, ASOF)).toEqual([]);
  });

  it('a spread whose source handle resolves to nothing mints NO card (fails closed)', () => {
    // A stat chained off another stat references a handle no lookup call carries. Guessing which read
    // underneath was "the real one" would draw a series the answer never stood on.
    expect(deriveChartCards({ number_calls: [stat('spread', ['L9'])], trace: {} }, ASOF)).toEqual([]);
    expect(deriveChartCards({ number_calls: [CURVE_LOOKUP, stat('spread', [])], trace: {} }, ASOF)).toHaveLength(
      1, // only the standalone curve read, not a second card off the handle-less stat
    );
  });
});

describe('deriveChartCards — window-stat series trigger', () => {
  it('a window_change over a period series mints a time-axis card locating that series', () => {
    const cards = deriveChartCards(
      { number_calls: [PERIOD_LOOKUP, stat('window_change', ['L2'])], trace: {} },
      ASOF,
    );
    expect(cards).toHaveLength(1);
    expect(cards[0]!.kind).toBe('series');
    expect((cards[0] as { locator: unknown }).locator).toEqual({
      table: 'silver_psd',
      metric: 'exports',
      commodity: 'soybeans',
      country: 'Brazil', // D-TW-9: country rides the locator, or the card draws a different series
      axis: 'time',
      asof: ASOF,
    });
  });

  it('a zscore does the same', () => {
    const cards = deriveChartCards(
      { number_calls: [PERIOD_LOOKUP, stat('zscore', ['L2'])], trace: {} },
      ASOF,
    );
    expect(cards.map((c) => c.kind)).toEqual(['series']);
    expect(cards[0]!.reason).toMatch(/zscore/);
  });

  it('a stat that is neither a window walk nor a spread mints nothing', () => {
    expect(
      deriveChartCards({ number_calls: [PERIOD_LOOKUP, stat('extrema_min', ['L2'])], trace: {} }, ASOF),
    ).toEqual([]);
  });

  it('a window stat over a CURVE read gets no series card', () => {
    // That combination is the curve-as-calendar shape the engine's own S4 guard declines; a time axis is
    // the wrong picture for it, and there is no honest series to draw.
    expect(
      deriveChartCards({ number_calls: [CURVE_LOOKUP, stat('window_change', ['L1'])], trace: {} }, ASOF),
    ).toHaveLength(1);
    expect(
      deriveChartCards({ number_calls: [CURVE_LOOKUP, stat('window_change', ['L1'])], trace: {} }, ASOF)[0]!
        .kind,
    ).toBe('curve');
  });
});

// ── the co-move overlay ────────────────────────────────────────────────────────────────────────────
// The engine injects THREE rows per leg (cascade.py `_xc_leg_lines`): the endpoint and the baseline in
// '%', and the within-window delta in 'pp'. Only the two '%' rows are points on a stocks-to-use axis.
function comoveCall(commodity: string, period: string, value: string, unit = '%') {
  return { query: { commodity, metric: 'su_ratio_world', period, asof: ASOF }, rows: [{ value, unit }], status: 'ok' };
}

const COMOVE_CALLS = [
  comoveCall('soybean_oil_cbot', 'MY2020', '11.2'),
  comoveCall('soybean_oil_cbot', 'MY2018', '14.8'),
  comoveCall('soybean_oil_cbot', 'MY2020', '-3.6', 'pp'),
  comoveCall('malaysian_crude_palm_oil_cme', 'MY2020', '9.4'),
  comoveCall('malaysian_crude_palm_oil_cme', 'MY2018', '12.1'),
  comoveCall('malaysian_crude_palm_oil_cme', 'MY2020', '-2.7', 'pp'),
];
const COMOVE_TRACE = {
  quantify_comove: {
    pair_id: 'vegoil_1',
    commodityA: 'soybean_oil_cbot',
    commodityB: 'malaysian_crude_palm_oil_cme',
    window: 'MY2018-MY2020',
    comove: true,
  },
};

describe('deriveChartCards — co-move overlay trigger', () => {
  it('builds both legs from the turn\'s OWN injected rows, dropping the pp delta row', () => {
    const cards = deriveChartCards({ number_calls: COMOVE_CALLS, trace: COMOVE_TRACE }, ASOF);
    expect(cards).toHaveLength(1);
    const c = cards[0] as { kind: string; legs: { label: string; unit: string; points: unknown[] }[]; window: string };
    expect(c.kind).toBe('overlay');
    expect(c.window).toBe('MY2018-MY2020');
    expect(c.legs.map((l) => l.label)).toEqual(['soybean oil cbot', 'malaysian crude palm oil cme']);
    // 2 points per leg -- the third injected row is the DELTA between them, not a third observation.
    expect(c.legs.map((l) => l.points.length)).toEqual([2, 2]);
    expect(c.legs[0]!.points).toEqual([
      { period: 'MY2018', value: 14.8, knowledge_date: '', contract_month: '' },
      { period: 'MY2020', value: 11.2, knowledge_date: '', contract_month: '' },
    ]);
    expect(c.legs.every((l) => l.unit === '%')).toBe(true);
  });

  it('the trace alone earns nothing — without the injected rows there is nothing honest to draw', () => {
    expect(deriveChartCards({ number_calls: [], trace: COMOVE_TRACE }, ASOF)).toEqual([]);
  });

  it('a leg with only one usable point earns nothing (fails closed)', () => {
    const thin = COMOVE_CALLS.filter((c) => !(c.query.commodity === 'soybean_oil_cbot' && c.query.period === 'MY2018'));
    expect(deriveChartCards({ number_calls: thin, trace: COMOVE_TRACE }, ASOF)).toEqual([]);
  });

  it('an OPPOSITE-sign divergence (quantify_reroute_v2) is not a co-move and draws no overlay', () => {
    // The engine routes the two forks to DIFFERENT trace keys on purpose; only the co-move one is a
    // "these moved together" claim an overlay can support.
    const rv2 = { quantify_reroute_v2: { ...COMOVE_TRACE.quantify_comove, comove: undefined, reroute_v2: true } };
    expect(deriveChartCards({ number_calls: COMOVE_CALLS, trace: rv2 }, ASOF)).toEqual([]);
  });
});

describe('deriveChartCards — priority + cap', () => {
  const all = {
    number_calls: [CURVE_LOOKUP, stat('spread', ['L1']), PERIOD_LOOKUP, stat('zscore', ['L2']), ...COMOVE_CALLS],
    trace: COMOVE_TRACE,
  };

  it('caps at two cards, curve > overlay > series', () => {
    const cards = deriveChartCards(all, ASOF);
    expect(cards.map((c) => c.kind)).toEqual(['curve', 'overlay']);
  });

  it('the series card is reached only when nothing higher fired', () => {
    const cards = deriveChartCards(
      { number_calls: [PERIOD_LOOKUP, stat('zscore', ['L2'])], trace: {} },
      ASOF,
    );
    expect(cards.map((c) => c.kind)).toEqual(['series']);
  });

  it('two different curve reads are two cards, and no more than two', () => {
    const second = lookup(
      'L3',
      {
        table: 'silver_futures_eod',
        metric: 'settle',
        commodity: 'soybeans_cbot',
        contract_month: '2026-08,2026-11',
      },
      [],
    );
    const cards = deriveChartCards(
      { number_calls: [CURVE_LOOKUP, second, PERIOD_LOOKUP, stat('zscore', ['L2'])], trace: {} },
      ASOF,
    );
    expect(cards).toHaveLength(2);
    expect(cards.every((c) => c.kind === 'curve')).toBe(true);
  });
});

describe('locator plumbing', () => {
  it('the time key family is Numbers.tsx\'s series key, field for field', () => {
    // Numbers.tsx: ['series', table, metric, commodity, country, asof]. If that ever drifts, this fails
    // instead of the cache silently splitting and the same picture being fetched twice.
    expect(
      seriesQueryKey({ table: 't', metric: 'm', commodity: 'c', country: 'k', axis: 'time', asof: ASOF }),
    ).toEqual(['series', 't', 'm', 'c', 'k', ASOF]);
  });

  it('the curve key family is Numbers.tsx\'s curve key, months included', () => {
    // Numbers.tsx: ['curve', table, metric, commodity, country, asof, months.join(',')].
    expect(
      seriesQueryKey({
        table: 't',
        metric: 'm',
        commodity: 'c',
        country: undefined,
        contract_month: '2026-07,2026-12',
        axis: 'curve',
        asof: ASOF,
      }),
    ).toEqual(['curve', 't', 'm', 'c', undefined, ASOF, '2026-07,2026-12']);
  });

  it('titles read as prose, and a curve says it is one', () => {
    expect(chartTitle({ table: 'silver_futures_eod', metric: 'settle', commodity: 'corn_cbot', axis: 'curve', asof: ASOF })).toBe(
      'corn cbot settle curve',
    );
    expect(chartTitle({ table: 'silver_oni', metric: 'oni', axis: 'time', asof: ASOF })).toBe('silver oni oni');
  });
});
