import * as Dialog from '@radix-ui/react-dialog';
import { usePdf } from '@/store/pdf';
import { PdfViewer } from './PdfViewer';

/**
 * The PDF modal (6.5) — now a thin Dialog CHROME over the extracted PdfViewer (P1.5-T3). The viewer body
 * (resolve → presign → raster, page nav, fallbacks) lives in PdfViewer and is shared with the workspace
 * PdfTab. Mounted once, lazily, next to SettingsModal; reads its target from the `usePdf` store, and the
 * lazy mount is gated on `open`, so pdf.js is never in a first-paint chunk.
 * v1 NOTE: citation clicks now push a workspace PdfTab instead of opening this modal — the modal stays
 * mounted but trigger-less (deletion is a follow-up once tabs prove out).
 */
export default function PdfModal() {
  const open = usePdf((s) => s.open);
  const close = usePdf((s) => s.close);
  const sourceKey = usePdf((s) => s.sourceKey);
  const snippet = usePdf((s) => s.snippet);
  const charStart = usePdf((s) => s.charStart);
  const offsetKind = usePdf((s) => s.offsetKind);

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && close()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-bg-0/60" />
        <Dialog.Content
          data-testid="pdf"
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[760px] max-w-[95vw] -translate-x-1/2 -translate-y-1/2 flex-col rounded-panel border border-line bg-bg-1 shadow-lg"
        >
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <Dialog.Title className="truncate font-mono text-12 uppercase tracking-wider text-text">
              Source document
            </Dialog.Title>
            <Dialog.Close aria-label="close pdf" className="font-mono text-11 text-text-faint hover:text-cyan">
              esc
            </Dialog.Close>
          </div>
          {sourceKey && (
            <PdfViewer sourceKey={sourceKey} snippet={snippet} charStart={charStart} offsetKind={offsetKind} />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
