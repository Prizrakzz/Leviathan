import * as Dialog from '@radix-ui/react-dialog';
import { getDocument, GlobalWorkerOptions, type PDFDocumentLoadingTask, type PDFDocumentProxy } from 'pdfjs-dist';
import { useEffect, useRef, useState } from 'react';
import { getPdfPage, type PdfPage } from '@/api/client';
import { usePdf } from '@/store/pdf';

// The pdf.js worker rides its OWN hashed asset (self-contained, no CDN): vite resolves the bare specifier
// inside `new URL(..., import.meta.url)` at build. This module is only ever pulled in by a lazy() chunk, so
// pdf.js + its worker stay off the first-paint critical path.
GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();

/**
 * The PDF click-to-page modal (6.5). Resolves a cited source to a presigned URL + the 1-indexed page the
 * passage was found on (`client.getPdfPage`), then rasters that page to a canvas via pdf.js, OPENING AT
 * `page ?? 1`. Every fallback is first-class so the open never dead-ends: a `null` page shows a
 * "page unknown" banner and opens at the top; a resolve/load error keeps the raw-download link (never a
 * blank modal). Mounted once, lazily, next to SettingsModal — it reads its target from the `usePdf` store,
 * and the lazy mount is gated on `open`, so pdf.js is never in a first-paint chunk.
 */
export default function PdfModal() {
  const open = usePdf((s) => s.open);
  const close = usePdf((s) => s.close);
  const sourceKey = usePdf((s) => s.sourceKey);
  const snippet = usePdf((s) => s.snippet);
  const charStart = usePdf((s) => s.charStart);
  const offsetKind = usePdf((s) => s.offsetKind);

  const [meta, setMeta] = useState<PdfPage | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageNum, setPageNum] = useState(1);
  const [pageUnknown, setPageUnknown] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const docRef = useRef<PDFDocumentProxy | null>(null);
  const taskRef = useRef<PDFDocumentLoadingTask | null>(null);

  // Resolve (presign + page) then fetch the bytes. `disableRange`/`disableStream` force a whole-object GET,
  // which sidesteps the S3 Range CORS preflight (there is no bucket CORS today). Re-runs if the target
  // changes; the cleanup destroys the previous doc + cancels a late resolve so state can't land after close.
  useEffect(() => {
    if (!sourceKey) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setMeta(null);
    setNumPages(0);
    getPdfPage(sourceKey, snippet, charStart, offsetKind)
      .then(async (m) => {
        if (cancelled) return;
        setMeta(m);
        setPageUnknown(m.page == null);
        setPageNum(m.page ?? 1);
        // Keep the loading TASK (v6: `destroy()` lives on the task, not the proxy) so cleanup tears down the
        // worker + document; the proxy is kept separately for page rasters.
        const task = getDocument({ url: m.url, disableRange: true, disableStream: true });
        taskRef.current = task;
        const doc = await task.promise;
        if (cancelled) {
          void task.destroy?.();
          return;
        }
        docRef.current = doc;
        setNumPages(doc.numPages);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
      const task = taskRef.current;
      taskRef.current = null;
      docRef.current = null;
      void task?.destroy?.();
    };
  }, [sourceKey, snippet, charStart, offsetKind]);

  // Raster the current page. pdf.js v6 takes the canvas directly (it owns the 2d context). A per-page raster
  // failure is swallowed — the nav + download links must survive it, so the modal never blanks mid-read.
  useEffect(() => {
    const doc = docRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas || numPages === 0) return;
    let cancelled = false;
    void (async () => {
      try {
        const page = await doc.getPage(Math.min(Math.max(pageNum, 1), numPages));
        if (cancelled) return;
        const viewport = page.getViewport({ scale: 1.35 });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvas, viewport }).promise;
      } catch {
        // torn range / unmounted canvas — the nav + links stay usable, so we degrade silently
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pageNum, numPages]);

  const canPrev = pageNum > 1;
  const canNext = numPages > 0 && pageNum < numPages;
  const link = 'font-mono text-11 text-cyan hover:text-amber';

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
            <div className="flex items-center gap-3">
              {meta?.url && (
                <a href={meta.url} target="_blank" rel="noopener noreferrer" download className={link}>
                  download ▾
                </a>
              )}
              <Dialog.Close aria-label="close pdf" className="font-mono text-11 text-text-faint hover:text-cyan">
                esc
              </Dialog.Close>
            </div>
          </div>

          {pageUnknown && !error && (
            <div className="border-b border-line bg-bg-2/50 px-4 py-1.5 font-mono text-11 text-amber">
              page unknown — opened at top
            </div>
          )}

          <div className="flex items-center justify-between border-b border-line px-4 py-1.5 font-mono text-11 text-text-dim">
            <button
              type="button"
              disabled={!canPrev}
              onClick={() => setPageNum((n) => Math.max(1, n - 1))}
              className="hover:text-cyan disabled:opacity-40"
            >
              ‹ prev
            </button>
            <span data-testid="pdf-page">{numPages ? `p ${pageNum} / ${numPages}` : '…'}</span>
            <button
              type="button"
              disabled={!canNext}
              onClick={() => setPageNum((n) => n + 1)}
              className="hover:text-cyan disabled:opacity-40"
            >
              next ›
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-auto bg-bg-0 p-3">
            {loading && <div className="p-6 text-center font-mono text-12 text-text-dim">loading document…</div>}
            {error && (
              <div className="p-6 text-center font-mono text-12 text-neg">
                couldn’t load this document.{' '}
                {meta?.url && (
                  <a href={meta.url} target="_blank" rel="noopener noreferrer" download className={link}>
                    download the raw file ▾
                  </a>
                )}
              </div>
            )}
            {!error && <canvas ref={canvasRef} className="mx-auto block max-w-full" />}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
