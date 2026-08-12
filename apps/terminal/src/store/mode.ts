import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * D-AM-14 / D-DR-3 / D-MW-21 — what the ask bar is set to, and the ONE place its wire rule lives.
 *
 * TWO LAYERS, deliberately not one:
 *
 *  1. INTERNAL MODE IDENTIFIERS (`quick`/`standard`/`deep`) — frozen by the D-CC/D-DR/D-MW-22 naming law.
 *     They ride EMF dimensions, trace stamps and every stored baseline; renaming them mid-estate mixes
 *     dashboard populations (the D-AM-11 warning). `ModeName`, `MODES`, `isMode` and `modeParam` below are
 *     therefore UNTOUCHED by every relabel this product has been through, including the `standard`
 *     passthrough pin — the backend (leviathan.graphrag.reasoning_modes) still resolves `standard` to an
 *     empty knob dict, and `modeParam` still omits it, so a no-request/API caller keeps byte-identical
 *     semantics.
 *
 *  2. THE NOTCH (`quick` | `deep` | `deep_research`) — what a human selects on the depth control. D-MW-21
 *     ships the RATIFIED 2-notch depth ramp plus the dossier: **Scan** (the `quick` preset), **Analysis**
 *     (the `deep` preset, metered at one credit a turn), and **Deep Research**, which is not an ask mode at
 *     all — it switches the composer's submit into a dossier job (POST /v1/dossier). Keeping the notch in
 *     its own union is what stops `deep_research` from ever leaking onto the `mode` query param: it is not
 *     a `ModeName` and the type system says so.
 *
 * WHAT IS DELIBERATELY *NOT* HERE (the P5 dark-first pin): `max` / `max_c0` exist in the backend's preset
 * table and may be present in serving's GRAPHRAG_MODES allowlist, and they are NOT offered by this bundle.
 * `DARK_TIERS` states that absence as a fact a test can pin, rather than leaving it as something a reader
 * has to notice.
 *
 * THE RECORDED DEFAULT-PRODUCT CHANGE (R7-ratified, D-MW-21): no notch maps to `standard` any more, so the
 * ask route always sends an explicit `mode` — **Scan** sends `mode=quick`, it does not omit the field. The
 * omit-when-default idiom survives only as `modeParam`'s treatment of a `standard`/absent/unknown input,
 * which is now reachable ONLY by a no-request/API caller. `standard` remains the backend's fail-open for a
 * mode-less request; it is no longer a thing this UI can ask for.
 *
 * The store persists to localStorage `lv-mode` (its own key, not the `lv-ui` blob: a depth choice is not an
 * appearance preference, and a corrupt/foreign value must never take the accent + workspace tabs down with
 * it). BOTH coercions are present on purpose: `migrate` throws away every older-version blob (a stored
 * selection whose PRICE has changed underneath it must never be re-applied silently — v2's roster had no
 * metered notch at all), and `merge` — which runs on EVERY rehydrate, version match or not — coerces
 * anything that is not a current notch back to the default, so a blob written by a newer bundle cannot
 * graft an unknown name onto the store.
 */
export type ModeName = 'quick' | 'standard' | 'deep';

/** Ratified order: shallow -> deep. The INTERNAL roster; `isMode`/`modeParam`/the mock lane are its readers. */
export const MODES: readonly ModeName[] = ['quick', 'standard', 'deep'] as const;

/** The passthrough. Never sent by the UI; needs no server flag. Dark from the UI since D-DR-3. */
export const DEFAULT_MODE: ModeName = 'standard';

/**
 * Tiers the BACKEND may honor that this bundle deliberately never offers (the P5 2-notch ship: `max` and
 * `max_c0` stay DARK). Stated here so the roster-parity pin can assert the absence in BOTH directions —
 * a backend tier missing from the FE roster is fine ONLY when it is listed here as intentional.
 */
export const DARK_TIERS: readonly string[] = ['max', 'max_c0'] as const;

/** The three things the ask bar can be set to. `deep_research` is a SUBMIT ROUTE, not a mode. */
export type PickerChoice = 'quick' | 'deep' | 'deep_research';

/** Notch order, shallow -> deep. Deep Research is the TOP notch and stays there (D-MW-21 invariant).
 *  Drives the slider's index arithmetic and its arrow-key traversal. */
export const CHOICES: readonly PickerChoice[] = ['quick', 'deep', 'deep_research'] as const;

export const DEFAULT_CHOICE: PickerChoice = 'quick';

/**
 * The WIRE name each notch asks at, or `null` for the notch that is not an ask at all. One table, so
 * "the label is Scan, the wire says quick" is stated once and every call site is a lookup, never a literal.
 */
export const CHOICE_MODE: Record<PickerChoice, ModeName | null> = {
  quick: 'quick',
  deep: 'deep',
  deep_research: null,
};

/**
 * What a turn at this notch COSTS against the monthly credit grant. Scan is UNMETERED by ratified policy
 * (the default experience is never metered). Deep Research is 0 HERE because it is metered by its own,
 * separate monthly allowance (GET /v1/dossier/quota) — two meters, two badges, deliberately.
 */
export const CHOICE_COST: Record<PickerChoice, number> = { quick: 0, deep: 1, deep_research: 0 };

/** Does choosing this notch spend a credit? The predicate the control and the copy branch on. */
export function isMetered(c: PickerChoice): boolean {
  return (CHOICE_COST[c] ?? 0) > 0;
}

/** The `mode` value a submit at this notch carries, or `undefined` for the dossier route. */
export function askModeFor(c: PickerChoice): ModeName | undefined {
  return CHOICE_MODE[c] ?? undefined;
}

/**
 * Every wire name this bundle can put on the `mode` param. The serving allowlist (GRAPHRAG_MODES) MUST
 * contain all of them: a name the allowlist does not honor is silently resolved to `standard` by the
 * orchestrator, and the user gets a shallower turn than the one they selected with no signal at all.
 * That is the production half of the silent-drop trap, and this constant is what the pin reads.
 */
export const FE_ASK_MODES: readonly ModeName[] = CHOICES.map((c) => CHOICE_MODE[c]).filter(
  (m): m is ModeName => m !== null,
);

/** Static selector copy. Deliberately RELATIVE — no invented milliseconds (the D-AM-13 rule): per-mode p50s
 *  exist only in the EMF `mode` dimension, and a precise number on screen before that is a number nobody
 *  measured. The dossier's "minutes" is the D-DR-1 design envelope (5-20 min, 20-min wall clock), which is a
 *  shape the user must know before spending one of four monthly runs — not a latency claim. A CREDIT PRICE
 *  is not a latency number: it is the exact, measured thing the server will charge. */
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
    label: 'Scan',
    time: 'one turn',
    detail: 'a grounded, cited answer to this question — free, no credit',
  },
  deep: {
    label: 'Analysis',
    time: 'a longer turn',
    detail: 'a wider walk — more drivers, deeper cascade, more evidence weighed; one credit',
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
 * `undefined` means OMIT THE FIELD — not send an empty one. Since D-MW-21 no NOTCH can produce `undefined`
 * here (Scan sends `quick` explicitly); what the rule still buys is the byte-identity of a `standard`
 * request for the no-request/API callers that have one, and a hard floor under a corrupted stored value:
 * an unrecognised name is dropped rather than forwarded.
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
      // of the three notches, so no consumer needs its own guard.
      setChoice: (c) => set({ choice: isChoice(c) ? c : DEFAULT_CHOICE }),
    }),
    {
      name: 'lv-mode',
      // v3 (D-MW-21): the roster gains a METERED notch. v1 held `mode` (three internal names), v2 held
      // `choice` over a two-entry, entirely unmetered roster. Neither can be carried forward: a stored
      // selection made when nothing cost anything must not become a standing instruction to spend.
      version: 3,
      partialize: (s) => ({ choice: s.choice }),
      // Every older blob resolves to the default, explicitly. (Without a migrate, zustand's own
      // version-mismatch path only logs — relying on that would make the "never silently spends" property
      // an accident of a library's internals rather than something this file states.)
      migrate: () => ({ choice: DEFAULT_CHOICE }),
      merge: (persisted, current) => ({
        ...current,
        choice: isChoice((persisted as { choice?: unknown } | null)?.choice)
          ? (persisted as { choice: PickerChoice }).choice
          : DEFAULT_CHOICE,
      }),
    },
  ),
);
