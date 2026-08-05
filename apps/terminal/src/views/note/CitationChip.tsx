import * as Tooltip from '@radix-ui/react-tooltip';
import { useUI } from '@/store/ui';
import type { CiteOpen, ResolvedCite } from './citations';

/** D-TW-23: what a chip says when this render carries no receipts (a durable turn: the drawer's evidence
 *  tiers live only on the LIVE turn's result). Exported so the fix and its regression assert one string. */
export const NO_RECEIPTS_TITLE = 'receipts available on live turns only';

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
 *  cyan = a number citation.
 *
 *  D-TW-23: `onOpen === null` = this render has no receipts drawer to open (a durable turn). The chip then
 *  renders VISIBLY inert -- dimmed, aria-disabled, and titled with the reason -- instead of looking live and
 *  swallowing the click. The Radix tooltip is deliberately KEPT in that state: the durable receipt (official
 *  name + date + 140-char snippet + open-PDF) is exactly what a past-turn chip still has to give. */
export function CitationChip({
  refId,
  resolved,
  onOpen,
}: {
  refId: string;
  resolved: ResolvedCite;
  onOpen: CiteOpen;
}) {
  const isNumber = /^N/i.test(refId); // N4 = number (cyan); E3 / bare 3 = evidence (amber) -- the P9
  //                                     typed-handle contract: any-letter matching turned [E] chips cyan
  const loc = resolved.locator;
  const isNumberLoc = loc?.kind === 'number';
  const isDocLoc = loc?.kind === 'doc' && typeof loc.source_key === 'string';
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <button
          type="button"
          data-testid="cite-chip"
          // Not the `disabled` ATTRIBUTE: a disabled button stops firing pointer events, which would take
          // the hover tooltip (the past turn's only receipt) down with the click.
          aria-disabled={onOpen ? undefined : true}
          title={onOpen ? undefined : NO_RECEIPTS_TITLE}
          onClick={onOpen ? () => onOpen(refId) : undefined}
          className={`mx-0.5 rounded-chip border px-1 align-baseline font-mono text-11 ${
            onOpen ? 'hover:bg-bg-2' : 'cursor-default opacity-50'
          } ${isNumber ? 'border-cyan text-cyan' : 'border-amber text-amber'}`}
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
            <div className="mt-1 font-mono text-11 text-text-dim">{numberProvenance(loc)}</div>
          )}
          {/* 6.5: a doc citation opens its SOURCE PDF at the cited page. P1.5: as a WORKSPACE TAB —
              dedupe by sourceKey means a second citation into an open doc focuses it + jumps its page. */}
          {isDocLoc && loc && (
            <button
              onClick={() =>
                useUI.getState().openTab({
                  kind: 'pdf',
                  title: resolved.source ?? String(loc.source_key).split('/').pop() ?? 'Source PDF',
                  params: {
                    sourceKey: loc.source_key as string,
                    snippet: typeof loc.snippet === 'string' ? loc.snippet : undefined,
                    charStart: typeof loc.char_start === 'number' ? loc.char_start : undefined,
                    offsetKind: typeof loc.offset_kind === 'string' ? loc.offset_kind : undefined,
                  },
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
