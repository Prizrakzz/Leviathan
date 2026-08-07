import { create } from 'zustand';
import type { GalleryVocab } from '@/api/schema';

/**
 * D-UX-1 — the COMPOSE seam: how a chosen template reaches the ask box.
 *
 * The wave's first design law is "click = PREFILL, Enter = send; nothing auto-submits from a template", and
 * the template library lives in the top bar while the composer lives at the bottom of the answer view — two
 * different subtrees. A store is the seam (the P9-E1a watch-chip prefill threaded a `setCmd` callback down
 * instead, and that only worked because the command bar is Shell's own controlled state; the composer is an
 * UNCONTROLLED textarea two components below Workspace).
 *
 * WHY A SLOT BAR AND NOT INLINE TOKENS IN THE BOX. The plan allowed either. Inline `{contract}` tokens
 * rendered as comboboxes require a contenteditable ask box, which would mean rewriting Composer's
 * Enter-to-send / Shift+Enter / grow / streaming-lock behaviour — the exact surface D-TW-5(a) hardened after
 * one keystroke fired two turns. The cheaper half of the inline idea (fill the slots, select the first blank
 * so typing replaces it) offers NO vocabulary at all: the analyst has to already know which contracts the
 * book tracks, which is the thing the census gate exists to tell them. So: a slot bar of real comboboxes
 * above the box (catalog values in the dropdown, free typing always allowed), plus the select-the-first-blank
 * caret trick when a slot is still empty. The textarea stays a textarea.
 *
 * The TEXT is the truth. Every edit — a slot pick or a keystroke in the box — lands in `draft`, and a slot
 * change rewrites only that slot's SPAN, so an analyst who has already reworded the sentence does not lose
 * their edit when they retarget the contract. If a hand edit lands ON a slot's span the bar DETACHES rather
 * than guessing: the template no longer anchors the text, and silently regenerating from it would clobber
 * their words.
 *
 * The span is tracked by INDEX, not found by searching for the old value, and that is not a detail: with a
 * search, typing "corn" one letter at a time into an empty {contract} rewrites the first "c" it finds — in
 * "close", in "changed" — and the sentence dissolves as you type. Hand edits move the spans (`syncDraft`
 * re-anchors them across the edit region), slot edits move the spans after them.
 */

/** The whole slot vocabulary the gallery ships (server: `_GALLERY_SLOT`). */
const SLOT_RE = /\{(\w+)\}/g;

export const EMPTY_VOCAB: GalleryVocab = { contracts: [], regimes: [], pairs: [] };

/** slot name -> the vocab list it draws from. A slot with no mapping gets an empty dropdown and stays
 *  free-text: an unknown slot must never be a dead input. */
const VOCAB_OF: Record<string, keyof GalleryVocab> = {
  contract: 'contracts',
  regime: 'regimes',
  pair: 'pairs',
};

/** Slot names in first-appearance order, de-duped (the bar's left-to-right order matches the sentence). */
export function slotsOf(template: string): string[] {
  const out: string[] = [];
  for (const m of template.matchAll(SLOT_RE)) {
    const name = m[1] ?? '';
    if (name && !out.includes(name)) out.push(name);
  }
  return out;
}

export function optionsFor(slot: string, vocab: GalleryVocab = EMPTY_VOCAB): string[] {
  const key = VOCAB_OF[slot];
  return key ? (vocab[key] ?? []) : [];
}

/** What a slot currently OCCUPIES in the text: its value, or the brace standing in for an empty one.
 *  An EMPTY value keeps its `{slot}` brace rather than leaving a hole: a visible blank is legible (and the
 *  composer's caret lands on it), whereas "how close is the  regime in corn" reads as a rendering bug. */
function shownValue(name: string, values: Record<string, string>): string {
  return values[name]?.trim() || `{${name}}`;
}

/** The filled text AND [start, end) of each slot in it — ONE definition of the fill, so the text and its
 *  anchors can never disagree. FIRST occurrence wins for a template that repeats a slot (none do today): a
 *  stale second copy is visible and editable by hand, whereas rewriting both from one combobox would
 *  silently overwrite whatever the analyst did to the other. */
export function fillWithSpans(template: string, values: Record<string, string>) {
  let text = '';
  let last = 0;
  const spans: Record<string, [number, number]> = {};
  for (const m of template.matchAll(SLOT_RE)) {
    const name = m[1] ?? '';
    text += template.slice(last, m.index);
    const shown = shownValue(name, values);
    if (!(name in spans)) spans[name] = [text.length, text.length + shown.length];
    text += shown;
    last = m.index + m[0].length;
  }
  return { text: text + template.slice(last), spans };
}

/** Re-anchor the spans across a HAND edit of the box: the unchanged head/tail bound the edit region, so
 *  everything after it shifts by the length delta and everything before it stands. A span the edit landed
 *  INSIDE is gone — the analyst rewrote that phrase themselves — and the caller detaches rather than guess. */
function reanchor(
  prev: string,
  next: string,
  spans: Record<string, [number, number]>,
): Record<string, [number, number]> | null {
  let head = 0;
  while (head < prev.length && head < next.length && prev[head] === next[head]) head++;
  let tail = 0;
  while (
    tail < prev.length - head &&
    tail < next.length - head &&
    prev[prev.length - 1 - tail] === next[next.length - 1 - tail]
  )
    tail++;
  const editEnd = prev.length - tail; // the edit replaced prev[head, editEnd)
  const delta = next.length - prev.length;
  const out: Record<string, [number, number]> = {};
  for (const [name, [a, b]] of Object.entries(spans)) {
    if (b <= head) out[name] = [a, b];
    else if (a >= editEnd) out[name] = [a + delta, b + delta];
    else return null; // the edit landed on this slot
  }
  return out;
}

export interface ComposeState {
  /** What the ask box should carry. Mirrors the textarea (the composer syncs its own edits back). */
  draft: string;
  /** Bumped on every PUSH to the box. The composer applies on change — never on `draft` identity, so
   *  choosing the same template twice still re-prefills. */
  rev: number;
  /** Whether this push should take focus. False for slot edits: the analyst is typing IN the combobox, and
   *  stealing focus back to the textarea on each keystroke would make the bar unusable. */
  focus: boolean;
  /** The authored template the bar is bound to, or null when there is nothing to fill (plain prefill, or
   *  the analyst rewrote the anchor span and the bar detached). */
  template: string | null;
  slots: string[];
  values: Record<string, string>;
  options: Record<string, string[]>;
  /** Where each slot currently sits in `draft` — the anchor a slot edit rewrites. */
  spans: Record<string, [number, number]>;
  /** Prefill the box from a template + the slot values it was filled with. A brace-free template is just a
   *  plain prefill (no bar). NEVER submits — that is the wave's first law. */
  prefillTemplate: (template: string, seed?: Record<string, string>, vocab?: GalleryVocab) => void;
  setSlot: (name: string, value: string) => void;
  /** The composer's own keystrokes, so a later slot edit rewrites the text the analyst is actually looking at. */
  syncDraft: (text: string) => void;
  /** Drop the bar, keep the text. */
  detach: () => void;
  /** D-DR-3: put a question BACK in the box after a submit that was refused (the dossier quota 429). The
   *  composer clears optimistically on Enter -- it has to, the send is asynchronous -- so "the composer text
   *  is preserved" is implemented as: clear, and if the server says no, hand the exact words back. A plain
   *  push with no template attached, so the slot bar never reappears around a question that never had one. */
  restore: (text: string) => void;
  /** The turn went out (or the box was emptied): forget everything. */
  clear: () => void;
}

/** A function, not a shared constant: every reset gets its OWN empty collections (a shared `slots: []`
 *  handed to two stores is a mutation bug waiting for its first `push`). */
const detached = (): Pick<ComposeState, 'template' | 'slots' | 'values' | 'options' | 'spans'> => ({
  template: null,
  slots: [],
  values: {},
  options: {},
  spans: {},
});

export const useCompose = create<ComposeState>((set) => ({
  draft: '',
  rev: 0,
  focus: false,
  ...detached(),

  prefillTemplate: (template, seed = {}, vocab = EMPTY_VOCAB) => {
    const slots = slotsOf(template);
    const values: Record<string, string> = {};
    const options: Record<string, string[]> = {};
    for (const name of slots) {
      // Seed from the SERVER's own fill when it has one: {contract} and {regime} come from the same
      // near-firing row, so the sentence the analyst sees first is the true pairing the gallery advertises,
      // not an arbitrary cross-product of two dropdowns.
      values[name] = seed[name] ?? '';
      options[name] = optionsFor(name, vocab);
    }
    const { text, spans } = fillWithSpans(template, values);
    set((s) => ({
      template,
      slots,
      values,
      options,
      spans,
      draft: text,
      rev: s.rev + 1,
      focus: true,
    }));
  },

  setSlot: (name, value) =>
    set((s) => {
      const span = s.spans[name];
      if (!s.template || !span) return s;
      const [a, b] = span;
      // Defensive: the anchor must still hold what we last put there (syncDraft keeps it true, and detaches
      // when a hand edit lands on the slot). If it does not, drop the bar rather than rewrite a phrase the
      // analyst chose.
      if (s.draft.slice(a, b) !== shownValue(name, s.values)) return detached();
      const shown = value.trim() || `{${name}}`;
      const delta = shown.length - (b - a);
      const spans: Record<string, [number, number]> = {};
      for (const [n, [x, y]] of Object.entries(s.spans))
        spans[n] = n === name ? [a, a + shown.length] : x >= b ? [x + delta, y + delta] : [x, y];
      return {
        draft: s.draft.slice(0, a) + shown + s.draft.slice(b),
        values: { ...s.values, [name]: value },
        spans,
        rev: s.rev + 1,
        focus: false,
      };
    }),

  syncDraft: (text) =>
    set((s) => {
      if (text === s.draft) return s;
      if (!s.template) return { draft: text };
      const spans = reanchor(s.draft, text, s.spans);
      // A hand edit ON a slot: the template stops anchoring the text, so the bar goes and the words stay.
      return spans ? { draft: text, spans } : { draft: text, ...detached() };
    }),
  detach: () => set(detached()),
  restore: (text) => set((s) => ({ draft: text, rev: s.rev + 1, focus: true, ...detached() })),
  clear: () => set({ draft: '', ...detached() }),
}));
