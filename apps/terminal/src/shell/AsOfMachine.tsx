import { useAsOf } from '@/store/asof';

/** The as-of time machine (design §3.4) — the signature control. `◂ ▸` step the global horizon; `[live]`
 *  glows cyan at today; any past date shows an amber BACKTEST pill (kill-switch greys the events rail). The
 *  expanding scrubber across 1973→today is Phase 3. */
export function AsOfMachine() {
  const { asof, live, step, goLive } = useAsOf();
  return (
    <div className="flex items-center gap-2 font-mono text-12" data-testid="asof">
      <span className="text-text-dim">as-of</span>
      <button aria-label="as-of step back" className="text-text-dim hover:text-cyan" onClick={() => step(-1)}>
        ◂
      </button>
      <span className="tabular-nums text-text" data-testid="asof-date">
        {asof}
      </span>
      <button aria-label="as-of step forward" className="text-text-dim hover:text-cyan" onClick={() => step(1)}>
        ▸
      </button>
      {live ? (
        <span className="text-live">[live]</span>
      ) : (
        <button
          aria-label="return to live"
          className="rounded-chip border border-warn px-1 text-11 text-warn hover:bg-bg-1"
          onClick={goLive}
        >
          BACKTEST
        </button>
      )}
    </div>
  );
}
