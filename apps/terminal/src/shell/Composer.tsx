import { useEffect, useRef } from 'react';
import { AttachedChips } from './AttachedChips';

/**
 * The follow-up composer (5.6 W4) — a ChatGPT-style prompt box pinned under the answer view, so "where do
 * I type next?" is never a question. Enter submits, Shift+Enter inserts a newline; disabled (with an
 * honest hint) while a turn streams — there is deliberately NO stop button (user decision). Refocuses
 * itself when the turn finishes. The top CommandBar stays for codes/power use.
 */
export function Composer({
  onSubmit,
  streaming,
  hero = false,
  autoFocus = true,
}: {
  onSubmit: (q: string) => void;
  streaming: boolean;
  /** Larger, centered variant for the empty state. */
  hero?: boolean;
  autoFocus?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Refocus when a turn completes so the next question needs zero mouse work.
  const prevStreaming = useRef(streaming);
  useEffect(() => {
    if (prevStreaming.current && !streaming) ref.current?.focus();
    prevStreaming.current = streaming;
  }, [streaming]);

  const grow = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`; // ~1-4 rows
  };

  const submit = () => {
    const el = ref.current;
    const q = el?.value.trim();
    if (!q || streaming) return;
    onSubmit(q);
    if (el) {
      el.value = '';
      el.style.height = 'auto';
    }
  };

  return (
    <div className={hero ? 'w-full max-w-2xl' : 'border-t border-line bg-bg-0 px-4 py-3'}>
      <AttachedChips />
      <div className="relative">
        <textarea
          ref={ref}
          rows={hero ? 2 : 1}
          autoFocus={autoFocus}
          disabled={streaming}
          aria-label="ask a follow-up"
          spellCheck={false}
          placeholder={
            streaming
              ? 'answering… (the pipeline above shows progress)'
              : hero
                ? 'ask a convexity question — e.g. "KC arabica frost risk vs 2021"'
                : 'ask a follow-up — Enter to send, Shift+Enter for a new line'
          }
          className="w-full resize-none rounded-panel border border-line bg-bg-1 px-3 py-2 pr-14 font-sans text-14 text-text placeholder:text-text-faint focus:border-cyan disabled:opacity-60"
          onInput={grow}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          data-testid={hero ? 'composer-hero' : 'composer'}
        />
        <button
          aria-label="send"
          disabled={streaming}
          onClick={submit}
          className="absolute bottom-2.5 right-2 rounded-chip border border-line px-2 py-0.5 font-mono text-11 text-cyan hover:bg-bg-2 disabled:opacity-40"
        >
          ↵
        </button>
      </div>
    </div>
  );
}
