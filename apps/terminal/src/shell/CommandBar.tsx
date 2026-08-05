/** The command bar (design §3.3): natural questions AND terse function codes. Plain Enter submits; the
 *  global ⌘↵ hotkey submits the same value from outside a text field. Autocomplete over tickers/metrics
 *  lands in Phase 3.
 *
 *  D-TW-5(c): DISABLED while a turn streams — the same rule (and the same faded look) as the Composer.
 *  There is deliberately no stop button, so an Enter here mid-turn used to ABORT the live answer and
 *  start a different one; nothing on screen suggested it would. */
export function CommandBar({
  value,
  onChange,
  onSubmit,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
  /** True while a turn streams. Required, not defaulted: forgetting it is exactly the defect above. */
  disabled: boolean;
}) {
  return (
    <input
      aria-label="command"
      spellCheck={false}
      autoComplete="off"
      disabled={disabled}
      placeholder={
        disabled
          ? 'answering… (the pipeline below shows progress)'
          : 'ask a convexity question, or a code — KC frost 2021 · SB su-ratio'
      }
      className="w-full rounded-chip border border-line bg-bg-1 px-3 py-1 font-mono text-14 text-text placeholder:text-text-faint focus:border-cyan disabled:opacity-60"
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
