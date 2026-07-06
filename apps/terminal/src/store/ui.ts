import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { type AccentName, applyAccent } from '@/tokens/tokens';

export type ViewName = 'answer' | 'convergence' | 'deep';

/** Terminal UI state (design §7): active view, thread visibility, palette/receipts drawers, active contract.
 *  `view` + `contract` + `accent` persist across reloads (localStorage `lv-ui`); URL params still win on a
 *  shared link via useUrlSync's mount read. The accent (6.6 Appearance) is client-only + instant — setAccent
 *  re-applies the CSS vars synchronously so the swap has no round-trip. */
export interface UIState {
  view: ViewName;
  contract: string | null;
  accent: AccentName;
  threadCollapsed: boolean;
  paletteOpen: boolean;
  receiptsOpen: boolean;
  focusedPanel: number; // 1..4
  setView: (v: ViewName) => void;
  setContract: (c: string | null) => void;
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
      view: 'answer', // land on the conversation, not the (heavier) heatmap (5.6 W4 user decision)
      contract: null,
      accent: 'cyan', // the design default; 'amber' = a monochrome amber terminal (6.6)
      threadCollapsed: false,
      paletteOpen: false,
      receiptsOpen: false,
      focusedPanel: 1,
      setView: (v) => set({ view: v }),
      setContract: (c) => set({ contract: c }),
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
    { name: 'lv-ui', partialize: (s) => ({ view: s.view, contract: s.contract, accent: s.accent }) },
  ),
);
