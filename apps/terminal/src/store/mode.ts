import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * D-AM-14 / D-DR-3 — what the ask bar is set to, and the ONE place its wire rule lives.
 *
 * TWO LAYERS, deliberately not one:
 *
 *  1. INTERNAL MODE IDENTIFIERS (`quick`/`standard`/`deep`) — frozen by the D-CC/D-DR naming law. They ride
 *     EMF dimensions, trace stamps and every stored baseline; renaming them mid-estate mixes dashboard
 *     populations (the D-AM-11 warning). `ModeName`, `MODES`, `isMode` and `modeParam` below are therefore
 *     UNTOUCHED by the two-mode relabel, including the `standard` passthrough pin — the backend
 *     (leviathan.graphrag.reasoning_modes) still resolves `standard` to an empty knob dict, and `modeParam`
 *     still omits it, so a no-request/API caller keeps byte-identical semantics even though no UI path can
 *     reach it any more.
 *
 *  2. THE PICKER CHOICE (`quick` | `deep_research`) — what a human selects. D-DR-3 collapses the selector to
 *     two entries: **Standard**, which is the LABEL for the `quick` preset and SENDS `mode=quick` on every
 *     ask, and **Deep Research**, which is not an ask mode at all — it switches the composer's submit into a
 *     dossier job (POST /v1/dossier). Keeping the choice in its own union is what stops `deep_research` from
 *     ever leaking onto the `mode` query param: it is not a `ModeName` and the type system says so.
 *
 * The store persists to localStorage `lv-mode` (its own key, not the `lv-ui` blob: a depth choice is not an
 * appearance preference, and a corrupt/foreign value must never take the accent + workspace tabs down with
 * it). `merge` — not `migrate` — does the coercion, because merge runs on EVERY rehydrate: a stored
 * `{"choice":"ultra"}` at the CURRENT version would sail past a version-gated migrate and graft an unknown
 * name onto the store. A v1 blob (which held `mode`, one of three names) has no `choice` key at all and so
 * lands on the default — deliberately: `deep`/`standard` are no longer selectable, and silently promoting a
 * returning user's stored `deep` into Deep Research would spend one of their four monthly dossiers on a
 * choice they never made.
 */
export type ModeName = 'quick' | 'standard' | 'deep';

/** Ratified order: shallow -> deep. The INTERNAL roster; `isMode`/`modeParam` are its only readers. */
export const MODES: readonly ModeName[] = ['quick', 'standard', 'deep'] as const;

/** The passthrough. Never sent on the wire; needs no server flag. Dark from the UI since D-DR-3. */
export const DEFAULT_MODE: ModeName = 'standard';

/** D-DR-3: what **Standard** sends. One constant, so the "the label is Standard, the wire says quick"
 *  mapping is stated once and every call site is a lookup rather than a literal. */
export const ASK_MODE: ModeName = 'quick';

/** The two things the ask bar can be set to. `deep_research` is a SUBMIT ROUTE, not a mode. */
export type PickerChoice = 'quick' | 'deep_research';

/** Picker order: the ordinary ask first, the job second. Drives arrow-key traversal too. */
export const CHOICES: readonly PickerChoice[] = ['quick', 'deep_research'] as const;

export const DEFAULT_CHOICE: PickerChoice = 'quick';

/** Static selector copy. Deliberately RELATIVE — no invented milliseconds (the D-AM-13 rule): per-mode p50s
 *  exist only in the EMF `mode` dimension, and a precise number on screen before that is a number nobody
 *  measured. The dossier's "minutes" is the D-DR-1 design envelope (5-20 min, 20-min wall clock), which is a
 *  shape the user must know before spending one of four monthly runs — not a latency claim. */
export interface ChoiceCopy {
  /** The LABEL a human reads. Internal identifiers never appear on screen. */
  label: string;
  /** The time expectation, one word/phrase, shown next to the label. */
  time: string;
  /** What it does, in terms the desk can check against the trace chip / the artifact it lands in. */
  detail: string;
}

export const CHOICE_COPY: Record<PickerChoice, ChoiceCopy> = {
  quick: {
    label: 'Standard',
    time: 'one turn',
    detail: 'a grounded, cited answer to this question',
  },
  deep_research: {
    label: 'Deep Research',
    time: 'minutes',
    detail: 'a planned set of sub-questions, delivered as a saved artifact',
  },
};

export function isMode(v: unknown): v is ModeName {
  return typeof v === 'string' && (MODES as readonly string[]).includes(v);
}

export function isChoice(v: unknown): v is PickerChoice {
  return typeof v === 'string' && (CHOICES as readonly string[]).includes(v);
}

/** Does this selection submit a DOSSIER instead of a turn? The one predicate Shell branches on. */
export function isDossierChoice(v: unknown): boolean {
  return v === 'deep_research';
}

/**
 * The WIRE value for an internal mode: the mode name for a recognised NON-standard mode, `undefined` for
 * everything else (standard, absent, empty, a name from a newer bundle's store blob).
 *
 * `undefined` means OMIT THE FIELD — not send an empty one. The backend fails open on an unknown name
 * (resolve() -> standard + invalid:true, never a 422), so this is belt-and-braces rather than validation;
 * what it buys is the byte-identity of a standard request for the no-request/API callers that still have one.
 */
export function modeParam(mode?: string | null): ModeName | undefined {
  return isMode(mode) && mode !== DEFAULT_MODE ? mode : undefined;
}

export interface ModeState {
  choice: PickerChoice;
  setChoice: (c: PickerChoice) => void;
}

export const useMode = create<ModeState>()(
  persist(
    (set) => ({
      choice: DEFAULT_CHOICE,
      // Coerced on the way IN as well as on the way out of storage: the store shape may only ever hold one
      // of the two choices, so no consumer needs its own guard.
      setChoice: (c) => set({ choice: isChoice(c) ? c : DEFAULT_CHOICE }),
    }),
    {
      name: 'lv-mode',
      // v2 (D-DR-3): the persisted key changes from `mode` (three internal names) to `choice` (two picker
      // entries) -- see the header note on why a v1 `deep` is NOT promoted to Deep Research.
      version: 2,
      partialize: (s) => ({ choice: s.choice }),
      merge: (persisted, current) => ({
        ...current,
        choice: isChoice((persisted as { choice?: unknown } | null)?.choice)
          ? (persisted as { choice: PickerChoice }).choice
          : DEFAULT_CHOICE,
      }),
    },
  ),
);
