import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { getSeries } from '@/api/client';
import { useSession } from '@/store/session';
import { SeriesChart } from './SeriesChart';
import { isAnomaly, parsePoints, sparkPath, vintageIndex, xOf } from './scale';

interface NumCall {
  ref?: string;
  query?: { table?: string; metric?: string; commodity?: string };
  rows?: { value?: unknown; z?: unknown }[];
  status?: string;
}

function NumberRow({ call, asof }: { call: NumCall; asof: string }) {
  const [open, setOpen] = useState(false);
  const table = call.query?.table;
  const metric = call.query?.metric;
  const notYet = call.status === 'not_yet_pub';
  // P7-P0.3: /v1/series is auth-gated — gate on session readiness alongside the click-to-expand.
  const ready = useSession((s) => s.ready);
  const q = useQuery({
    queryKey: ['series', table, metric, call.query?.commodity, asof],
    queryFn: () => getSeries(table!, metric!, { commodity: call.query?.commodity, asof }),
    enabled: ready && !!table && !!metric && !notYet && open,
    staleTime: 60_000,
  });

  if (notYet) {
    return (
      <div className="flex items-center gap-2 py-0.5 font-mono text-12">
        <span className="text-cyan">[{call.ref}]</span>
        <span className="w-24 text-text-dim">{metric}</span>
        <span className="text-text-faint">not known at {asof}</span>
      </div>
    );
  }

  const row0 = call.rows?.[0];
  const val = row0?.value != null ? String(row0.value) : '—';
  const z = row0?.z;
  const anom = isAnomaly(z);
  const pts = q.data ? parsePoints(q.data.points as Record<string, unknown>[]) : [];
  const vidx = pts.length ? vintageIndex(pts, asof) : -1;

  return (
    <div>
      <button
        className="flex w-full items-center gap-3 py-0.5 text-left font-mono text-12 hover:bg-bg-2"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-cyan">[{call.ref}]</span>
        <span className="w-24 shrink-0 text-text-dim">{metric}</span>
        <span className={`w-14 shrink-0 tabular-nums ${anom ? 'text-amber' : 'text-text'}`}>{val}</span>
        {pts.length >= 2 && (
          <svg width={90} height={18} className="shrink-0" aria-hidden>
            <path d={sparkPath(pts.map((p) => p.value), 90, 18)} fill="none" className="stroke-text-dim" strokeWidth={1} />
            {vidx >= 0 && (
              <line x1={xOf(vidx, pts.length, 90)} y1={0} x2={xOf(vidx, pts.length, 90)} y2={18} className="stroke-cyan" strokeWidth={0.8} />
            )}
          </svg>
        )}
        {z != null && String(z) !== '' && (
          <span className={`text-11 ${anom ? 'text-amber' : 'text-text-dim'}`}>
            z={String(z)}
            {anom ? ' ⚠' : ''}
          </span>
        )}
      </button>
      {open && q.data && <SeriesChart series={q.data} asof={asof} />}
    </div>
  );
}

/** The NUMBERS panel (design §4.5): every metric with its vintage-marked sparkline + `[N#]`, never a bare
 *  value; click a row to expand the full series. */
export function Numbers({ calls, asof }: { calls: unknown[]; asof: string }) {
  const cs = (calls ?? []) as NumCall[];
  if (!cs.length) return null;
  return (
    <div className="rounded-panel border border-line bg-bg-1 p-2" data-testid="numbers">
      <div className="mb-1 font-mono text-11 uppercase tracking-wider text-text-dim">Numbers</div>
      {cs.map((c, i) => (
        <NumberRow key={i} call={c} asof={asof} />
      ))}
    </div>
  );
}
