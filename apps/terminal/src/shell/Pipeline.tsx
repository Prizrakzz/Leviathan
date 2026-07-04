import type { StageEvent } from '@/api/schema';

const ROWS: { key: StageEvent['stage']; label: string }[] = [
  { key: 'planning', label: 'planning' },
  { key: 'walking', label: 'walking graph' },
  { key: 'retrieving', label: 'retrieving' },
  { key: 'numbers', label: 'numbers' },
  { key: 'verifying', label: 'verifying' },
];

function detail(s?: StageEvent): string {
  if (!s) return '—';
  switch (s.stage) {
    case 'planning':
      return `intent=${s.intent ?? '?'}${s.contracts?.length ? ` · ${s.contracts.join(', ')}` : ''}`;
    case 'walking':
      return `${s.nodes ?? 0} nodes · ${s.regimes ?? 0} regimes fired`;
    case 'retrieving':
      return `${s.props ?? 0} props @ ≤ as-of`;
    case 'numbers':
      return s.calls ? `${s.calls} looked up` : '—';
    case 'verifying':
      return `${s.checked ?? 0} cited · ${s.stripped ?? 0} stripped`;
    default:
      return '—';
  }
}

/** The staged-pipeline progress (design §4.9): turns the 30–90s wait into visible proof of grounded
 *  reasoning. Reads the granular SSE `stage` ticks; collapses into the finished note. */
export function Pipeline({ stages, done }: { stages: StageEvent[]; done: boolean }) {
  const seen = new Map(stages.map((s) => [s.stage, s]));
  return (
    <div className="font-mono text-12 text-text-dim" data-testid="pipeline">
      {ROWS.map((r) => {
        const s = seen.get(r.key);
        const active = seen.has(r.key);
        return (
          <div key={r.key} className="flex items-baseline gap-2 py-0.5">
            <span className={active ? 'text-cyan' : 'text-text-faint'}>
              {active ? (done ? '✓' : '▸') : '·'}
            </span>
            <span className={`inline-block w-28 ${active ? 'text-text' : 'text-text-faint'}`}>{r.label}</span>
            <span>{detail(s)}</span>
          </div>
        );
      })}
    </div>
  );
}
