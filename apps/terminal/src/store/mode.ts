import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * D-AM-14 — the reasoning-mode selection, and the ONE place its wire rule lives.
 *
 * The backend (leviathan.graphrag.reasoning_modes) knows exactly three modes and treats `standard` as a
 * PASSTHROUGH PIN: a standard turn resolves to an empty knob dict and every seam runs byte-identical to
 * the pre-wave code. This module mirrors that pin on the client: `modeParam` returns undefined for
 * standard (and for anything it does not recognise), so the transport OMITS the field entirely and a
 * standard turn sends the exact query string it sent before this wave. That is the whole reason the
 * omit rule is a function and not an `if` at a call site -- one rule, one place, one test.
 *
 * The store persists to localStorage `lv-mode` (its own key, not the `lv-ui` blob: a reasoning-depth
 * choice is not an appearance preference, and keeping it separate means a corrupt/foreign value can
 * never take the accent + workspace tabs down with it). `merge` -- not `migrate` -- does the coercion,
 * because merge runs on EVERY rehydrate: a stored `{"mode":"ultra"}` at the CURRENT version would sail
 * past a version-gated migrate and graft an unknown name onto the store.
 */
export type ModeName = 'quick' | 'standard' | 'deep';

/** Ratified order: shallow -> deep. Drives the picker's option order and its arrow-key traversal. */
export const MODES: readonly ModeName[] = ['quick', 'standard', 'deep'] as const;

/** The passthrough. Never sent on the wire; needs no server flag. */
export const DEFAULT_MODE: ModeName = 'standard';

/** Static v1 selector copy (D-AM-14). Deliberately RELATIVE -- no invented milliseconds. The live
 *  per-mode p50s exist only once stage-1 traffic has run through the EMF `mode` dimension; until then a
 *  precise number on screen would be a number nobody measured. */
export interface ModeCopy {
  /** the time expectation, one word/phrase, shown next to the name */
  time: string;
  /** why it costs what it costs, in engine terms the desk can check against the trace chip */
  detail: string;
}

export const MODE_COPY: Record<ModeName, ModeCopy> = {
  quick: { time: 'faster', detail: 'narrower evidence, a one-hop walk' },
  standard: { time: 'baseline', detail: 'the depth every answer has shipped at' },
  deep: {
    time: '~2-3x slower',
    detail: 'several times the evidence, a three-hop walk, all cascade legs',
  },
};

export function isMode(v: unknown): v is ModeName {
  return typeof v === 'string' && (MODES as readonly string[]).includes(v);
}

/**
 * The WIRE value for a selection: the mode name for a recognised NON-standard mode, `undefined` for
 * everything else (standard, absent, empty, a name from a newer bundle's store blob).
 *
 * `undefined` means OMIT THE FIELD -- not send an empty one. The backend fails open on an unknown name
 * (resolve() -> standard + invalid:true, never a 422), so this is belt-and-braces rather than
 * validation; what it really buys is the byte-identity of a standard request.
 */
export function modeParam(mode?: string | null): ModeName | undefined {
  return isMode(mode) && mode !== DEFAULT_MODE ? mode : undefined;
}

export interface ModeState {
  mode: ModeName;
  setMode: (m: ModeName) => void;
}

export const useMode = create<ModeState>()(
  persist(
    (set) => ({
      mode: DEFAULT_MODE,
      // Coerced on the way IN as well as on the way out of storage: the store shape may only ever hold
      // one of the three names, so no consumer needs its own guard.
      setMode: (m) => set({ mode: isMode(m) ? m : DEFAULT_MODE }),
    }),
    {
      name: 'lv-mode',
      version: 1,
      partialize: (s) => ({ mode: s.mode }),
      merge: (persisted, current) => ({
        ...current,
        mode: isMode((persisted as { mode?: unknown } | null)?.mode)
          ? ((persisted as { mode: ModeName }).mode)
          : DEFAULT_MODE,
      }),
    },
  ),
);
