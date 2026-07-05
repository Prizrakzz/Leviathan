import * as Dialog from '@radix-ui/react-dialog';
import * as ScrollArea from '@radix-ui/react-scroll-area';
import type { RespondResult } from '@/api/schema';
import { partitionReceipts, type ReceiptRow } from './partition';

function Row({ r }: { r: ReceiptRow }) {
  const isNum = r.kind === 'number';
  return (
    <div className="border-b border-line py-2">
      <div className="flex flex-wrap items-baseline gap-2 font-mono text-11">
        {r.ref && <span className={isNum ? 'text-cyan' : 'text-amber'}>[{r.ref}]</span>}
        <span className="text-text">{r.source}</span>
        <span className="text-text-dim">{r.date}</span>
        <span className="text-pos">≤ as-of ✓</span>
      </div>
      {r.snippet && <div className="mt-1 font-sans text-12 text-text-dim">“{r.snippet}”</div>}
    </div>
  );
}

/** The receipts drawer (design §4.3): the trust layer made explicit — cited first, then retrieved-but-
 *  uncited, then verifier strips (normally 0). Opened by `e` or a citation/node click. */
export function ReceiptsDrawer({
  result,
  open,
  onClose,
}: {
  result: RespondResult;
  open: boolean;
  onClose: () => void;
}) {
  const r = partitionReceipts(result);
  const section = 'mt-3 font-mono text-11 uppercase tracking-wider';
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-bg-0/50" />
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
          <div className="px-3 py-1 font-mono text-11 text-text-dim">
            {r.cited.length} cited · {r.strippedCount} stripped · all ≤ as-of ✓
          </div>
          <ScrollArea.Root className="min-h-0 flex-1">
            <ScrollArea.Viewport className="h-full px-3 pb-4">
              {r.cited.map((row, i) => (
                <Row key={`c${i}`} r={row} />
              ))}
              {r.uncited.length > 0 && <div className={`${section} text-text-faint`}>retrieved-but-uncited ({r.uncited.length})</div>}
              {r.uncited.map((row, i) => (
                <Row key={`u${i}`} r={row} />
              ))}
              {r.stripped.length > 0 && <div className={`${section} text-neg`}>stripped by verifier ({r.stripped.length})</div>}
              {r.stripped.map((row, i) => (
                <Row key={`s${i}`} r={row} />
              ))}
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
