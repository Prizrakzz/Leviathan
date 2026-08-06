import { AxisBottom } from '@visx/axis';
import { Group } from '@visx/group';
import { scaleLinear, scalePoint } from '@visx/scale';
import { LinePath } from '@visx/shape';
import type { OverlayLeg } from './chartTriggers';

const W = 360;
const H = 150;
const M = { t: 8, r: 10, b: 22, l: 34 };
const IW = W - M.l - M.r;
const IH = H - M.t - M.b;

/** TWO series in ONE svg -- the single new chart primitive this wave adds (D-UX-3).
 *
 *  It exists for the co-move pair: two legs whose whole point is that they moved TOGETHER, which is a claim
 *  about their shapes side by side and is unreadable as two charts stacked one above the other.
 *
 *  MIXED UNITS ARE REFUSED, not accommodated. The obvious accommodation is a second y axis, and a dual axis
 *  is the classic way to manufacture a correlation: the two scales are chosen independently, so the crossing
 *  point and the apparent co-movement are artifacts of where the axes were pinned, not of the data. In v1
 *  this says so in one plain line instead. Both legs share ONE y domain, so "these two moved together" is a
 *  statement the picture can actually support. */
export function OverlayChart({
  legs,
  window: win,
}: {
  legs: [OverlayLeg, OverlayLeg];
  /** The shared window the legs were measured over (e.g. 'MY2018-MY2020'), named in the header because a
   *  two-leg picture has no other place to say what span it covers. */
  window?: string;
}) {
  const [a, b] = legs;
  if (a.unit !== b.unit)
    return (
      <div className="py-0.5 font-mono text-11 text-text-faint" data-testid="overlay-mixed-units">
        these two legs are quoted in different units ({a.unit || 'unlabelled'} against {b.unit || 'unlabelled'})
        — plotting them on one axis would invent a comparison, so they are not overlaid here
      </div>
    );
  if (a.points.length < 2 || b.points.length < 2) return null;

  // The x domain is the UNION of both legs' labels, in label order -- the legs are index-aligned eras on
  // each commodity's OWN marketing year, so one leg can carry a label the other does not, and dropping to
  // the intersection would silently shorten a leg the answer quoted in full.
  const domain = [...new Set([...a.points, ...b.points].map((p) => p.period))].sort();
  const x = scalePoint<string>({ domain, range: [0, IW], padding: 0.5 });
  const vals = [...a.points, ...b.points].map((p) => p.value);
  const y = scaleLinear<number>({ domain: [Math.min(...vals), Math.max(...vals)], range: [IH, 0], nice: true });

  return (
    <div data-testid="overlay-chart">
      <div className="mt-1 flex flex-wrap items-center gap-x-3 font-mono text-11 text-text-faint">
        <span className="text-amber">— {a.label}</span>
        <span className="text-cyan">— {b.label}</span>
        <span>
          {a.unit}
          {win ? ` · ${win}` : ''}
        </span>
      </div>
      <svg width={W} height={H} role="img" aria-label={`${a.label} and ${b.label} overlay`}>
        <Group left={M.l} top={M.t}>
          {[
            { leg: a, cls: 'stroke-amber', dot: 'fill-amber' },
            { leg: b, cls: 'stroke-cyan', dot: 'fill-cyan' },
          ].map(({ leg, cls, dot }) => (
            <g key={leg.label}>
              <LinePath
                data={leg.points}
                x={(p) => x(p.period) ?? 0}
                y={(p) => y(p.value)}
                className={cls}
                strokeWidth={1.5}
              />
              {leg.points.map((p, i) => (
                <circle key={i} cx={x(p.period) ?? 0} cy={y(p.value)} r={2.2} className={dot} />
              ))}
            </g>
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
