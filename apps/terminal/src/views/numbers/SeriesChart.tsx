import { AxisBottom, AxisLeft } from '@visx/axis';
import { Group } from '@visx/group';
import { scaleLinear, scalePoint } from '@visx/scale';
import { LinePath } from '@visx/shape';
import type { components } from '@/api/types.gen';
import {
  type SeriesAxis,
  TICK_X,
  TICK_Y,
  axisTick,
  curvePoints,
  curveSession,
  parsePoints,
  vintageIndex,
} from './scale';

type Series = components['schemas']['Series'];

const W = 360;
const H = 140;
const M = { t: 8, r: 10, b: 22, l: 34 };
const IW = W - M.l - M.r;
const IH = H - M.t - M.b;

/** The expanded vintage-aware series (design §4.5): the line, the as-of vintage line, and a marker on the
 *  point that was known then. Bespoke visx — themed from tokens, no default chart styling.
 *
 *  D-AM-21 adds a SECOND axis mode rather than a second component. `axis='curve'` draws the TERM STRUCTURE:
 *  x is the delivery month (nearest → deferred), the line is carry when it rises and backwardation when it
 *  falls, and there is no vintage marker because every point is the SAME session — which is why that session
 *  is named in the header instead. `axis='time'` is the default and the pre-wave path.
 *
 *  D-UX-5 adds two things the picture was missing and one it was misstating:
 *   - AxisLeft. `M.l = 34` had reserved a left gutter since the first commit and nothing was ever drawn in
 *     it, so a reader saw a SHAPE WITH NO MAGNITUDES and had to recover the scale from the `[N#]` row.
 *   - the mono token on tick labels (see TICK_LABEL).
 *   - the as-of line is NAMED. Because /v1/series has already filtered to `knowledge_date <= asof` and
 *     collapsed to one row per identity (query.py `ROW_NUMBER … WHERE _rn = 1`), the marker lands on the
 *     last point of essentially every time chart — so drawn bare it reads as "this point was revised",
 *     which is the one thing it does not mean. The legend says what it is: the READ's cutoff. A real
 *     vintage overlay needs an un-collapsed vintage window out of /v1/series and is not this change. */
export function SeriesChart({
  series,
  asof,
  axis = 'time',
}: {
  series: Series;
  asof: string;
  axis?: SeriesAxis;
}) {
  const pts = parsePoints(series.points as Record<string, unknown>[]);
  if (axis === 'curve') return <CurveChart series={series} points={curvePoints(pts)} />;
  if (pts.length < 2) return null;
  const x = scalePoint<string>({ domain: pts.map((p) => p.period), range: [0, IW], padding: 0.5 });
  const vals = pts.map((p) => p.value);
  const y = scaleLinear<number>({ domain: [Math.min(...vals), Math.max(...vals)], range: [IH, 0], nice: true });
  const vidx = vintageIndex(pts, asof);
  const vintageX = vidx >= 0 ? (x(pts[vidx]!.period) ?? 0) : 0;
  const unit = series.unit ?? '';

  return (
    <div data-testid="series-chart">
      <svg width={W} height={H} className="mt-1" role="img" aria-label={`${series.metric} series`}>
        <Group left={M.l} top={M.t}>
          <line x1={vintageX} y1={0} x2={vintageX} y2={IH} className="stroke-asof" strokeDasharray="2 2">
            {/* The native tooltip carries the same sentence as the legend, for a reader who hovers the
                line itself rather than reading the row under the chart. */}
            <title>as-of {asof} — the cutoff this series was read at, not a revision marker</title>
          </line>
          <LinePath data={pts} x={(p) => x(p.period) ?? 0} y={(p) => y(p.value)} className="stroke-amber" strokeWidth={1.5} />
          {pts.map((p, i) => (
            <circle key={i} cx={x(p.period) ?? 0} cy={y(p.value)} r={2.2} className={i === vidx ? 'fill-asof' : 'fill-text-dim'} />
          ))}
          <AxisLeft scale={y} numTicks={4} tickFormat={(v) => axisTick(Number(v))}
            stroke="var(--line)" tickStroke="var(--line)" tickLabelProps={() => TICK_Y} />
          <AxisBottom
            top={IH}
            scale={x}
            stroke="var(--line)"
            tickStroke="var(--line)"
            tickLabelProps={() => TICK_X}
          />
        </Group>
      </svg>
      {/* NAMED, not decorative: see the D-UX-5 note above. The dash is drawn in the same ink as the line
          it explains, so the legend and the mark cannot drift apart under an accent swap. */}
      <div className="font-mono text-11 text-text-faint" data-testid="series-asof-legend">
        <span className="text-asof">--</span> as-of line · {asof || 'this read'} cutoff (not a vintage marker)
        {unit ? ` · ${unit}` : ''}
      </div>
    </div>
  );
}

/** The curve (carry / backwardation) picture: one settle per delivery month at ONE as-of.
 *
 *  The header is not decoration. A curve has no time axis, so the session it was struck at is not
 *  recoverable from the picture — and a term structure read at yesterday's close means something different
 *  from one read at today's. It comes off the ROWS (`curveSession`), never off the caller's as-of: the
 *  as-of is a PIT cutoff, the session is what the exchange actually printed on/before it, and on any card
 *  with a publication lag those are different dates. Rows that disagree on the session are not a
 *  single-as-of curve at all, and the header says so rather than picking one. */
function CurveChart({ series, points }: { series: Series; points: ReturnType<typeof curvePoints> }) {
  if (points.length < 2) return null;
  const x = scalePoint<string>({ domain: points.map((p) => p.contract_month), range: [0, IW], padding: 0.5 });
  const vals = points.map((p) => p.value);
  const y = scaleLinear<number>({ domain: [Math.min(...vals), Math.max(...vals)], range: [IH, 0], nice: true });
  const session = curveSession(points);
  // The unit comes off the ROWS when the envelope has none, which on the per-expiry card is always: `settle`
  // declares no registry `unit` at all, its serving unit is the per-contract override the server stamps onto
  // each row, and this table converts no currency anywhere. Only when the rows AGREE — ten currencies share
  // this card, and an unlabelled 446.0 is the exact figure the card's own notes forbid quoting.
  const rowUnits = new Set(
    (series.points as Record<string, unknown>[])
      .map((p) => String(p.unit ?? ''))
      .filter((u) => u !== ''),
  );
  const unit = series.unit || (rowUnits.size === 1 ? [...rowUnits][0]! : '');

  return (
    <div data-testid="curve-chart">
      <div className="mt-1 font-mono text-11 text-text-faint">
        curve — {points.length} expiries {session ? `at ${session}` : 'across MIXED sessions'}
        {unit ? ` (${unit})` : ''}
      </div>
      <svg width={W} height={H} role="img" aria-label={`${series.metric} curve`}>
        <Group left={M.l} top={M.t}>
          <LinePath
            data={points}
            x={(p) => x(p.contract_month) ?? 0}
            y={(p) => y(p.value)}
            className="stroke-amber"
            strokeWidth={1.5}
          />
          {points.map((p, i) => (
            <circle key={i} cx={x(p.contract_month) ?? 0} cy={y(p.value)} r={2.2} className="fill-text-dim" />
          ))}
          <AxisLeft scale={y} numTicks={4} tickFormat={(v) => axisTick(Number(v))}
            stroke="var(--line)" tickStroke="var(--line)" tickLabelProps={() => TICK_Y} />
          <AxisBottom
            top={IH}
            scale={x}
            stroke="var(--line)"
            tickStroke="var(--line)"
            tickLabelProps={() => TICK_X}
          />
        </Group>
      </svg>
    </div>
  );
}
