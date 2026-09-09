import * as Tooltip from '@radix-ui/react-tooltip';
import type { FrozenSnapshot, Section } from '@/api/schema';
import { resolvedFor } from '@/views/note/citations';
import { FormattedNote, renderInline } from '@/views/note/inlineFormat';
import { Sections } from '@/views/note/Sections';
import { ChartCards } from '@/views/numbers/ChartCards';
import { deriveChartCards } from '@/views/numbers/chartTriggers';
import { Numbers } from '@/views/numbers/Numbers';

/**
 * D-AM-15 — the READ-ONLY render of a frozen turn. One component serves both readers: a saved artifact
 * (private, opened from the sidebar) and a public share link (/s/:id). They are the same freeze, so they
 * must not be allowed to drift into two renderers that disagree about what a pinned answer looks like.
 *
 * READ-ONLY is enforced through the type, not by convention: `onOpen` is the D-TW-23 `CiteOpen` null, the
 * DECLARED "no receipts behind this render" state. It is the truthful value here for the same reason it is
 * on a durable PastTurn — the drawer's retrieved-but-uncited tier and the verifier line are not in the
 * snapshot, and a chip that looks live and swallows the click is exactly the defect D-TW-23 fixed. Chips
 * still hover their official name + dated snippet, which the snapshot really does carry.
 *
 * The pins are shown, not implied: `asof` and `graph_version` are what make this artifact reproducible
 * rather than merely old, so they render as chips on the header instead of living only in the payload.
 *
 * D-UX-5 — THE ARTIFACT CARRIED ITS NUMBERS ALL ALONG. `_freeze_artifact` stores the WHOLE RespondResult
 * with no field filtering, so `number_calls` and `trace` have been in every saved item since D-AM-15; the
 * READER simply never mounted them, and a saved answer reopened as prose + pins over a payload that still
 * held every figure it stood on. Both panels below are therefore ADDITIVE and need no new persistence:
 * `<Numbers>` re-renders the frozen rows (values straight out of the payload -- no fetch until a reader
 * expands one) and `<ChartCards>` re-derives the SAME deterministic triggers the live turn ran, since
 * `deriveChartCards` is a pure function of `number_calls` + `trace`. Both are pinned to `snapshot.asof`,
 * which is the point: their series fetches are live, and an unpinned one would draw a CURRENT-vintage line
 * under a frozen figure -- the exact "old evidence rendered as if current" failure the freeze exists to
 * prevent.
 */
export function FrozenTurn({
  snapshot,
  liveSeries = true,
}: {
  snapshot: FrozenSnapshot;
  /** Whether THIS reader can resolve `/v1/series`. The private artifact tab can (it is behind the session);
   *  the PUBLIC share page at `/s/:id` cannot -- `series_route` carries `Depends(_require_identity)`, so a
   *  signed-out reader's every chart card would mount straight into "couldn't load this chart · retry".
   *  Declared as a capability rather than sniffed, for the same reason `onOpen: CiteOpen` is (D-TW-23): a
   *  surface that cannot resolve something must SAY so in the type, not discover it at fetch time. Defaults
   *  true so the artifact tab, the reader this was built for, needs no argument. */
  liveSeries?: boolean;
}) {
  const r = snapshot.payload ?? ({ answer: '' } as FrozenSnapshot['payload']);
  const s = r.structured ?? null;
  const tldr = s?.tldr ?? '';
  const mechanism = s?.mechanism ?? '';
  const sections = (s?.sections ?? []) as Section[];
  // Floor / refusal / numbers-only turns carry no `structured` — their prose lives on `answer`, and a
  // reader that rendered nothing for them would silently lose a saved artifact's whole content.
  const flat = !tldr && !mechanism && !sections.length ? (r.answer ?? '') : '';
  const resolved = resolvedFor(r);
  const sources = (s?.sources ?? []) as { ref?: unknown; source?: unknown; date?: unknown }[];
  const label = 'font-mono text-11 uppercase tracking-wider text-text-dim';
  const chip = 'rounded-chip border border-line px-1.5 py-0.5 font-mono text-11 text-text-dim';
  // THE PIN. `snapshot.asof` first because it is the freeze's own header pin -- the date the chips above
  // already display -- with the payload's copy as the fallback for an older item written before the server
  // lifted it onto the envelope. NO `?? today` branch and no empty-string pass-through: `getSeries` drops
  // an empty `asof` from the query string and the server then defaults to `_today()`, so an unpinned panel
  // would quietly draw the current vintage beneath a frozen figure. With no as-of there is nothing honest
  // to draw, so nothing is drawn.
  const asof = snapshot.asof ?? r.asof ?? '';
  // "No empty panel" is asserted here rather than left to the children. Both DO self-gate to null, but the
  // wrapper carries the margin, and a wrapper that renders around two nulls is a visible gap under the
  // sources row on every prose-only artifact. `deriveChartCards` is pure and memoized in ChartCards, so
  // asking it twice costs a derivation over an array the component already holds.
  const numberCalls = (r.number_calls ?? []) as unknown[];
  const showSeries =
    liveSeries && !!asof && (numberCalls.length > 0 || deriveChartCards(r, asof).length > 0);

  return (
    // A frozen turn's prose carries resolved [n] chips, and CitationChip renders a Radix Tooltip — which
    // THROWS without a provider ancestor. The share reader has no Shell above it at all, so this provider
    // is the only one there will ever be (the S2.2 lesson, re-learned outside the terminal).
    <Tooltip.Provider delayDuration={150}>
      <article className="max-w-3xl" data-testid="frozen-turn">
        <div className="font-mono text-12 text-cyan">▸ {snapshot.question}</div>

        <div className="mt-2 flex flex-wrap items-center gap-2" data-testid="frozen-pins">
          {snapshot.asof && <span className={chip}>as of {snapshot.asof}</span>}
          {snapshot.graph_version && (
            <span className={chip} title="the causal graph this answer was made against">
              graph {snapshot.graph_version}
            </span>
          )}
          {snapshot.created_at && <span className={chip}>frozen {snapshot.created_at}</span>}
        </div>

        {tldr && (
          <>
            <div className={`mt-4 ${label}`}>TL;DR</div>
            <p className="mt-1 font-sans text-16 font-semibold leading-snug text-text">
              {renderInline(tldr, resolved, null)}
            </p>
          </>
        )}

        {(sections.length > 0 || mechanism) && (
          <>
            <div className={`mt-4 ${label}`}>Why</div>
            <div className="mt-1 font-sans text-14 leading-relaxed text-text">
              {sections.length > 0 ? (
                <Sections sections={sections} resolved={resolved} onOpen={null} />
              ) : (
                <FormattedNote text={mechanism} resolved={resolved} onOpen={null} />
              )}
            </div>
          </>
        )}

        {flat && (
          <div className="mt-3 font-sans text-14 leading-relaxed text-text" data-testid="frozen-flat">
            <FormattedNote text={flat} resolved={resolved} onOpen={null} />
          </div>
        )}

        {sources.length > 0 && (
          <>
            <div className={`mt-4 ${label}`}>Sources</div>
            {/* Spans, not buttons: the live Note's source row OPENS the receipts drawer, which does not
                exist here. A dead-looking button is the honest render. */}
            <div className="mt-1 flex flex-wrap gap-3 font-mono text-11 text-text-dim" data-testid="frozen-sources">
              {sources.map((src, i) => (
                <span key={i}>
                  [{String(src.ref)}] {String(src.source)} {String(src.date)}
                </span>
              ))}
            </div>
          </>
        )}

        {/* The order is the LIVE surface's order (AnswerView: note+sources -> Numbers -> ChartCards), so a
            reopened turn reads like the turn did. Both self-gate to nothing: `Numbers` returns null on an
            empty `number_calls` and `ChartCards` returns null when the turn earned no trigger, so a
            prose-only artifact renders byte-for-byte what it rendered before this change -- no empty panel,
            no empty frame. */}
        {showSeries && (
          <div className="mt-4 space-y-3" data-testid="frozen-series">
            <Numbers calls={numberCalls} asof={asof} />
            <ChartCards result={r} asof={asof} />
          </div>
        )}
      </article>
    </Tooltip.Provider>
  );
}
