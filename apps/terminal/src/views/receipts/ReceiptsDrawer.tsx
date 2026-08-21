import * as Dialog from '@radix-ui/react-dialog';
import * as ScrollArea from '@radix-ui/react-scroll-area';
import { useEffect, useRef } from 'react';
import type { RespondResult } from '@/api/schema';
import { useUI } from '@/store/ui';
import { OVERLAY_SCRIM } from '@/tokens/tokens';
import { citedDrivers, partitionReceipts, type ReceiptRow } from './partition';

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
                params: { sourceKey, snippet: r.snippet, charStart: r.charStart, charEnd: r.charEnd,
                          offsetKind: r.offsetKind },
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
 *  uncited, then verifier strips (normally 0). Opened by `e` or a citation click; a click on `[n]` PINS it
 *  (6.4) — the cited list filters to that source's document, the row is ringed + scrolled to. D-TW-16 adds
 *  the outbound leg: a driver chip re-centres the causal map on the driver that fired. */
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
  // D-TW-16: the drawer is where a reader asks "what is this answer standing on" — so it is also where
  // "show me that driver on the map" belongs. Each chip opens the graph tab FOCUSED on one fired driver.
  // The tab key is `graph:<contract>:<asof>`, IDENTICAL to the answer's "open causal graph" chip, so this
  // never opens a second tab: openTab focuses the existing one and refreshes its params — i.e. re-centres
  // the map already on screen. Gated on a contract because GraphTab cannot render without one.
  const graphContract = result.contract ?? result.contracts?.[0] ?? null;
  const drivers = citedDrivers(result);
  const openDriver = (driver: string) => {
    if (!graphContract) return; // unreachable (the chips are gated on it) — this is the type narrowing
    useUI.getState().openTab({
      kind: 'graph',
      title: graphContract.replace(/_/g, ' '),
      params: {
        contract: graphContract,
        asof: r.asof,
        focus: driver,
        firedRegimes: (result.trace?.fired_regimes ?? []) as { matched?: string[] }[],
        drivers,
      },
    });
    // Close on the way out. The drawer is a MODAL dialog with a full-viewport scrim: leaving it open would
    // put the map the user just asked to see behind a dimmed, inert layer — a live affordance that looks
    // like a dead one, which is the exact class this wave is deleting.
    onClose();
  };
  // D-TW-23: resolve the clicked chip's handle to a receipt row across BOTH ref conventions on the wire.
  // A prose chip fires its TYPED display handle ('E5', 'N1', or a legacy bare '5'); a row's ref is
  // `citation.ref ?? citation.id`, and the serving Citation model (citations.py) carries only `id` -- the
  // typed form -- while `structured.sources` numbers its refs as bare integers. So: exact id first, then,
  // for an EVIDENCE handle only, the bare ledger digit. Never the reverse -- digit-matching a number handle
  // would let [N1] pin evidence row [1] (the same E4/N4 collision citations.ts keeps two maps to avoid).
  const digits = (s?: string) => (s ?? '').replace(/^[A-Za-z]+/, '');
  const rowFor = (ref: string) =>
    r.cited.find((x) => x.ref === ref) ??
    (/^N/i.test(ref)
      ? undefined
      : r.cited.find((x) => x.kind !== 'number' && !!x.ref && digits(x.ref) === digits(ref)));
  const pinnedRow = pinnedRef ? rowFor(pinnedRef) : undefined;
  const pinnedKey = pinnedRow?.sourceKey;
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
          {graphContract && drivers.length > 0 && (
            <div
              className="flex flex-wrap items-center gap-1 border-b border-line px-3 pb-2 font-mono text-11"
              data-testid="receipts-drivers"
            >
              <span className="uppercase tracking-wider text-text-faint">drivers</span>
              {drivers.map((d) => (
                <button
                  key={d}
                  onClick={() => openDriver(d)}
                  title={`centre the causal map on ${d.replace(/_/g, ' ')}`}
                  className="rounded-chip border border-line px-1.5 text-text-dim hover:border-cyan hover:text-cyan"
                >
                  {d.replace(/_/g, ' ')} ↗
                </button>
              ))}
            </div>
          )}
          <ScrollArea.Root className="min-h-0 flex-1">
            <ScrollArea.Viewport className="h-full px-3 pb-4">
              {cited.map((row, i) => (
                <Row
                  key={`c${i}`}
                  r={row}
                  // Identity against the RESOLVED row (rows come from the same `r.cited` array), so the
                  // highlight follows the same ref convention the pin filter just used.
                  highlight={!!pinnedRow && row === pinnedRow}
                  rowRef={row === pinnedRow ? (el) => (pinRow.current = el) : undefined}
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
