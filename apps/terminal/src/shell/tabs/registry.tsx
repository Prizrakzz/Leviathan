import { lazy } from 'react';
import { retryImport } from '@/lib/retryImport';
import type { TabKind } from '@/store/tabs';

/** The kind→component map (P1.5). Kept OUT of store/tabs.ts so the store never imports components and the
 *  heavy viewers stay in their own lazy chunks (GraphTab pulls @xyflow+dagre, PdfTab pulls pdf.js — neither
 *  may enter first paint). Adding a future kind (e.g. 'model-chart') = one new component file + one line
 *  here + the TabKind/tabKey lines in store/tabs.ts. */
export const TAB_COMPONENTS: Record<TabKind, ReturnType<typeof lazy>> = {
  graph: lazy(() => retryImport(() => import('./GraphTab'))),
  pdf: lazy(() => retryImport(() => import('./PdfTab'))),
  artifact: lazy(() => retryImport(() => import('./ArtifactTab'))),
};
