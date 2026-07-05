import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ViewName = 'answer' | 'convergence' | 'deep';

/** Terminal UI state (design §7): active view, thread visibility, palette/receipts drawers, active contract.
 *  `view` + `contract` persist across reloads (5.6 W3, localStorage `lv-ui`); URL params still win on a
 *  shared link via useUrlSync's mount read. */
export interface UIState {
  view: ViewName;
  contract: string | null;
  threadCollapsed: boolean;
  paletteOpen: boolean;
  receiptsOpen: boolean;
  focusedPanel: number; // 1..4
  setView: (v: ViewName) => void;
  setContract: (c: string | null) => void;
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
      threadCollapsed: false,
      paletteOpen: false,
      receiptsOpen: false,
      focusedPanel: 1,
      setView: (v) => set({ view: v }),
      setContract: (c) => set({ contract: c }),
      toggleThread: () => set((s) => ({ threadCollapsed: !s.threadCollapsed })),
      setPalette: (open) => set({ paletteOpen: open }),
      setReceipts: (open) => set({ receiptsOpen: open }),
      toggleReceipts: () => set((s) => ({ receiptsOpen: !s.receiptsOpen })),
      focusPanel: (n) => set({ focusedPanel: n }),
    }),
    { name: 'lv-ui', partialize: (s) => ({ view: s.view, contract: s.contract }) },
  ),
);
