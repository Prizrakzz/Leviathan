import * as Dialog from '@radix-ui/react-dialog';
import * as ScrollArea from '@radix-ui/react-scroll-area';
import { useEffect, useRef } from 'react';
import type { RespondResult } from '@/api/schema';
import { useUI } from '@/store/ui';
import { OVERLAY_SCRIM } from '@/tokens/tokens';
import { partitionReceipts, type ReceiptRow } from './partition';

function Row({ r, highlight, rowRef }: { r: ReceiptRow; highlight?: boolean; rowRef?: (el: HTMLDivElement | null) => void }) {
  const isNum = r.kind === 'number';
  const sourceKey = r.sourceKey;
  return (
    <div ref={rowRef} className={`border-b border-line py-2 ${highlight ? 'rounded bg-bg-2/60 ring-1 ring-amber' : ''}`}>
      <div className="flex flex-wrap items-baseline gap-2 font-mono text-11">
        {r.ref && <span className={isNum ? 'text-cyan' : 'text-amber'}>[{r.ref}]</span>}
        <span className="text-text">{r.source}</span>
        <span className="text-text-dim">{r.date}</span>
        <span className="text-pos">≤ as-of ✓</span>
        {/* 6.5: a row with a text-layer key opens its source PDF at the cited page (same handler the
            citation chip uses). P1.5: as a workspace tab. Only rows with a sourceKey get the affordance. */}
        {sourceKey && (
          <button
            type="button"
            onClick={() =>
              useUI.getState().openTab({
                kind: 'pdf',
                title: r.source ?? sourceKey.split('/').pop() ?? 'Source PDF',
                params: { sourceKey, snippet: r.snippet },
              })
            }
            className="ml-auto text-text-faint hover:text-cyan"
          >
            pdf ▸
          </button>
        )}
      </div>
      {r.snippet && <div className="mt-1 font-sans text-12 text-text-dim">“{r.snippet}”</div>}
    </div>
  );
}

/** The receipts drawer (design §4.3): the trust layer made explicit — cited first, then retrieved-but-
 *  uncited, then verifier strips (normally 0). Opened by `e` or a citation/node click; a click on `[n]`
 *  PINS it (6.4) — the cited list filters to that source's document, the row is ringed + scrolled to. */
export function ReceiptsDrawer({
  result,
  open,
  onClose,
  pinnedRef,
  onClearPin,
}: {
  result: RespondResult;
  open: boolean;
  onClose: () => void;
  pinnedRef?: string | null;
  onClearPin?: () => void;
}) {
  const r = partitionReceipts(result);
  const pinnedKey = pinnedRef ? r.cited.find((row) => row.ref === pinnedRef)?.sourceKey : undefined;
  const cited = pinnedKey ? r.cited.filter((row) => row.sourceKey === pinnedKey) : r.cited;
  const pinRow = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (open && pinnedRef) pinRow.current?.scrollIntoView({ block: 'nearest' });
  }, [open, pinnedRef]);
  const section = 'mt-3 font-mono text-11 uppercase tracking-wider';
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className={`fixed inset-0 z-40 ${OVERLAY_SCRIM}`} />
        <Dialog.Content
          data-testid="receipts"
          aria-describedby={undefined}
          className="fixed right-0 top-0 z-50 flex h-full w-[420px] flex-col border-l border-line bg-bg-1"
        >
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <Dialog.Title className="font-mono text-11 uppercase tracking-wider text-text-dim">
              Receipts · {result.contract ?? '—'} · as-of {r.asof}
            </Dialog.Title>
            <Dialog.Close aria-label="close receipts" className="font-mono text-11 text-text-faint hover:text-cyan">
              esc
            </Dialog.Close>
          </div>
          <div className="flex items-center justify-between px-3 py-1 font-mono text-11 text-text-dim">
            <span>
              {cited.length} cited · {r.strippedCount} stripped · all ≤ as-of ✓
            </span>
            {pinnedKey && (
              <button onClick={onClearPin} className="text-cyan hover:text-amber">
                pinned [{pinnedRef}] · show all
              </button>
            )}
          </div>
          <ScrollArea.Root className="min-h-0 flex-1">
            <ScrollArea.Viewport className="h-full px-3 pb-4">
              {cited.map((row, i) => (
                <Row
                  key={`c${i}`}
                  r={row}
                  highlight={!!pinnedRef && row.ref === pinnedRef}
                  rowRef={row.ref === pinnedRef ? (el) => (pinRow.current = el) : undefined}
                />
              ))}
              {!pinnedKey && r.uncited.length > 0 && (
                <div className={`${section} text-text-faint`}>retrieved-but-uncited ({r.uncited.length})</div>
              )}
              {!pinnedKey && r.uncited.map((row, i) => <Row key={`u${i}`} r={row} />)}
              {!pinnedKey && r.stripped.length > 0 && (
                <div className={`${section} text-neg`}>stripped by verifier ({r.stripped.length})</div>
              )}
              {!pinnedKey && r.stripped.map((row, i) => <Row key={`s${i}`} r={row} />)}
            </ScrollArea.Viewport>
            <ScrollArea.Scrollbar orientation="vertical" className="w-1.5">
              <ScrollArea.Thumb className="rounded bg-bg-2" />
            </ScrollArea.Scrollbar>
          </ScrollArea.Root>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
