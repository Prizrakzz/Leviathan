import type { StoreApi } from 'zustand';

/** P1.5 workspace tabs — the pure state slice, composed into useUI so tabs/activeTabId/panelPx persist
 *  under the single `lv-ui` v4 blob. RULES: params carry ONLY locators (contract/sourceKey/page...), never
 *  presigned urls or fetched content — a rehydrated tab refetches; a stale locator degrades to the tab's
 *  error state, never a crash. Tabs are WORKSPACE-GLOBAL: thread switches never touch them. This module
 *  imports no components (the kind→lazy map lives in shell/tabs/registry.tsx) so the store stays pure. */

export type TabKind = 'graph' | 'pdf';

export interface GraphTabParams {
  contract: string;
  asof?: string;
  focus?: string;
  // firing snapshot from the answer that opened the tab (ephemeral flavor, safe to persist — plain ids)
  firedRegimes?: { matched?: string[] }[];
  drivers?: string[];
}

export interface PdfTabParams {
  sourceKey: string;
  snippet?: string;
  charStart?: number;
  offsetKind?: string;
}

export interface Tab {
  id: string; // == tabKey(kind, params): stable identity => dedupe-focus on reopen
  kind: TabKind;
  title: string;
  params: GraphTabParams | PdfTabParams;
}

/** Stable identity for dedupe. asof normalizes `?? ''` — MUST match AnswerView's graphQ key family
 *  (['graph', contract, asof]) or the react-query cache splits and /v1/graph double-fetches. */
export function tabKey(kind: TabKind, params: Tab['params']): string {
  if (kind === 'graph') {
    const p = params as GraphTabParams;
    return `graph:${p.contract}:${p.asof ?? ''}`;
  }
  const p = params as PdfTabParams;
  return `pdf:${p.sourceKey}`;
}

// Panel sizing constants (Track D). The hook (hooks/usePanelDrag) imports these — store→hook never.
export const MIN_PANEL_PX = 160; // >= composer + one transcript line
export const TAB_STRIP_MIN_PX = 48; // the document area may shrink to just the strip, never less
export const DEFAULT_PANEL_PX = 320;

export interface TabsSlice {
  tabs: Tab[];
  activeTabId: string | null;
  panelPx: number;
  /** Open-or-focus: same tabKey => focus the existing tab (and refresh its params, e.g. a new page jump). */
  openTab: (t: Omit<Tab, 'id'>) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  setPanelPx: (px: number) => void;
}

type Set = StoreApi<TabsSlice>['setState'];

export function createTabsSlice(set: Set): TabsSlice {
  return {
    tabs: [],
    activeTabId: null,
    panelPx: DEFAULT_PANEL_PX,
    openTab: (t) =>
      set((s) => {
        const id = tabKey(t.kind, t.params);
        const existing = s.tabs.find((x) => x.id === id);
        if (existing) {
          // focus + refresh params (a second citation into the same doc jumps its page/snippet)
          return {
            tabs: s.tabs.map((x) => (x.id === id ? { ...x, params: t.params, title: t.title } : x)),
            activeTabId: id,
          };
        }
        return { tabs: [...s.tabs, { ...t, id }], activeTabId: id };
      }),
    closeTab: (id) =>
      set((s) => {
        const idx = s.tabs.findIndex((x) => x.id === id);
        const tabs = s.tabs.filter((x) => x.id !== id);
        const activeTabId =
          s.activeTabId !== id
            ? s.activeTabId
            : (tabs[Math.min(idx, tabs.length - 1)]?.id ?? null); // neighbor inherits focus
        return { tabs, activeTabId };
      }),
    setActiveTab: (id) => set((s) => (s.tabs.some((x) => x.id === id) ? { activeTabId: id } : s)),
    setPanelPx: (px) => set({ panelPx: px }),
  };
}
