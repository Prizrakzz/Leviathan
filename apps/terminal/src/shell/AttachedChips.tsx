import { useUI } from '@/store/ui';

const KIND_GLYPH: Record<string, string> = { node: '◈', edge: '⇢', event: '⚡' };

/** P2: the removable context-chip row above the composer — the user's attached graph gestures riding the
 *  next turn. Reads the store directly (SuggestionChips pattern: no new Composer props, both mount sites
 *  untouched); renders nothing when empty. Chips are per-thread + cleared after send. */
export function AttachedChips() {
  const chips = useUI((s) => s.attachedChips);
  if (chips.length === 0) return null;
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2" data-testid="attached-chips">
      <span className="font-mono text-11 uppercase tracking-wider text-text-faint">context</span>
      {chips.map((c) => (
        <span
          key={c.key}
          className="flex items-center gap-1.5 rounded-chip border border-cyan/50 bg-bg-1 px-2.5 py-1 font-sans text-12 text-text"
        >
          <span className="font-mono text-11 text-cyan">{KIND_GLYPH[c.type] ?? '◈'}</span>
          <span className="max-w-[220px] truncate">{c.label}</span>
          <button
            aria-label={`remove ${c.label}`}
            onClick={() => useUI.getState().removeChip(c.key)}
            className="font-mono text-11 text-text-faint hover:text-neg"
          >
            ✕
          </button>
        </span>
      ))}
    </div>
  );
}
