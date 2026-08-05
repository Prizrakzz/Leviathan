/** Phase 6.2 — follow-up question chips (the depth path that makes concise answers safe). Purely
 *  presentational: the suggester query lives in AnswerView (fired ONCE per completed turn, never per
 *  input). Renders nothing for an empty list — chips are a nicety, never an error state.
 *  P9-E1a: `watchItems` (FE-derived from the answer's watch section) render PREPENDED and PREFILL the
 *  composer via `onPrefill` -- a watch item is a mentor sentence, not a query; auto-submitting it through
 *  `onAsk` degrades retrieval (the NotificationBell prefill contract). Callers dedupe watch items against
 *  `items` before passing: chips key by text. */

/** `**`/`*` emphasis runs and code backticks. Deliberately NOT `_`: a watch sentence can carry a snake_case
 *  table/driver id (`silver_psd`, `sugar_ethanol_parity`) and underscore-stripping would corrupt it. */
const EMPHASIS = /[*`]+/g;
/** The measured D-TW-24 shape: a bolded item NAME, then `:`, then the mentor sentence --
 *  `**BRL/USD trajectory**: a further weakening real strengthens ...`. Anchored at the start and requiring
 *  the closing marker immediately before the colon, so a mid-sentence colon can never truncate a chip. */
const TITLED = /^\s*\*\*(.+?)\*\*\s*:\s*\S/;

/** D-TW-24 -- the chip LABEL boundary. Watch items are raw mentor-bullet text: markdown emphasis markers
 *  reach the DOM literally here (SuggestionChips renders `{q}` as a text child, so nothing strips them the
 *  way inlineFormat does for note prose), and the whole sentence is dumped into a chip. So at the boundary:
 *  strip emphasis, and when the item is the `**name**: sentence` shape, show just the NAME. The full text
 *  is preserved for the tooltip and for the prefill. Server data is untouched -- this is render-side only. */
export function watchChipLabel(raw: string): string {
  const titled = raw.match(TITLED);
  return watchChipText(titled?.[1] ?? raw);
}

/** The same item with emphasis markers stripped -- what the tooltip shows and what the composer prefills.
 *  Prefilling the raw string would put literal `**` into the query box: the identical defect, one step on. */
export function watchChipText(raw: string): string {
  return raw.replace(EMPHASIS, '').replace(/\s+/g, ' ').trim();
}

/** The "follow up" row itself (see the module note above). */
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
  // S3: the suggester row is where the server suggestions and FE watch chips MERGE into one "follow up"
  // row. The server clamps to <=4 (and a stale bundle can over-produce); clamp the suggester follow-ups
  // to EXACTLY 3 here so the user never sees a 4th cyan chip. Watch chips are a SEPARATE class (amber
  // hover, prefill) and keep their own count — they are not suggester follow-ups.
  const suggesters = items.slice(0, 3);
  if (!suggesters.length && !watchItems.length) return null;
  return (
    <div data-testid="suggestion-chips">
      <div className="font-mono text-11 uppercase tracking-wider text-text-faint">follow up</div>
      <div className="mt-1.5 flex flex-wrap gap-2">
        {/* D-TW-24: `key` stays the RAW item (two watch bullets can share a title; the raw text is what the
            caller already deduped on), while the visible label is the cleaned title and the full cleaned
            sentence rides the tooltip. */}
        {watchItems.map((q) => (
          <button
            key={q}
            data-testid="watch-chip"
            title={watchChipText(q)}
            onClick={() => onPrefill?.(watchChipText(q))}
            className="rounded-chip border border-line px-2.5 py-1 text-left font-sans text-12 text-text-dim hover:border-amber hover:text-text"
          >
            {watchChipLabel(q)}
          </button>
        ))}
        {suggesters.map((q) => (
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
