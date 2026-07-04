import { create } from 'zustand';

/** The corpus spans 1973 → today (design §3.4). */
export const CORPUS_START = '1973-01-01';
export const today = (): string => new Date().toISOString().slice(0, 10);

export function clampDate(d: string): string {
  const t = today();
  if (d > t) return t;
  if (d < CORPUS_START) return CORPUS_START;
  return d;
}

export function shiftDate(d: string, days: number): string {
  const dt = new Date(`${d}T00:00:00Z`);
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

/**
 * The as-of time machine (design §3.4) — the GLOBAL knowledge horizon every data hook reads. Setting it
 * re-pins the whole terminal; `live` = the horizon is today. A single query may still override the as-of
 * for that one note via a command suffix — that override is carried on the turn, NOT in this store, so it
 * never moves the global horizon.
 */
export interface AsOfState {
  asof: string;
  live: boolean;
  corpusStart: string;
  setAsOf: (d: string) => void;
  goLive: () => void;
  step: (dir: -1 | 1, large?: boolean) => void; // ‹ / › ; large = a bigger jump (Shift)
}

export const useAsOf = create<AsOfState>((set, get) => ({
  asof: today(),
  live: true,
  corpusStart: CORPUS_START,
  setAsOf: (d) => {
    const c = clampDate(d);
    set({ asof: c, live: c === today() });
  },
  goLive: () => set({ asof: today(), live: true }),
  step: (dir, large) => get().setAsOf(shiftDate(get().asof, (large ? 30 : 1) * dir)),
}));
