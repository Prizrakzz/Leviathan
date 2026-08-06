import { describe, expect, it } from 'vitest';
import { MOCK_SERIES } from '@/api/mock';
import {
  axisKey,
  curvePoints,
  curveSession,
  isAnomaly,
  parsePoints,
  sparkPath,
  trackedMonths,
  vintageIndex,
} from './scale';

/** A futures row as the server returns it: NO `period` and NO `date` (silver_futures_eod surfaces neither
 *  alias), a delivery month, and the session under `knowledge_date`. */
const futuresRow = (contract_month: string, value: string, knowledge_date = '2026-06-05') => ({
  contract_month,
  value,
  knowledge_date,
});

describe('numbers scaling', () => {
  it('parses string values to numeric points, dropping empties', () => {
    const pts = parsePoints(MOCK_SERIES.points as Record<string, unknown>[]);
    expect(pts).toHaveLength(6);
    expect(pts[5]).toMatchObject({ period: '2021', value: 0.36 });
  });

  it('sparkPath spans the width and emits one command per point', () => {
    const d = sparkPath([1, 2, 3, 2], 90, 18);
    expect(d.startsWith('M')).toBe(true);
    expect((d.match(/[ML]/g) ?? []).length).toBe(4);
  });

  it('vintageIndex is the last point known at/before the as-of', () => {
    const pts = parsePoints(MOCK_SERIES.points as Record<string, unknown>[]);
    expect(vintageIndex(pts, '2021-07-20')).toBe(5); // 2021 vintage known 2021-06-11
    expect(vintageIndex(pts, '2019-01-01')).toBe(2); // only through the 2018 vintage
  });

  it('flags |z| over threshold', () => {
    expect(isAnomaly('-1.4')).toBe(false);
    expect(isAnomaly('-2.1')).toBe(true);
    expect(isAnomaly(null)).toBe(false);
  });
});

describe('D-AM-21 the knowledge_date x fallback', () => {
  it('gives a futures row an x instead of collapsing every point onto one', () => {
    // THE DEFECT: `period ?? date` was undefined on every futures row, so all six points shared x=''.
    const pts = parsePoints([
      futuresRow('2026-12', '446.0', '2026-06-03'),
      futuresRow('2026-12', '447.5', '2026-06-04'),
      futuresRow('2026-12', '449.0', '2026-06-05'),
    ]);
    expect(pts.map((p) => p.period)).toEqual(['2026-06-03', '2026-06-04', '2026-06-05']);
    expect(new Set(pts.map((p) => p.period)).size).toBe(3);
  });

  it('is LAST in the chain, so a card that has a period keeps the axis it drew before', () => {
    const pts = parsePoints(MOCK_SERIES.points as Record<string, unknown>[]);
    expect(pts.map((p) => p.period)).toEqual(['2016', '2017', '2018', '2019', '2020', '2021']);
    // and an explicit period wins over a knowledge_date that disagrees with it
    expect(parsePoints([{ period: '2019', value: '1', knowledge_date: '2020-01-01' }])[0]!.period).toBe('2019');
  });

  it('carries the delivery month onto the point, empty on a card that has none', () => {
    expect(parsePoints([futuresRow('2026-12', '446.0')])[0]!.contract_month).toBe('2026-12');
    expect(parsePoints(MOCK_SERIES.points as Record<string, unknown>[])[0]!.contract_month).toBe('');
  });

  it('still drops non-numeric rows', () => {
    expect(parsePoints([futuresRow('2026-12', 'n/a'), futuresRow('2027-03', '446.0')])).toHaveLength(1);
  });
});

describe('D-AM-21 the curve axis', () => {
  const CURVE = parsePoints([
    futuresRow('2027-03', '461.5'),
    futuresRow('2026-07', '417.5'),
    futuresRow('2026-12', '446.0'),
  ]);

  it('orders nearest -> deferred and drops rows with no delivery month', () => {
    const pts = curvePoints([...CURVE, ...parsePoints([{ period: '2021', value: '9' }])]);
    expect(pts.map((p) => p.contract_month)).toEqual(['2026-07', '2026-12', '2027-03']);
  });

  it('does not mutate the array it was handed', () => {
    const before = CURVE.map((p) => p.contract_month);
    curvePoints(CURVE);
    expect(CURVE.map((p) => p.contract_month)).toEqual(before);
  });

  it('axisKey picks the delivery month on the curve and the period on time', () => {
    const p = parsePoints([futuresRow('2026-12', '446.0', '2026-06-05')])[0]!;
    expect(axisKey(p, 'curve')).toBe('2026-12');
    expect(axisKey(p, 'time')).toBe('2026-06-05');
  });

  it('names the ONE session a curve was struck at', () => {
    expect(curveSession(CURVE)).toBe('2026-06-05');
  });

  it("returns '' when the rows do not agree on one session -- that is not a curve", () => {
    // The header must say so rather than label the picture with a date true of only some of it.
    const mixed = parsePoints([futuresRow('2026-07', '417.5', '2026-06-04'), futuresRow('2026-12', '446.0')]);
    expect(curveSession(mixed)).toBe('');
  });
});

describe('D-AM-21 trackedMonths (the futures-card test, and the scope of the curve fetch)', () => {
  const rows = [
    { value: '417.5', contract_month: '2026-07' },
    { value: '446.0', contract_month: '2026-12' },
    { value: '461.5', contract_month: '2026-12' },
  ];

  it("prefers the call's OWN contract_month scope over whatever came back", () => {
    expect(trackedMonths({ contract_month: '2026-12,2027-03' }, rows)).toEqual(['2026-12', '2027-03']);
  });

  it('falls back to the distinct expiries on the rows, ascending', () => {
    expect(trackedMonths({}, rows)).toEqual(['2026-07', '2026-12']);
    expect(trackedMonths(undefined, rows)).toEqual(['2026-07', '2026-12']);
  });

  it('tolerates spacing and empty entries in the query list', () => {
    expect(trackedMonths({ contract_month: ' 2027-03 , ,2026-07' }, [])).toEqual(['2026-07', '2027-03']);
  });

  it('a call with no delivery-month axis anywhere tracks NOTHING -- the curve is futures-only', () => {
    // Only a card declaring contract_month_col can put a month on a row or in a query, so this is the
    // whole gate: no table-name list to go stale when the next per-expiry card is registered.
    expect(trackedMonths({}, [{ value: '10.0' }, { value: '12.0' }])).toEqual([]);
    expect(trackedMonths(undefined, undefined)).toEqual([]);
  });
});
