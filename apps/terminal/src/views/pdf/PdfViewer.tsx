import {
  getDocument,
  GlobalWorkerOptions,
  TextLayer,
  type PDFDocumentLoadingTask,
  type PDFDocumentProxy,
} from 'pdfjs-dist';
import { useEffect, useRef, useState } from 'react';
import { getPdfPage } from '@/api/client';
import type { PdfPage } from '@/api/schema';
import { buildPageMap, locateInPage, rangesForSpan, type DivRange, type TextItemLike } from './locateSpan';

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
 *
 * PHASE F — THE HIGHLIGHT. When the resolver returns `sentence`/`span` (pin-point offsets on a native
 * PDF), the raster effect also renders the pdf.js v6 TextLayer over the canvas, locates the string in the
 * find-controller page text (locateSpan.ts — raw substring first, folded fallback second), paints glow
 * rects behind the text divs, and scrolls the first hit into view once per locator. Every miss degrades to
 * exactly today's page-jump: no layer target, no glow, no error. The text layer also makes the page's text
 * SELECTABLE, which is its own small win.
 *
 * SCALE LOCK: the canvas carries `max-w-full` at a fixed raster scale (1.35), so on a narrow panel it
 * renders smaller than its intrinsic width. The text layer sizes itself from `--total-scale-factor`
 * (v6 renamed from --scale-factor; --scale-round-x/y required), so the factor is derived from the RENDERED
 * canvas box and kept fresh by a ResizeObserver — text and raster stay locked through panel drags.
 */
export function PdfViewer({
  sourceKey,
  snippet,
  charStart,
  charEnd,
  offsetKind,
}: {
  sourceKey: string;
  snippet?: string;
  charStart?: number;
  charEnd?: number;
  offsetKind?: string;
}) {
  const [meta, setMeta] = useState<PdfPage | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageNum, setPageNum] = useState(1);
  const [pageUnknown, setPageUnknown] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const textRef = useRef<HTMLDivElement | null>(null);
  const hlRef = useRef<HTMLDivElement | null>(null);
  const docRef = useRef<PDFDocumentProxy | null>(null);
  const taskRef = useRef<PDFDocumentLoadingTask | null>(null);
  const loadedKeyRef = useRef<string | null>(null);
  const renderTaskRef = useRef<{ cancel: () => void } | null>(null);
  const layerRef = useRef<TextLayer | null>(null);
  const roRef = useRef<ResizeObserver | null>(null);
  const rangesRef = useRef<DivRange[]>([]);
  const scrolledForRef = useRef<string | null>(null); // one auto-scroll per (doc, target)

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
    getPdfPage(sourceKey, snippet, charStart, offsetKind, charEnd)
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
  }, [sourceKey, snippet, charStart, charEnd, offsetKind]);

  // Unmount teardown (separate from the resolve effect so a same-doc page jump never destroys the doc).
  useEffect(
    () => () => {
      const task = taskRef.current;
      taskRef.current = null;
      docRef.current = null;
      loadedKeyRef.current = null;
      layerRef.current?.cancel();
      layerRef.current = null;
      roRef.current?.disconnect();
      roRef.current = null;
      void task?.destroy?.();
    },
    [],
  );

  /** Repaint the glow rects from the stored DOM ranges — wrapper-relative, all rects per range (a column
   *  break yields disjoint rects and every one must glow; a naive bounding box would smear the gutter). */
  const paintHighlights = () => {
    const hl = hlRef.current;
    const wrap = wrapRef.current;
    const layer = layerRef.current;
    if (!hl || !wrap) return;
    hl.replaceChildren();
    if (!layer || rangesRef.current.length === 0) return;
    const wrapBox = wrap.getBoundingClientRect();
    for (const dr of rangesRef.current) {
      const div = layer.textDivs[dr.divIndex];
      const node = div?.firstChild;
      if (!node || node.nodeType !== Node.TEXT_NODE) continue;
      const range = document.createRange();
      try {
        range.setStart(node, Math.min(dr.startOffset, node.textContent?.length ?? 0));
        range.setEnd(node, Math.min(dr.endOffset, node.textContent?.length ?? 0));
      } catch {
        continue; // a mid-layout mutation — skip the rect, keep the rest
      }
      for (const r of range.getClientRects()) {
        if (r.width <= 0 || r.height <= 0) continue;
        const d = document.createElement('div');
        d.className = 'lv-hl-rect';
        d.style.left = `${r.left - wrapBox.left}px`;
        d.style.top = `${r.top - wrapBox.top}px`;
        d.style.width = `${r.width}px`;
        d.style.height = `${r.height}px`;
        hl.appendChild(d);
      }
    }
  };

  // Raster the current page, then (Phase F) the text layer + highlight. pdf.js v6 takes the canvas directly
  // (it owns the 2d context). A per-page raster failure is swallowed — the nav + download links must
  // survive it, so the viewer never blanks mid-read.
  //
  // RENDER-TASK CANCELLATION IS LOAD-BEARING, not hygiene (caught LIVE on the WASDE rehydration path,
  // 2026-08-21): overlapping effect runs on ONE canvas make pdf.js throw "Cannot use the same canvas
  // during multiple render() operations", the catch ate it, and the page showed the PREVIOUS raster with
  // NO text layer and no glow. The `cancelled` flag only ignores results — it never stops the task —
  // so the in-flight RenderTask is tracked and .cancel()ed before any new render (and on cleanup).
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
        renderTaskRef.current?.cancel();                 // stop any in-flight raster BEFORE touching the canvas
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const renderTask = page.render({ canvas, viewport });
        renderTaskRef.current = renderTask;
        await renderTask.promise;                        // rejects RenderingCancelledException when cancelled
        if (renderTaskRef.current === renderTask) renderTaskRef.current = null;
        if (cancelled) return;

        // ── text layer (v6 TextLayer class; renderTextLayer died with v3) ────────────────────────────
        const text = textRef.current;
        const wrap = wrapRef.current;
        rangesRef.current = [];
        layerRef.current?.cancel();
        layerRef.current = null;
        if (text) text.replaceChildren();
        paintHighlights(); // clears stale glow when the target page has none
        if (!text || !wrap) return;
        const content = await page.getTextContent();
        if (cancelled) return;
        const layer = new TextLayer({ textContentSource: content, container: text, viewport });
        layerRef.current = layer;
        // Scale lock: container width comes from --total-scale-factor × raw page width; derive the factor
        // from the RENDERED canvas box so `max-w-full` shrink keeps text and raster aligned.
        const applyScale = () => {
          const shown = canvas.clientWidth || viewport.width;
          wrap.style.setProperty('--total-scale-factor', String((1.35 * shown) / viewport.width));
        };
        applyScale();
        await layer.render();
        if (cancelled) return;
        applyScale();
        roRef.current?.disconnect();
        const ro = new ResizeObserver(() => {
          applyScale();
          paintHighlights();
        });
        ro.observe(canvas);
        roRef.current = ro;

        // ── highlight: only on the RESOLVED page, sentence first, pin-point span fallback ───────────
        const onResolvedPage = meta?.page != null && pageNum === meta.page;
        const target = onResolvedPage ? (meta?.sentence ?? meta?.span ?? null) : null;
        if (!target) return;
        const items = (content.items as unknown[]).filter(
          (it): it is TextItemLike => typeof (it as { str?: unknown }).str === 'string',
        );
        const map = buildPageMap(items);
        let hit = locateInPage(map, target);
        if (!hit && meta?.span && target !== meta.span) hit = locateInPage(map, meta.span);
        if (!hit) return; // honest degrade: page-jump only, exactly today's behaviour
        rangesRef.current = rangesForSpan(map, hit.start, hit.end);
        paintHighlights();
        const first = rangesRef.current[0];
        const scrollKey = `${sourceKey}#${target}`;
        if (first != null && scrolledForRef.current !== scrollKey) {
          scrolledForRef.current = scrollKey;
          layer.textDivs[first.divIndex]?.scrollIntoView({ block: 'center' });
        }
      } catch (e) {
        // torn range / unmounted canvas — the nav + links stay usable, so we degrade silently (but never
        // invisibly: the debug line is what makes a dead text layer diagnosable without editing code)
        console.debug('[PdfViewer] raster/text-layer degraded:', e);
      }
    })();
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();                   // a re-run must never overlap the prior raster
      renderTaskRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- paintHighlights is a stable closure over refs
  }, [pageNum, numPages, meta]);

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
        {!error && (
          <div ref={wrapRef} className="lv-pdfwrap relative mx-auto w-fit max-w-full" data-testid="pdf-wrap">
            <canvas ref={canvasRef} className="block max-w-full" />
            <div ref={hlRef} className="pointer-events-none absolute inset-0" data-testid="pdf-highlights" />
            <div ref={textRef} className="lv-textlayer" data-testid="pdf-textlayer" />
          </div>
        )}
      </div>
    </div>
  );
}
