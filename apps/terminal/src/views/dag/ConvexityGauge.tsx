import type { components } from '@/api/types.gen';

type RegimeCard = components['schemas']['RegimeCard'];

/** The convexity gauge (design §4.4) — the brand mark made functional: a small option-payoff curve, flat
 *  until the threshold kink then convex past it, with the current proximity marked (cyan) relative to the
 *  kink (amber). The honest "how close to the kink" glyph — the product's thesis in one shape. */
export function ConvexityGauge({ regime }: { regime: RegimeCard }) {
  const w = 220;
  const h = 84;
  const pad = 10;
  const x0 = pad;
  const x1 = w - pad;
  const yBase = h - pad - 16;
  const yTop = pad + 2;
  const kinkX = x0 + (x1 - x0) * 0.42;
  const payoff = `M ${x0} ${yBase} L ${kinkX} ${yBase} Q ${(kinkX + x1) / 2} ${yBase} ${x1} ${yTop}`;

  const prox = Math.max(0, Math.min(1, regime.proximity));
  const px = x0 + (x1 - x0) * prox;
  const py = px <= kinkX ? yBase : yBase - ((px - kinkX) / (x1 - kinkX)) * (yBase - yTop);
  const status = regime.fired ? 'FIRING' : prox >= 0.5 ? 'ARMED' : 'DORMANT';
  const statusColor = regime.fired ? 'text-amber' : prox >= 0.5 ? 'text-warn' : 'text-text-faint';

  return (
    <div className="rounded-panel border border-line bg-bg-1 p-2" data-testid="gauge">
      <div className="mb-1 flex items-center justify-between font-mono text-11">
        <span className="uppercase tracking-wider text-text-dim">{regime.name}</span>
        <span className={statusColor}>{status}</span>
      </div>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${regime.name} gauge`}>
        <line x1={kinkX} y1={yTop} x2={kinkX} y2={yBase} className="stroke-line" strokeDasharray="2 3" />
        <path d={payoff} fill="none" className="stroke-amber" strokeWidth={2} strokeLinecap="round" />
        <circle cx={px} cy={py} r={4} className="fill-cyan" />
        <text x={kinkX} y={yBase + 12} textAnchor="middle" className="fill-text-faint" style={{ font: '9px monospace' }}>
          kink
        </text>
      </svg>
      <div className="mt-1 font-mono text-11 text-text-dim">
        {regime.n_active} of {regime.threshold} drivers · {regime.matched.join(', ') || '—'}
      </div>
    </div>
  );
}
