import { useQuery } from '@tanstack/react-query';
import { suggest } from '@/api/client';
import { Composer } from '@/shell/Composer';
import { useSession } from '@/store/session';

/** Fallback starters — shown while the suggester loads, errors, or returns empty (6.2: the live set
 *  comes from /v1/suggest with an empty packet, so starters are news-aware, not frozen strings). */
const FALLBACK = [
  'KC arabica frost in Brazil — walk me through the convexity setup',
  'Which contracts have convergence regimes closest to firing right now?',
  'US corn ending stocks vs the 5-year average — what does it imply?',
  'How does a weak BRL interact with the sugar su-ratio regime?',
];

/** The new-thread landing (5.6 W4): a centered hero composer + starter prompts, ChatGPT-style,
 *  so the first thing a user sees is WHERE TO TYPE — not an empty panel. */
export function EmptyState({ onAsk }: { onAsk: (q: string) => void }) {
  const ready = useSession((s) => s.ready);
  const startersQ = useQuery({
    queryKey: ['suggest', 'empty'],
    queryFn: () => suggest({ contracts: [] }),
    enabled: ready,
    staleTime: 600_000, // starters refresh at most every 10 min per session
  });
  const starters = startersQ.data?.suggestions?.length ? startersQ.data.suggestions : FALLBACK;
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 p-8" data-testid="empty-state">
      <div className="text-center">
        <div className="font-mono text-11 uppercase tracking-wider text-text-dim">leviathan terminal</div>
        <div className="mt-1 font-sans text-18 font-semibold text-text">
          ask a fundamental-convexity question
        </div>
      </div>
      <Composer onSubmit={onAsk} streaming={false} hero />
      <div className="flex max-w-2xl flex-wrap justify-center gap-2">
        {starters.map((q) => (
          <button
            key={q}
            onClick={() => onAsk(q)}
            className="rounded-chip border border-line px-2.5 py-1 text-left font-sans text-12 text-text-dim hover:border-cyan hover:text-text"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
