import { useEffect, useReducer } from 'react';
import type { StampedStage } from '@/api/useTurn';

const ROWS: { key: string; label: string }[] = [
  { key: 'planning', label: 'planning' },
  { key: 'walking', label: 'walking graph' },
  { key: 'retrieving', label: 'retrieving' },
  { key: 'numbers', label: 'numbers' },
  { key: 'synthesizing', label: 'synthesizing' },
  { key: 'verifying', label: 'verifying' },
];

function detail(s?: StampedStage): string {
  if (!s) return '—';
  switch (s.stage) {
    case 'planning':
      return `intent=${s.intent ?? '?'}${s.contracts?.length ? ` · ${s.contracts.join(', ')}` : ''}`;
    case 'walking':
      return s.nodes != null ? `${s.nodes} nodes · ${s.regimes ?? 0} regimes fired` : 'walking the cascade DAG…';
    case 'retrieving':
      if (s.props != null) return `${s.props} props @ ≤ as-of`;
      if (s.done != null) return `${s.done}/${s.total ?? '?'} nodes filled`;
      return '—';
    case 'numbers':
      if (s.running) return `${s.calls ?? 0} looked up · ${s.table ?? '…'}`;
      return s.calls ? `${s.calls} looked up` : '—';
    case 'synthesizing':
      return 'drafting the note…';
    case 'verifying':
      return `${s.checked ?? 0} cited · ${s.stripped ?? 0} stripped`;
    default:
      return '—';
  }
}

function fmtSecs(ms: number): string {
  return `${(Math.max(0, ms) / 1000).toFixed(1)}s`;
}

/** The staged-pipeline progress (design §4.9): turns the 30–90s wait into visible proof of grounded
 *  reasoning. 5.6: rows now update LIVE during the long phases (retrieval node counts, per-lookup numbers
 *  ticks, a synthesizing row) and each row shows elapsed seconds — no more dark phases. Unknown stage
 *  names from a newer backend are simply ignored. */
export function Pipeline({ stages, done }: { stages: StampedStage[]; done: boolean }) {
  // 1s ticker so the active row's elapsed time visibly counts while streaming.
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    if (done) return;
    const id = setInterval(force, 1000);
    return () => clearInterval(id);
  }, [done]);

  const latest = new Map<string, StampedStage>();
  const firstTs = new Map<string, number>();
  for (const s of stages) {
    latest.set(s.stage, s);
    if (!firstTs.has(s.stage)) firstTs.set(s.stage, s.ts);
  }
  const lastTsOverall = stages.length ? stages[stages.length - 1]!.ts : 0;

  // Elapsed per row ≈ from its first event to the NEXT seen row's first event (or now / stream end).
  // Numbers runs in parallel with the walk, so its span can overlap others — cosmetic, and honest.
  const elapsed = (idx: number): string => {
    const key = ROWS[idx]!.key;
    const start = firstTs.get(key);
    if (start == null) return '';
    let end: number | undefined;
    for (let j = idx + 1; j < ROWS.length; j++) {
      const t = firstTs.get(ROWS[j]!.key);
      if (t != null && t > start) {
        end = t;
        break;
      }
    }
    if (end == null) end = done ? lastTsOverall : performance.now();
    return fmtSecs(end - start);
  };

  return (
    <div className="font-mono text-12 text-text-dim" data-testid="pipeline">
      {ROWS.map((r, i) => {
        const s = latest.get(r.key);
        const active = latest.has(r.key);
        return (
          <div key={r.key} className="flex items-baseline gap-2 py-0.5">
            <span className={active ? 'text-cyan' : 'text-text-faint'}>
              {active ? (done ? '✓' : '▸') : '·'}
            </span>
            <span className={`inline-block w-28 ${active ? 'text-text' : 'text-text-faint'}`}>{r.label}</span>
            <span className="flex-1">{detail(s)}</span>
            <span className="text-text-faint">{elapsed(i)}</span>
          </div>
        );
      })}
    </div>
  );
}
