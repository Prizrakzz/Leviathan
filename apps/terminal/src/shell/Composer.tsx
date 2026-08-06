import { useEffect, useRef } from 'react';
import { useCompose } from '@/store/compose';
import { AttachedChips } from './AttachedChips';
import { ModePicker } from './ModePicker';
import { TemplateSlotBar } from './TemplateSlotBar';

/**
 * The follow-up composer (5.6 W4) — a ChatGPT-style prompt box pinned under the answer view, so "where do
 * I type next?" is never a question. Enter submits, Shift+Enter inserts a newline; disabled (with an
 * honest hint) while a turn streams — there is deliberately NO stop button (user decision). Refocuses
 * itself when the turn finishes. The top CommandBar stays for codes/power use.
 *
 * D-AM-14 docks the reasoning-mode picker here, under the box, in BOTH variants (hero + pinned): depth is
 * chosen with the question, so the control belongs at the ask bar and nowhere else. It reads its own
 * selection from the store and Shell reads it back at submit — the composer stays a text box with no
 * mode prop to thread and no mode state to hold.
 *
 * D-UX-1 makes this box the PREFILL target for the template library and the landing starters (store/compose,
 * same no-prop posture as the mode picker). The box stays UNCONTROLLED — a prefill is written to the DOM
 * node on a `rev` change, never bound in JSX — because a controlled box would re-render the composer on
 * every keystroke of every question anyone ever types, to serve a feature used at most once per question.
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

  // D-UX-1: a PREFILL push (template chosen, or a slot edited). Keyed on `rev`, never on the text, so
  // choosing the same template twice still refills. This writes the box and NEVER submits — the analyst
  // presses Enter, which is the whole point of reverting the click-submits starters.
  const prefillRev = useCompose((s) => s.rev);
  useEffect(() => {
    if (!prefillRev) return; // rev 0 = nothing has ever been pushed; leave a fresh box alone
    const el = ref.current;
    if (!el) return;
    const { draft, focus } = useCompose.getState();
    el.value = draft;
    grow();
    if (!focus) return; // a slot edit: the caret belongs in the combobox the analyst is typing in
    el.focus();
    // Land on the first REMAINING blank so typing replaces it (cold catalog, or a slot the analyst
    // cleared); with every slot filled the caret goes to the end, ready for Enter.
    const blank = /\{\w+\}/.exec(draft);
    if (blank) el.setSelectionRange(blank.index, blank.index + blank[0].length);
    else el.setSelectionRange(draft.length, draft.length);
  }, [prefillRev]);

  const submit = () => {
    const el = ref.current;
    const q = el?.value.trim();
    if (!q || streaming) return;
    onSubmit(q);
    useCompose.getState().clear(); // the turn went out: the slot bar and its template go with it
    if (el) {
      el.value = '';
      el.style.height = 'auto';
    }
  };

  return (
    <div className={hero ? 'w-full max-w-2xl' : 'border-t border-line bg-bg-0 px-4 py-3'}>
      <AttachedChips />
      <TemplateSlotBar />
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
          onInput={(e) => {
            grow();
            // ONLY while a template is attached: keep the store's copy of the question in step with the box,
            // so a later slot pick rewrites the sentence the analyst is actually looking at rather than the
            // one the template produced. With no template (the normal typing path) this is a no-op and the
            // store never hears a keystroke.
            const c = useCompose.getState();
            if (c.template) c.syncDraft(e.currentTarget.value);
          }}
          onKeyDown={(e) => {
            // D-TW-5(a): Enter submits, Shift+Enter is a newline -- and a MODIFIED Enter is not ours at
            // all. Cmd/Ctrl+Enter is the global submit hotkey (useHotkeys), so without this guard one
            // keystroke fired BOTH handlers: this box's text and whatever sat in the top command bar
            // went out as two turns, burning two of the 50 a user gets per day. CommandBar:22 is the
            // guard this mirrors.
            if (e.key === 'Enter' && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
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
      <div className="mt-1.5 flex items-center gap-2">
        <ModePicker disabled={streaming} />
      </div>
    </div>
  );
}
