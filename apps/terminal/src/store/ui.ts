import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { type ChipsSlice, createChipsSlice } from '@/store/chips';
import { createTabsSlice, DEFAULT_PANEL_PX, type TabsSlice } from '@/store/tabs';
import { type AccentName, applyAccent } from '@/tokens/tokens';

/** Terminal UI state (design §7): thread visibility, the receipts drawer, the accent. `accent` +
 *  `threadCollapsed` persist across reloads (localStorage `lv-ui`); the as-of still rides the URL via
 *  useUrlSync. The accent (6.6 Appearance) is client-only + instant — setAccent re-applies the CSS vars
 *  synchronously so the swap has no round-trip.
 *  D-TW-15 removed `view`/`setView` (a single-member enum since the 5.6 view-prune: Answer is the only
 *  view, so every write set it to the value it already held) and `focusedPanel`/`focusPanel` (written by
 *  the 1-4 hotkeys, read by nothing). D-TW-14b removed `paletteOpen`/`setPalette` with the palette. */
export interface UIState extends TabsSlice, ChipsSlice {
  accent: AccentName;
  threadCollapsed: boolean;
  receiptsOpen: boolean;
  setAccent: (a: AccentName) => void;
  toggleThread: () => void;
  setReceipts: (open: boolean) => void;
  toggleReceipts: () => void;
}

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      ...createTabsSlice(set), // P1.5 workspace tabs + panelPx (persisted via partialize below)
      ...createChipsSlice(set), // P2 context chips — EPHEMERAL (absent from partialize; thread-switch clears)
      accent: 'cyan', // the design default; 'amber' = a monochrome amber terminal (6.6)
      threadCollapsed: false,
      receiptsOpen: false,
      setAccent: (a) => {
        applyAccent(a); // instant, before the store notifies subscribers — no flash
        set({ accent: a });
      },
      toggleThread: () => set((s) => ({ threadCollapsed: !s.threadCollapsed })),
      setReceipts: (open) => set({ receiptsOpen: open }),
      toggleReceipts: () => set((s) => ({ receiptsOpen: !s.receiptsOpen })),
    }),
    {
      name: 'lv-ui',
      // v2 (5.6 view-prune): a returning user's localStorage may hold view:'convergence'/'deep' or a stale
      // `contract` — both removed. v3 (P1 W1.6): threadCollapsed becomes persisted — a pre-v3 blob lacks
      // it; backfill false. v4 (P1.5 workspace): tabs/activeTabId/panelPx become persisted (locator-only
      // params — a rehydrated tab refetches by contract/sourceKey, never replays a url).
      // v5 (D-TW-15 view-prune finished): `view` leaves the store shape entirely. persist SHALLOW-MERGES
      // the stored blob into the live state, so a v1-v4 blob would otherwise graft a dead `view` key back
      // onto the store on every boot — migrate drops it (and `contract`) instead.
      version: 5,
      migrate: (s: unknown) => {
        const prev = (s ?? {}) as Record<string, unknown>;
        const { contract: _contract, view: _view, ...rest } = prev;
        return {
          ...rest,
          threadCollapsed: typeof rest.threadCollapsed === 'boolean' ? rest.threadCollapsed : false,
          tabs: Array.isArray(rest.tabs) ? rest.tabs : [],
          activeTabId: typeof rest.activeTabId === 'string' ? rest.activeTabId : null,
          panelPx: typeof rest.panelPx === 'number' ? rest.panelPx : DEFAULT_PANEL_PX,
        };
      },
      partialize: (s) => ({
        accent: s.accent,
        threadCollapsed: s.threadCollapsed,
        tabs: s.tabs,
        activeTabId: s.activeTabId,
        panelPx: s.panelPx,
      }),
    },
  ),
);
