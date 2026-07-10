/** Phase 6.2 — follow-up question chips (the depth path that makes concise answers safe). Purely
 *  presentational: the suggester query lives in AnswerView (fired ONCE per completed turn, never per
 *  input). Renders nothing for an empty list — chips are a nicety, never an error state.
 *  P9-E1a: `watchItems` (FE-derived from the answer's watch section) render PREPENDED and PREFILL the
 *  composer via `onPrefill` -- a watch item is a mentor sentence, not a query; auto-submitting it through
 *  `onAsk` degrades retrieval (the NotificationBell prefill contract). Callers dedupe watch items against
 *  `items` before passing: chips key by text. */
export function SuggestionChips({
  items,
  onAsk,
  watchItems = [],
  onPrefill,
}: {
  items: string[];
  onAsk: (q: string) => void;
  watchItems?: string[];
  onPrefill?: (q: string) => void;
}) {
  if (!items.length && !watchItems.length) return null;
  return (
    <div data-testid="suggestion-chips">
      <div className="font-mono text-11 uppercase tracking-wider text-text-faint">follow up</div>
      <div className="mt-1.5 flex flex-wrap gap-2">
        {watchItems.map((q) => (
          <button
            key={q}
            data-testid="watch-chip"
            onClick={() => onPrefill?.(q)}
            className="rounded-chip border border-line px-2.5 py-1 text-left font-sans text-12 text-text-dim hover:border-amber hover:text-text"
          >
            {q}
          </button>
        ))}
        {items.map((q) => (
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
