/** The command bar (design §3.3): natural questions AND terse function codes. Plain Enter submits; the
 *  global ⌘↵ hotkey submits the same value. Autocomplete over tickers/metrics lands in Phase 3. */
export function CommandBar({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
}) {
  return (
    <input
      aria-label="command"
      spellCheck={false}
      autoComplete="off"
      placeholder="ask a convexity question, or a code — KC frost 2021 · SB su-ratio"
      className="w-full rounded-chip border border-line bg-bg-1 px-3 py-1 font-mono text-14 text-text placeholder:text-text-faint focus:border-cyan"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.metaKey && !e.ctrlKey && value.trim()) {
          e.preventDefault();
          onSubmit(value.trim());
        }
      }}
    />
  );
}
