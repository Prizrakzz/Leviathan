import { AxisBottom } from '@visx/axis';
import { Group } from '@visx/group';
import { scaleLinear, scalePoint } from '@visx/scale';
import { LinePath } from '@visx/shape';
import type { components } from '@/api/types.gen';
import { type SeriesAxis, curvePoints, curveSession, parsePoints, vintageIndex } from './scale';

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
 *  is named in the header instead. `axis='time'` is the default and the pre-wave path: same domain, same
 *  marks, same bare `<svg>` element, byte for byte. */
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

  return (
    <svg width={W} height={H} className="mt-1" role="img" aria-label={`${series.metric} series`}>
      <Group left={M.l} top={M.t}>
        <line x1={vintageX} y1={0} x2={vintageX} y2={IH} className="stroke-cyan" strokeDasharray="2 2" />
        <LinePath data={pts} x={(p) => x(p.period) ?? 0} y={(p) => y(p.value)} className="stroke-amber" strokeWidth={1.5} />
        {pts.map((p, i) => (
          <circle key={i} cx={x(p.period) ?? 0} cy={y(p.value)} r={2.2} className={i === vidx ? 'fill-cyan' : 'fill-text-dim'} />
        ))}
        <AxisBottom
          top={IH}
          scale={x}
          stroke="var(--line)"
          tickStroke="var(--line)"
          tickLabelProps={() => ({ fill: 'var(--text-faint)', fontSize: 9, fontFamily: 'monospace', textAnchor: 'middle' })}
        />
      </Group>
    </svg>
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
          <AxisBottom
            top={IH}
            scale={x}
            stroke="var(--line)"
            tickStroke="var(--line)"
            tickLabelProps={() => ({
              fill: 'var(--text-faint)',
              fontSize: 9,
              fontFamily: 'monospace',
              textAnchor: 'middle',
            })}
          />
        </Group>
      </svg>
    </div>
  );
}
