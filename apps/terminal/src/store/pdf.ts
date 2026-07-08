import { create } from 'zustand';

/**
 * PDF click-to-page modal state (6.5) — ephemeral (not persisted), mirroring `useSettings`. A citation
 * chip or a receipts row calls `openPdf` with the cited source's text-layer `source_key` (+ the snippet
 * and, when the prop carries one, the char offset the backend uses to resolve an EXACT page); the modal
 * mounts lazily off `open` and fetches the presigned URL + resolved page. `close` leaves the other fields
 * in place — the lazy mount unmounts on `open=false`, so a stale key is never read.
 */
export interface PdfArgs {
  sourceKey: string;
  snippet?: string;
  charStart?: number;
  offsetKind?: string;
}

export interface PdfState extends PdfArgs {
  open: boolean;
  sourceKey: string;
  openPdf: (args: PdfArgs) => void;
  close: () => void;
}

export const usePdf = create<PdfState>((set) => ({
  open: false,
  sourceKey: '',
  snippet: undefined,
  charStart: undefined,
  offsetKind: undefined,
  openPdf: ({ sourceKey, snippet, charStart, offsetKind }) =>
    set({ open: true, sourceKey, snippet, charStart, offsetKind }),
  close: () => set({ open: false }),
}));
