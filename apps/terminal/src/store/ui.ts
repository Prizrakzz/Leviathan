import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { type AccentName, applyAccent } from '@/tokens/tokens';

export type ViewName = 'answer';

/** Terminal UI state (design §7): active view, thread visibility, palette/receipts drawers.
 *  `view` + `accent` persist across reloads (localStorage `lv-ui`); URL params still win on a shared link via
 *  useUrlSync's mount read. Answer is the only view after the 5.6 view-prune (the Convergence heatmap +
 *  per-contract Deep-Dive were removed), so `view` is a single-member enum kept for the URL/hotkey plumbing.
 *  The accent (6.6 Appearance) is client-only + instant — setAccent re-applies the CSS vars synchronously so
 *  the swap has no round-trip. */
export interface UIState {
  view: ViewName;
  accent: AccentName;
  threadCollapsed: boolean;
  paletteOpen: boolean;
  receiptsOpen: boolean;
  focusedPanel: number; // 1..4
  setView: (v: ViewName) => void;
  setAccent: (a: AccentName) => void;
  toggleThread: () => void;
  setPalette: (open: boolean) => void;
  setReceipts: (open: boolean) => void;
  toggleReceipts: () => void;
  focusPanel: (n: number) => void;
}

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      view: 'answer', // the only view after the 5.6 view-prune
      accent: 'cyan', // the design default; 'amber' = a monochrome amber terminal (6.6)
      threadCollapsed: false,
      paletteOpen: false,
      receiptsOpen: false,
      focusedPanel: 1,
      setView: (v) => set({ view: v }),
      setAccent: (a) => {
        applyAccent(a); // instant, before the store notifies subscribers — no flash
        set({ accent: a });
      },
      toggleThread: () => set((s) => ({ threadCollapsed: !s.threadCollapsed })),
      setPalette: (open) => set({ paletteOpen: open }),
      setReceipts: (open) => set({ receiptsOpen: open }),
      toggleReceipts: () => set((s) => ({ receiptsOpen: !s.receiptsOpen })),
      focusPanel: (n) => set({ focusedPanel: n }),
    }),
    {
      name: 'lv-ui',
      // v2 (5.6 view-prune): a returning user's localStorage may hold view:'convergence'/'deep' or a stale
      // `contract` — both removed. Coerce any persisted view to 'answer' and drop `contract` so the store
      // never boots into a now-deleted view (which would render an empty <main>).
      // v3 (P1 W1.6): threadCollapsed becomes persisted — a pre-v3 blob lacks it; backfill false.
      // NB the next persisted-key addition (P1.5 tabs/panel split) must be a v4 bump, not a v3 edit.
      version: 3,
      migrate: (s: unknown) => {
        const prev = (s ?? {}) as Record<string, unknown>;
        const { contract: _contract, ...rest } = prev;
        return {
          ...rest,
          view: 'answer' as ViewName,
          threadCollapsed: typeof rest.threadCollapsed === 'boolean' ? rest.threadCollapsed : false,
        };
      },
      partialize: (s) => ({ view: s.view, accent: s.accent, threadCollapsed: s.threadCollapsed }),
    },
  ),
);
