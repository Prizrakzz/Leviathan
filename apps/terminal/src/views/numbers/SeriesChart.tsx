import { AxisBottom } from '@visx/axis';
import { Group } from '@visx/group';
import { scaleLinear, scalePoint } from '@visx/scale';
import { LinePath } from '@visx/shape';
import type { components } from '@/api/types.gen';
import { parsePoints, vintageIndex } from './scale';

type Series = components['schemas']['Series'];

/** The expanded vintage-aware series (design §4.5): the line, the as-of vintage line, and a marker on the
 *  point that was known then. Bespoke visx — themed from tokens, no default chart styling. */
export function SeriesChart({ series, asof }: { series: Series; asof: string }) {
  const pts = parsePoints(series.points as Record<string, unknown>[]);
  const w = 360;
  const h = 140;
  const m = { t: 8, r: 10, b: 22, l: 34 };
  const iw = w - m.l - m.r;
  const ih = h - m.t - m.b;
  if (pts.length < 2) return null;
  const x = scalePoint<string>({ domain: pts.map((p) => p.period), range: [0, iw], padding: 0.5 });
  const vals = pts.map((p) => p.value);
  const y = scaleLinear<number>({ domain: [Math.min(...vals), Math.max(...vals)], range: [ih, 0], nice: true });
  const vidx = vintageIndex(pts, asof);
  const vintageX = vidx >= 0 ? (x(pts[vidx]!.period) ?? 0) : 0;

  return (
    <svg width={w} height={h} className="mt-1" role="img" aria-label={`${series.metric} series`}>
      <Group left={m.l} top={m.t}>
        <line x1={vintageX} y1={0} x2={vintageX} y2={ih} className="stroke-cyan" strokeDasharray="2 2" />
        <LinePath data={pts} x={(p) => x(p.period) ?? 0} y={(p) => y(p.value)} className="stroke-amber" strokeWidth={1.5} />
        {pts.map((p, i) => (
          <circle key={i} cx={x(p.period) ?? 0} cy={y(p.value)} r={2.2} className={i === vidx ? 'fill-cyan' : 'fill-text-dim'} />
        ))}
        <AxisBottom
          top={ih}
          scale={x}
          stroke="var(--line)"
          tickStroke="var(--line)"
          tickLabelProps={() => ({ fill: 'var(--text-faint)', fontSize: 9, fontFamily: 'monospace', textAnchor: 'middle' })}
        />
      </Group>
    </svg>
  );
}
