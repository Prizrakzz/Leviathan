import { Composer } from '@/shell/Composer';

const SUGGESTED = [
  'KC arabica frost in Brazil — walk me through the convexity setup',
  'Which contracts have convergence regimes closest to firing right now?',
  'US corn ending stocks vs the 5-year average — what does it imply?',
  'How does a weak BRL interact with the sugar su-ratio regime?',
];

/** The new-thread landing (5.6 W4): a centered hero composer + curated starter prompts, ChatGPT-style,
 *  so the first thing a user sees is WHERE TO TYPE — not an empty panel. */
export function EmptyState({ onAsk }: { onAsk: (q: string) => void }) {
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
        {SUGGESTED.map((q) => (
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
