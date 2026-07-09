import type { StoreApi } from 'zustand';
import type { ContextAttachment } from '@/api/schema';

export const MAX_ATTACH = 4; // §II: GET-only stream, URL-safe JSON, cap <=4 (backend re-caps server-side)

/** A rendered chip = the wire attachment + display-only fields (stripped before send). */
export type AttachedChip = ContextAttachment & { key: string; label: string };

/** Stable identity for dedupe (matches the backend's own validation targets). */
export function chipKey(a: ContextAttachment): string {
  switch (a.type) {
    case 'node':
      return `node:${a.contract}:${a.driver_id}`;
    case 'edge':
      return `edge:${a.contract}:${a.source}->${a.target}`;
    case 'event':
      return `event:${a.event_type}:${a.commodity}:${a.date ?? ''}`;
  }
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
