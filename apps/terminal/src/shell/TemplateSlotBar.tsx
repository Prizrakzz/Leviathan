import { useCompose } from '@/store/compose';

/**
 * D-UX-1 — the slot bar: one combobox per blank in the template the composer is currently carrying.
 *
 * A native `<input list=…>` + `<datalist>` IS the combobox this wave asked for: the dropdown offers the
 * catalog values (census-gated server-side — `vocab.pairs` only ever names a realizable cascade) and free
 * typing is allowed BY CONSTRUCTION, not by a flag we could get wrong. No popup to manage, no focus trap, no
 * new dependency, and it degrades to a plain text input in any environment without datalist support.
 *
 * Editing a slot rewrites that span of the question in place (store: `setSlot`) — the analyst watches the
 * sentence change, which is the point of prefilling instead of submitting. Renders NOTHING when there is no
 * template attached, so every other compose path (typing, a plain prefill, a detached edit) is byte-identical
 * to before this existed.
 */
export function TemplateSlotBar() {
  const template = useCompose((s) => s.template);
  const slots = useCompose((s) => s.slots);
  const values = useCompose((s) => s.values);
  const options = useCompose((s) => s.options);

  if (!template || slots.length === 0) return null;

  return (
    <div
      data-testid="slot-bar"
      className="mb-1.5 flex flex-wrap items-center gap-2 rounded-panel border border-line bg-bg-1 px-2 py-1.5"
    >
      <span className="font-mono text-11 uppercase tracking-wider text-text-faint">fill</span>
      {slots.map((name) => (
        <span key={name} className="flex items-center gap-1">
          <span className="font-mono text-11 text-text-dim">{name}</span>
          <input
            list={`slot-vocab-${name}`}
            aria-label={`${name} slot`}
            data-testid={`slot-input-${name}`}
            spellCheck={false}
            value={values[name] ?? ''}
            placeholder={`{${name}}`}
            onChange={(e) => useCompose.getState().setSlot(name, e.target.value)}
            className="w-44 rounded-chip border border-line bg-bg-0 px-2 py-0.5 font-sans text-12 text-text placeholder:text-text-faint focus:border-cyan"
          />
          <datalist id={`slot-vocab-${name}`} data-testid={`slot-vocab-${name}`}>
            {(options[name] ?? []).map((o) => (
              <option key={o} value={o} />
            ))}
          </datalist>
        </span>
      ))}
      <button
        onClick={() => useCompose.getState().detach()}
        aria-label="dismiss slots"
        title="dismiss the slot bar (the question stays)"
        className="ml-auto rounded-chip border border-line px-1.5 py-0.5 font-mono text-11 text-text-dim hover:border-cyan hover:text-cyan"
      >
        ×
      </button>
    </div>
  );
}
