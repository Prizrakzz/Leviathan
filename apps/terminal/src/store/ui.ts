import { create } from 'zustand';

export type ViewName = 'answer' | 'convergence' | 'deep';

/** Terminal UI state (design §7): active view, thread visibility, palette/receipts drawers, active contract. */
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

export const useUI = create<UIState>((set) => ({
  view: 'convergence', // cold-start landing (design §3.2 / §5)
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
}));
