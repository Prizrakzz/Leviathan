/** Live draft of the research note (design §4.1, streamed). The synthesis is a forced tool call, so the SSE
 *  `token` deltas are partial tool-input JSON — we best-effort pull the human text (tldr/mechanism) out so the
 *  note visibly writes itself instead of blocking on the full completion. Deliberately NO integrity strip:
 *  that renders only on the FINAL, verified structured note (Note.tsx / IntegrityStrip), preserving
 *  "trust machinery renders post-verify."
 *
 *  F7 CITATION RULE. The draft is PRE-VERIFIER: the verifier runs after synthesis and strips unbacked
 *  handles (StripCount p50 1, p90 7, max 16). So while `live` is false every `[n]` handle renders INERT —
 *  visible as a dimmed marker, not clickable, not resolved to a source. Handles are activated only once
 *  `verified`/`result` has landed AND a resolved map exists (`live` + `resolved`), which is also the window
 *  where this component keeps rendering the tail of the reveal before the final Note swaps in. Net effect:
 *  nothing a user could click ever disappears. */

import * as Tooltip from '@radix-ui/react-tooltip';
import type { ResolvedMap } from './citations';
import { FormattedNote, renderInline } from './inlineFormat';

const NO_CHIPS: ResolvedMap = {}; // pre-verify: nothing is resolvable, so nothing is clickable
const noop = () => {};

function unescapeJson(s: string): string {
  return s.replace(/\\n/g, '\n').replace(/\\t/g, '  ').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
}

function field(raw: string, key: string): string {
  // a completed  "key":"…"  wins; otherwise the still-open  "key":"…(no close yet)
  const done = raw.match(new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"`))?.[1];
  if (done != null) return unescapeJson(done);
  const open = raw.match(new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)$`))?.[1];
  return open != null ? unescapeJson(open) : '';
}

/** Extract the (possibly partial) tldr + mechanism from the accumulating tool-input JSON. */
function streamingPreview(raw: string): { tldr: string; mechanism: string } {
  try {
    const o = JSON.parse(raw) as { tldr?: string; mechanism?: string };
    return { tldr: o.tldr ?? '', mechanism: o.mechanism ?? '' };
  } catch {
    return { tldr: field(raw, 'tldr'), mechanism: field(raw, 'mechanism') };
  }
}

export function StreamingNote({
  draft,
  resolved,
  live = false,
  onOpen,
}: {
  draft: string;
  /** The verifier's resolved-citation map. Only meaningful together with `live`. */
  resolved?: ResolvedMap;
  /** The turn is verified (a `verified` stage or the terminal `result` landed) → handles may go live. */
  live?: boolean;
  onOpen?: (ref: string) => void;
}) {
  const { tldr, mechanism } = streamingPreview(draft);
  if (!tldr && !mechanism) return null;
  // Activation needs BOTH the verified signal and a map to resolve against — a live flag with no receipts
  // would produce chips pointing at nothing, which is the very failure this rule exists to prevent.
  const chips = live && resolved && Object.keys(resolved).length > 0;
  const map = chips ? (resolved as ResolvedMap) : NO_CHIPS;
  const open = chips ? (onOpen ?? noop) : noop;
  const label = 'font-mono text-11 uppercase tracking-wider text-text-dim';
  const caret = <span className="ml-0.5 animate-pulse text-amber">▍</span>;
  const body = (
    <article className="max-w-3xl" data-testid="note-draft" aria-busy={!live}>
      <div className={label}>
        TL;DR {!live && <span className="text-amber">· drafting</span>}
      </div>
      <p className="mt-1 font-sans text-18 font-semibold leading-snug text-text">
        {renderInline(tldr, map, open, { inert: !chips })}
        {!mechanism && !live && caret}
      </p>
      {mechanism && (
        <>
          <div className={`mt-4 ${label}`}>Why</div>
          <div className="mt-1 font-sans text-14 leading-relaxed text-text">
            <FormattedNote text={mechanism} resolved={map} onOpen={open} inert={!chips} />
            {!live && caret}
          </div>
        </>
      )}
    </article>
  );
  // CitationChip renders a Radix Tooltip, which THROWS without a provider ancestor (the PastTurn lesson) —
  // so the live path brings its own. The inert path renders no chip and needs none.
  return chips ? <Tooltip.Provider delayDuration={150}>{body}</Tooltip.Provider> : body;
}
