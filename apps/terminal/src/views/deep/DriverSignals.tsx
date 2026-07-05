import type { components } from '@/api/types.gen';
import { orderDrivers } from './order';

type DriverSignal = components['schemas']['DriverSignal'];

/** Driver coverage (design §3.2) — every driver the contract's regimes depend on, with its point-in-time
 *  verdict + value + z at the as-of. Live/observed drivers float to the top; dormant drivers dim. */
export function DriverSignals({ drivers }: { drivers: DriverSignal[] }) {
  const ds = orderDrivers(drivers);
  if (!ds.length) return null;
  return (
    <div className="rounded-panel border border-line bg-bg-1 p-2" data-testid="drivers">
      <div className="mb-1 font-mono text-11 uppercase tracking-wider text-text-dim">Driver coverage</div>
      {ds.map((d) => {
        const z = Number(d.z);
        const hasZ = d.z != null && String(d.z) !== '' && Number.isFinite(z);
        const anom = hasZ && Math.abs(z) >= 1.5;
        return (
          <div key={d.id} className="flex items-center gap-3 py-0.5 font-mono text-12">
            <span
              className={`h-1.5 w-1.5 shrink-0 rounded-full ${d.live ? 'bg-live' : 'bg-text-faint'}`}
              aria-hidden
            />
            <span className={`w-40 shrink-0 truncate ${d.live ? 'text-text' : 'text-text-faint'}`}>
              {d.id}
            </span>
            <span className="w-24 shrink-0 text-text-dim">{d.verdict ?? '—'}</span>
            <span className={`w-16 shrink-0 tabular-nums ${anom ? 'text-amber' : 'text-text-dim'}`}>
              {d.value != null ? String(d.value) : '—'}
            </span>
            {hasZ && (
              <span className={`text-11 ${anom ? 'text-amber' : 'text-text-dim'}`}>
                z={String(d.z)}
                {anom ? ' ⚠' : ''}
              </span>
            )}
            {d.knowledge_date ? (
              <span className="ml-auto text-11 text-text-faint">{d.knowledge_date}</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
