import * as Tooltip from '@radix-ui/react-tooltip';
import { usePdf } from '@/store/pdf';
import { useUI } from '@/store/ui';
import type { ResolvedCite } from './citations';

/** The number citation's query provenance line (6.4): "{table} · {metric} · {scope} · asof {asof}". */
function numberProvenance(loc: Record<string, unknown>): string {
  const parts = [loc.table, loc.metric, loc.commodity, loc.country, loc.period && `MY${loc.period}`]
    .filter(Boolean)
    .map(String);
  const asof = loc.asof ? ` · asof ${String(loc.asof)}` : '';
  return parts.join(' · ') + asof;
}

/** An inline `[1]` / `[N1]` citation chip: hover → the official source + dated snippet (or a number's query
 *  provenance); click → opens the Receipts drawer PINNED to that item (design §4.1, 6.4). Amber = evidence,
 *  cyan = a number citation. */
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
  const loc = resolved.locator;
  const isNumberLoc = loc?.kind === 'number';
  const isDocLoc = loc?.kind === 'doc' && typeof loc.source_key === 'string';
  const setView = useUI((s) => s.setView);
  const setContract = useUI((s) => s.setContract);
  const openPdf = usePdf((s) => s.openPdf);
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
          {isNumberLoc && loc && (
            <>
              <div className="mt-1 font-mono text-11 text-text-dim">{numberProvenance(loc)}</div>
              {typeof loc.commodity === 'string' && (
                <button
                  onClick={() => {
                    setContract(loc.commodity as string);
                    setView('deep');
                  }}
                  className="mt-1 font-mono text-11 text-cyan hover:text-amber"
                >
                  open series ▸
                </button>
              )}
            </>
          )}
          {/* 6.5: a doc citation opens its SOURCE PDF at the cited page — the clean slot beside the
              number branch's "open series" (which stays number-gated). */}
          {isDocLoc && loc && (
            <button
              onClick={() =>
                openPdf({
                  sourceKey: loc.source_key as string,
                  snippet: typeof loc.snippet === 'string' ? loc.snippet : undefined,
                  charStart: typeof loc.char_start === 'number' ? loc.char_start : undefined,
                  offsetKind: typeof loc.offset_kind === 'string' ? loc.offset_kind : undefined,
                })
              }
              className="mt-1 block font-mono text-11 text-amber hover:text-cyan"
            >
              open PDF ▸
            </button>
          )}
          <Tooltip.Arrow className="fill-line" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
