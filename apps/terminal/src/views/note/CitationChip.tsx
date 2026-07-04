import * as Tooltip from '@radix-ui/react-tooltip';
import type { ResolvedCite } from './citations';

/** An inline `[1]` / `[N1]` citation chip: hover → the dated snippet; click → opens the Receipts drawer
 *  scrolled to that item (design §4.1). Amber = evidence, cyan = a number citation. */
export function CitationChip({
  refId,
  resolved,
  onOpen,
}: {
  refId: string;
  resolved: ResolvedCite;
  onOpen: (ref: string) => void;
}) {
  const isNumber = /^[A-Za-z]/.test(refId); // N1 / E2 …
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <button
          type="button"
          onClick={() => onOpen(refId)}
          className={`mx-0.5 rounded-chip border px-1 align-baseline font-mono text-11 hover:bg-bg-2 ${
            isNumber ? 'border-cyan text-cyan' : 'border-amber text-amber'
          }`}
        >
          [{refId}]
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          sideOffset={4}
          className="z-50 max-w-xs rounded-panel border border-line bg-bg-1 p-2 font-sans text-12 text-text shadow-lg"
        >
          <div className="font-mono text-11 text-text-dim">
            {resolved.source} · {resolved.date}
          </div>
          {resolved.text && <div className="mt-1 text-text-dim">{resolved.text}</div>}
          <Tooltip.Arrow className="fill-line" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
