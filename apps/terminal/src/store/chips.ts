import type { StoreApi } from 'zustand';
import type { ContextAttachment } from '@/api/schema';

export const MAX_ATTACH = 4; // §II: GET-only stream, URL-safe JSON, cap <=4 (backend re-caps server-side)

/** A rendered chip = the wire attachment + display-only fields (stripped before send). */
export type AttachedChip = ContextAttachment & { key: string; label: string };

/** Stable identity for dedupe (matches the backend's own validation targets). Exported so an "is this
 *  already attached?" read (D-UX-4's chart button) uses the SAME derivation the store dedupes on -- a
 *  mirrored copy would drift and the button would offer to attach something already in the tray. */
export function chipKey(a: ContextAttachment): string {
  switch (a.type) {
    case 'node':
      return `node:${a.contract}:${a.driver_id}`;
    case 'edge':
      return `edge:${a.contract}:${a.source}->${a.target}`;
    case 'event':
      return `event:${a.event_type}:${a.commodity}:${a.date ?? ''}`;
    // D-UX-4: EVERY locator field rides the key, for the tabKey reason -- two charts differing only by
    // country (or delivery month) are DIFFERENT attachments, and a key that dropped one would silently
    // dedupe the second away and steer the next turn at the first one's series.
    case 'series':
      return `series:${a.table}:${a.metric}:${a.commodity ?? ''}:${a.country ?? ''}:${a.contract_month ?? ''}`;
  }
}

/** D-UX-4: a chart locator -> the `series` wire attachment, ready for `addChip`.
 *
 *  ATTACHING A CHART IS STEERING, NOT DATA. `axis` and `asof` are deliberately DROPPED here: axis is a
 *  drawing choice, and the as-of must be the NEXT turn's, not this chart's -- the backend re-reads the
 *  series under the new turn's own horizon, which is what stops an old chart from carrying stale (or
 *  future) numbers into a new answer. No points are ever attached. Undefined optional fields are omitted
 *  rather than sent as `undefined` so the GET `context` JSON stays minimal and stable. */
export function seriesChip(loc: {
  table: string;
  metric: string;
  commodity?: string;
  country?: string;
  contract_month?: string;
  label?: string;
}): ContextAttachment & { label: string } {
  const { table, metric, commodity, country, contract_month, label } = loc;
  return {
    type: 'series',
    table,
    metric,
    ...(commodity ? { commodity } : {}),
    ...(country ? { country } : {}),
    ...(contract_month ? { contract_month } : {}),
    label: label ?? [metric, commodity, country].filter(Boolean).join(' · '),
  };
}

/** Strip display-only key/label -> the exact wire array the GET `context` param carries. */
export function toContext(chips: AttachedChip[]): ContextAttachment[] {
  return chips.map(({ key: _k, label: _l, ...wire }) => wire as ContextAttachment);
}

/** P2 typed context attachments — EPHEMERAL per-thread state (deliberately NOT persisted: absent from
 *  the ui partialize allow-list, so the v4 blob and its migrate are untouched; cleared on thread switch
 *  by the thread.ts subscription — the thread is the context boundary). */
export interface ChipsSlice {
  attachedChips: AttachedChip[];
  /** add-or-noop: derive key; dedupe; hard-cap MAX_ATTACH (silently ignores the 5th).
   *  (Typed as union+label — Omit over the discriminated union would collapse the discriminant.) */
  addChip: (c: ContextAttachment & { label: string }) => void;
  removeChip: (key: string) => void;
  clearChips: () => void;
}

type Set = StoreApi<ChipsSlice>['setState'];

export function createChipsSlice(set: Set): ChipsSlice {
  return {
    attachedChips: [],
    addChip: (c) =>
      set((s) => {
        const key = chipKey(c);
        if (s.attachedChips.some((x) => x.key === key)) return s; // dedupe
        if (s.attachedChips.length >= MAX_ATTACH) return s; // cap
        return { attachedChips: [...s.attachedChips, { ...c, key }] };
      }),
    removeChip: (key) => set((s) => ({ attachedChips: s.attachedChips.filter((x) => x.key !== key) })),
    clearChips: () => set({ attachedChips: [] }),
  };
}
