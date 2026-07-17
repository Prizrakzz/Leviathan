import { getDocument, GlobalWorkerOptions, type PDFDocumentLoadingTask, type PDFDocumentProxy } from 'pdfjs-dist';
import { useEffect, useRef, useState } from 'react';
import { getPdfPage } from '@/api/client';
import type { PdfPage } from '@/api/schema';

// The pdf.js worker rides its OWN hashed asset (self-contained, no CDN): vite resolves the bare specifier
// inside `new URL(..., import.meta.url)` at build. This module is only ever pulled in by a lazy() chunk
// (PdfTab), so pdf.js + its worker stay off the first-paint critical path.
GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();

/**
 * The reusable pdf.js viewer (P1.5-T3, extracted from the since-deleted 6.5 PdfModal): resolve a cited
 * source to a presigned URL + 1-indexed page (`client.getPdfPage`), raster to a canvas, page nav +
 * download escape. PROP-driven (no store) so any host surface can mount it. Every fallback is
 * first-class: null page → "page unknown" banner at top; resolve/load error → raw-download link.
 * Same-doc guard: when only the locator-within-the-doc changes (a second citation into an open doc),
 * re-resolve the PAGE but never re-download the document bytes.
 */
export function PdfViewer({
  sourceKey,
  snippet,
  charStart,
  offsetKind,
}: {
  sourceKey: string;
  snippet?: string;
  charStart?: number;
  offsetKind?: string;
}) {
  const [meta, setMeta] = useState<PdfPage | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageNum, setPageNum] = useState(1);
  const [pageUnknown, setPageUnknown] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const docRef = useRef<PDFDocumentProxy | null>(null);
  const taskRef = useRef<PDFDocumentLoadingTask | null>(null);
  const loadedKeyRef = useRef<string | null>(null);

  // Resolve (presign + page) then fetch the bytes. `disableRange`/`disableStream` force a whole-object GET,
  // which sidesteps the S3 Range CORS preflight (there is no bucket CORS today). Re-runs if the target
  // changes; the cleanup destroys the previous doc + cancels a late resolve so state can't land after close.
  useEffect(() => {
    if (!sourceKey) return;
    let cancelled = false;
    const sameDoc = loadedKeyRef.current === sourceKey && docRef.current != null;
    if (!sameDoc) {
      setLoading(true);
      setMeta(null);
      setNumPages(0);
    }
    setError(null);
    getPdfPage(sourceKey, snippet, charStart, offsetKind)
      .then(async (m) => {
        if (cancelled) return;
        setMeta(m);
        setPageUnknown(m.page == null);
        setPageNum(m.page ?? 1);
        if (sameDoc) return; // page jump only — the loaded document is reused, no re-download
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
        loadedKeyRef.current = sourceKey;
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
    };
  }, [sourceKey, snippet, charStart, offsetKind]);

  // Unmount teardown (separate from the resolve effect so a same-doc page jump never destroys the doc).
  useEffect(
    () => () => {
      const task = taskRef.current;
      taskRef.current = null;
      docRef.current = null;
      loadedKeyRef.current = null;
      void task?.destroy?.();
    },
    [],
  );

  // Raster the current page. pdf.js v6 takes the canvas directly (it owns the 2d context). A per-page raster
  // failure is swallowed — the nav + download links must survive it, so the viewer never blanks mid-read.
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
    <div className="flex h-full min-h-0 flex-col" data-testid="pdf-viewer">
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
        <div className="flex items-center gap-3">
          {meta?.url && (
            <a href={meta.url} target="_blank" rel="noopener noreferrer" download className={link}>
              download ▾
            </a>
          )}
          <button
            type="button"
            disabled={!canNext}
            onClick={() => setPageNum((n) => n + 1)}
            className="hover:text-cyan disabled:opacity-40"
          >
            next ›
          </button>
        </div>
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
    </div>
  );
}
