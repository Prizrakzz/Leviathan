import type { components } from '@/api/types.gen';
import { cellLabel, firedCount, HEAT_CLASS, heatBucket, rankRows } from './heat';

type ConvergenceRow = components['schemas']['ConvergenceRow'];

/** The convergence heatmap (design §4.8) — one row per contract, one cell per regime colored by
 *  proximity-to-firing; contracts float hottest-first so "where convexity is building" reads top-down.
 *  Presentational: the container feeds `rows` from GET /v1/convergence. Click a contract or cell to
 *  deep-dive. */
export function ConvergenceGrid({
  rows,
  asof,
  onPick,
}: {
  rows: ConvergenceRow[];
  asof: string;
  onPick: (contract: string) => void;
}) {
  const ranked = rankRows(rows);
  if (!ranked.length)
    return (
      <div className="font-mono text-12 text-text-faint" data-testid="convergence-empty">
        no contracts in the graph at {asof}.
      </div>
    );

  return (
    <div className="space-y-2" data-testid="convergence-grid">
      <div className="flex items-baseline justify-between">
        <div className="font-mono text-11 uppercase tracking-wider text-text-dim">
          where convexity is building
        </div>
        <div className="font-mono text-11 text-text-faint">as of {asof}</div>
      </div>

      <div className="space-y-1">
        {ranked.map((row) => {
          const fired = firedCount(row);
          return (
            <div key={row.contract} className="flex items-center gap-2" data-testid="conv-row">
              <button
                className={`w-40 shrink-0 truncate text-left font-mono text-12 hover:text-cyan ${
                  fired > 0 ? 'text-amber' : 'text-text'
                }`}
                onClick={() => onPick(row.contract)}
                title={`${row.contract} — ${fired} firing / ${row.regimes.length} regimes`}
              >
                {fired > 0 ? '● ' : ''}
                {row.contract}
              </button>
              <div className="flex flex-wrap gap-0.5">
                {row.regimes.map((r) => (
                  <button
                    key={r.name}
                    className={`rounded-chip px-1.5 py-0.5 font-mono text-11 tabular-nums ${
                      HEAT_CLASS[heatBucket(r.proximity, r.fired)]
                    }`}
                    onClick={() => onPick(row.contract)}
                    title={`${r.name} ${r.direction} — ${
                      r.fired ? 'FIRING' : `proximity ${Math.round((r.proximity ?? 0) * 100)}%`
                    } (${r.n_active}/${r.threshold})`}
                  >
                    {cellLabel(r)}
                  </button>
                ))}
                {row.regimes.length === 0 && (
                  <span className="font-mono text-11 text-text-faint">no regimes</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
