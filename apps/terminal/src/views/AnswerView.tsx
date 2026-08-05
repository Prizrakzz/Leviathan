import * as Tooltip from '@radix-ui/react-tooltip';
import { useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { getThreadTurns, suggest } from '@/api/client';
import type { Section } from '@/api/schema';
import type { components } from '@/api/types.gen';
import type { TurnState } from '@/api/useTurn';
import { Composer } from '@/shell/Composer';
import { ErrorBoundary } from '@/shell/ErrorBoundary';
import { Pipeline } from '@/shell/Pipeline';
import { useAutoScroll } from '@/shell/useAutoScroll';
import { useSession } from '@/store/session';
import { useThread } from '@/store/thread';
import { useUI } from '@/store/ui';
import { EmptyState } from './answer/EmptyState';
import { FindingsFeed } from './answer/FindingsFeed';
import { SuggestionChips } from './answer/SuggestionChips';
import { Banners } from './note/Banners';
import { type CiteOpen, resolvedFor } from './note/citations';
import { FormattedNote, renderInline } from './note/inlineFormat';
import { IntegrityStrip } from './note/IntegrityStrip';
import { Note } from './note/Note';
import { Sections } from './note/Sections';
import { StreamingNote } from './note/StreamingNote';
import { useTypewriter } from './note/useTypewriter';
import { deriveWatchChips } from './note/watchChips';
import { Numbers } from './numbers/Numbers';
import { ReceiptsDrawer } from './receipts/ReceiptsDrawer';

type TurnRecord = components['schemas']['TurnRecord'];

// A caught render error inside a finalized answer degrades to a readable line instead of blanking the app.
const answerErrorFallback = (
  <div className="rounded-panel border border-line bg-bg-1 p-3 font-mono text-12 text-neg">
    couldn’t render this answer ·{' '}
    <button onClick={() => window.location.reload()} className="text-cyan hover:text-amber">
      reload
    </button>
  </div>
);
// S2.2: a single turn/drawer/chip throwing must degrade LOCALLY, never blank the whole terminal — the root
// boundary is the last resort, not the first (a PastTurn tooltip throw took the whole app down).
const pastTurnErrorFallback = (
  <div className="border-b border-line pb-4 font-mono text-11 text-text-faint">
    ▸ (this turn couldn’t be displayed)
  </div>
);
// INTEGRITY strip is an eval/log signal, not user-facing (6.1); show it only in debug (localStorage lv-debug=1).
const SHOW_INTEGRITY = typeof localStorage !== 'undefined' && localStorage.getItem('lv-debug') === '1';

/** One past (durable) turn of the active thread — full answer, ChatGPT-style (5.6 decision). Renders from
 *  the persisted `structured` (backend-sanitized in 6.1, so clean prose — no raw markup or internal ids).
 *  6.4: chips HOVER their official name + durable snippet via the durable resolved map (structured.sources
 *  + citation locator snippet).
 *
 *  D-TW-23 -- `onOpenReceipts`. This component renders TWO different things:
 *   (a) genuinely past turns, whose receipts do NOT exist client-side. `TurnRecord` is PIT-firewalled by
 *       construction (api_models.py: "NEVER carries retrieved evidence"; the server's `_trim_citation_
 *       provenance` keeps refs + locator pointers and drops the evidence text, and no `trace` is persisted
 *       at all). So a durable turn can populate ONLY the drawer's cited tier -- the retrieved-but-uncited
 *       tier and the whole verifier line ("N stripped / all <= as-of") would be fabricated from absent
 *       data, and the cited tier alone shows strictly LESS than the chip's own hover already does (official
 *       name + date + 140-char snippet + open-PDF). So: no drawer, and the chip SAYS so (inert + title).
 *   (b) the LIVE turn, moments after it settles: ThreadSidebar invalidates `thread-turns` on
 *       status==='done', the completed turn lands in `past`, `showLive` goes false -- and the answer on
 *       screen becomes a PastTurn render while `turn.result` is still in hand. That is the measured
 *       defect: every chip mid-session was dead while `e` still worked (the drawer hangs off the result,
 *       which survives). AnswerView passes the REAL handler for that one turn. */
export function PastTurn({ t, onOpenReceipts }: { t: TurnRecord; onOpenReceipts?: (ref?: string) => void }) {
  const onOpen: CiteOpen = onOpenReceipts ?? null;
  const s = (t.structured ?? null) as { tldr?: string; mechanism?: string; sections?: Section[] } | null;
  const tldr = s?.tldr ?? '';
  const mechanism = s?.mechanism ?? '';
  const sections = s?.sections ?? [];
  const legacy = !tldr && !mechanism && !sections.length ? (t.answer ?? '') : '';
  const resolved = resolvedFor(t as Parameters<typeof resolvedFor>[0]);
  // S5: a durable cascade/mechanism turn must keep the open-full-graph affordance the LIVE mapSlot has
  // (AnswerView.tsx:195-210) — without it, a reopened thread renders every answer through this reduced
  // PastTurn with no way to open the graph tab (the sole first-tab bootstrap). Contract guard KEPT:
  // GraphTab requires a contract; a structured-null/contract-null floor/no-match turn offers NO chip.
  const gContract = t.contract ?? t.contracts?.[0] ?? null;
  return (
    // A durable turn's tldr/mechanism can contain resolved [n] chips, and CitationChip renders a Radix
    // Tooltip — which THROWS ("must be used within TooltipProvider") without a provider ancestor. The live
    // Note has its own provider; a past turn needs its own too, else the throw (outside the answer boundary)
    // blanks the whole terminal. The mock fixture had empty sources → no chips → this stayed latent (S2.2).
    <Tooltip.Provider delayDuration={150}>
      <div className="border-b border-line pb-4" data-testid="past-turn">
        <div className="font-mono text-12 text-cyan">▸ {t.question}</div>
        {tldr && (
          <p className="mt-2 font-sans text-14 font-semibold leading-snug text-text">
            {renderInline(tldr, resolved, onOpen)}
          </p>
        )}
        {/* S5: reuse the LIVE mapSlot's exact openTab call + data-testid so a durable turn can open the
            graph tab. Gated on contract AND any content — floor/no-match (structured-null) offers none. */}
        {gContract && (tldr || sections.length || mechanism) && (
          <button
            data-testid="open-full-graph"
            onClick={() =>
              useUI.getState().openTab({
                kind: 'graph',
                title: gContract.replace(/_/g, ' '),
                params: { contract: gContract, asof: t.asof ?? '' },
              })
            }
            className="mt-2 block rounded-chip border border-line px-2 py-1 font-mono text-11 text-text-dim hover:border-cyan hover:text-cyan"
          >
            open causal graph ↗
          </button>
        )}
        {/* P9-C: sections win over the flat mechanism, same branch as the live Note — a durable turn
            persisted with sections must not reopen in the legacy render. The view stays REDUCED
            (no sources row, no numbers). */}
        {sections.length > 0 ? (
          <div className="mt-1 font-sans text-13 leading-relaxed text-text-dim">
            <Sections sections={sections} resolved={resolved} onOpen={onOpen} />
          </div>
        ) : (
          mechanism && (
            <div className="mt-1 font-sans text-13 leading-relaxed text-text-dim">
              <FormattedNote text={mechanism} resolved={resolved} onOpen={onOpen} />
            </div>
          )
        )}
        {legacy && (
          <div className="mt-1 font-sans text-13 leading-relaxed text-text-dim">
            <FormattedNote text={legacy} resolved={resolved} onOpen={onOpen} />
          </div>
        )}
        {t.asof && <div className="mt-1 font-mono text-11 text-text-faint">as of {t.asof}</div>}
      </div>
    </Tooltip.Provider>
  );
}

/** The Answer view (design §4.1), 5.6: now the CONVERSATION column — the active thread's durable past
 *  turns above the live turn, a pinned bottom composer, smooth typewriter streaming, and pin-to-bottom
 *  auto-scroll. The live turn keeps the full trust loop (pipeline → streamed draft → verified note + DAG +
 *  numbers + integrity strip + receipts). */
export function AnswerView({
  turn,
  question,
  onAsk,
  onPrefill,
}: {
  turn: TurnState;
  question: string;
  onAsk: (q: string) => void;
  /** P9-E1a: watch-chip click PREFILLS the composer (the NotificationBell setCmd path) -- never submits. */
  onPrefill?: (q: string) => void;
}) {
  const r = turn.result;
  const receiptsOpen = useUI((s) => s.receiptsOpen);
  const setReceipts = useUI((s) => s.setReceipts);
  // 6.4 click-pin: a [n] click opens the drawer pinned to that source; a node/hotkey open pins nothing.
  const [pinnedRef, setPinnedRef] = useState<string | null>(null);
  const openReceipts = (ref?: string) => {
    setPinnedRef(ref ?? null);
    setReceipts(true);
  };
  const threadId = useThread((s) => s.threadId);
  const ready = useSession((s) => s.ready);
  const { shown, settled } = useTypewriter(turn.draft, turn.status);

  const turnsQ = useQuery({
    queryKey: ['thread-turns', threadId],
    queryFn: () => getThreadTurns(threadId),
    enabled: ready,
    staleTime: 10_000,
  });
  const past = turnsQ.data?.turns ?? [];
  const lastPastQ = past.length ? past[past.length - 1]!.question : null;
  // Keep the live turn visible until the refetch pulls it into `past` (matched by question) — no flicker.
  const showLive =
    !!question &&
    (turn.status === 'streaming' ||
      turn.status === 'error' ||
      ((turn.status === 'done' || !settled) && lastPastQ !== question));

  // D-TW-23. `showLive` going false is exactly the handover: the refetch pulled THIS turn into `past`, so
  // the answer the reader is looking at is now the LAST PastTurn -- rendered from the durable copy while
  // `turn.result` is still held right here. That index (and only that one) gets the real open-receipts
  // handler, so a Sections/FormattedNote/TL;DR chip stays clickable across the settle instead of going
  // dead the instant the answer finishes arriving. Every earlier turn keeps `undefined` -> inert chips.
  const liveSettledIdx =
    !showLive && turn.status === 'done' && !!r && !!question && lastPastQ === question
      ? past.length - 1
      : -1;

  const contract = r?.contract ?? r?.contracts?.[0] ?? null;
  const asof = r?.asof ?? '';

  // 6.2 suggester — fired ONCE per completed turn (never per input). Keyed on the latest turn's
  // question: the live result and its persisted copy share the key, so the turn settling into `past`
  // never refetches. A reopened thread suggests off its LAST persisted turn.
  const lastTurn = past.length ? past[past.length - 1] : null;
  const liveDone = turn.status === 'done' && !!r?.structured && !!question;
  const suggestKey = liveDone ? question : (lastTurn?.question ?? null);
  const suggestQ = useQuery({
    queryKey: ['suggest', threadId, suggestKey],
    queryFn: () =>
      suggest(
        liveDone
          ? { thread_id: threadId, question, tldr: r?.structured?.tldr ?? null,
              contracts: r?.contracts ?? [], intent: r?.intent ?? null, asof: r?.asof ?? null }
          : { thread_id: threadId, question: lastTurn?.question ?? null,
              tldr: (lastTurn?.structured as { tldr?: string } | null)?.tldr ?? null,
              contracts: lastTurn?.contracts ?? [], intent: lastTurn?.intent ?? null,
              asof: lastTurn?.asof ?? null },
      ),
    enabled: ready && !!suggestKey && turn.status !== 'streaming' && turn.status !== 'error',
    staleTime: Infinity,
  });

  // P9-E1a: deterministic watch chips off the SAME turn the suggester keys on (live result when done,
  // else the last persisted turn). Deduped against the server texts inside the helper.
  const suggestions = suggestQ.data?.suggestions ?? [];
  const watchSource = liveDone
    ? (r?.structured ?? null)
    : ((lastTurn?.structured ?? null) as Parameters<typeof deriveWatchChips>[0]);
  const watchChips = deriveWatchChips(watchSource, suggestions);

  const scrollRef = useRef<HTMLDivElement>(null);
  useAutoScroll(
    scrollRef,
    `${shown.length}:${turn.stages.length}:${past.length}:${turn.status}:${suggestQ.data?.suggestions.length ?? 0}`,
  );

  // Brand-new thread, nothing asked yet → the hero landing.
  if (turn.status === 'idle' && !question && past.length === 0 && !turnsQ.isLoading)
    return <EmptyState onAsk={onAsk} />;

  const finalReady = turn.status === 'done' && settled && !!r;
  // The two REVEAL states (still streaming / result landed but the typewriter is still catching up) render
  // the same shape, so they are ONE branch. Split, they sat at different child slots and React unmounted
  // the whole subtree between them — remounting the findings feed and replaying every row's enter
  // animation at the exact moment the answer arrives, and silently discarding the reader's expand/collapse
  // choice with it. StreamingNote stops remounting here too (no caret/text flash across the settle).
  const revealing = turn.status === 'streaming' || (turn.status === 'done' && !settled);
  const trace = (r?.trace ?? {}) as { fired_regimes?: { matched?: string[] }[]; drivers?: string[] };
  // F7 citation rule: receipts exist only once the turn is verified (`verified` stage OR the terminal
  // `result` — useTurn sets citationsLive on either). Until then the draft's [n] handles render inert, so
  // a handle the verifier is about to strip is never something the user could have clicked.
  const citeResolved = turn.citationsLive && r ? resolvedFor(r) : undefined;

  // P1.5 (user-directed): the graph renders as a WORKSPACE TAB ONLY — never inline in the chat (the
  // double-render read as a bug). The answer carries just this chip; the tab owns rendering, its own
  // loading/error states, and a life independent of the turn. Gated to the two map-eligible states
  // (floor/refused keep their contract with structured=null and must NOT offer a graph).
  const mapSlot =
    contract && (r?.structured || r?.intent === 'numbers_only') ? (
      <button
        data-testid="open-full-graph"
        onClick={() =>
          useUI.getState().openTab({
            kind: 'graph',
            title: (contract ?? '').replace(/_/g, ' '),
            params: { contract, asof, firedRegimes: trace.fired_regimes, drivers: trace.drivers },
          })
        }
        className="mb-1 block rounded-chip border border-line px-2 py-1 font-mono text-11 text-text-dim hover:border-cyan hover:text-cyan"
      >
        open causal graph ↗
      </button>
    ) : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-auto p-4" data-testid="conversation">
        {past.map((t, i) => (
          <ErrorBoundary key={t.ts ?? i} fallback={pastTurnErrorFallback} resetKeys={[t.ts ?? i]}>
            <PastTurn t={t} onOpenReceipts={i === liveSettledIdx ? openReceipts : undefined} />
          </ErrorBoundary>
        ))}

        {showLive && (
          <div className="space-y-3">
            <div className="font-mono text-12 text-cyan">▸ {question}</div>

            {revealing && (
              <div className="rounded-panel border border-line bg-bg-1 p-3">
                <Pipeline stages={turn.stages} done={turn.status === 'done'} />
              </div>
            )}

            {turn.status === 'error' && (
              <div className="font-mono text-12 text-neg">error: {turn.error}</div>
            )}

            {/* F7: ONE feed, at a slot that exists in EVERY turn state, so it is never unmounted between
                them. It renders what the engines have already decided, as it lands (and nothing at all if
                the server emits no partials — an older deployment leaves the view exactly as it was).
                Collapsed once the writer takes over, but KEPT: the findings are the answer's provenance,
                and staying one click away beats vanishing at the moment of delivery. It also survives an
                errored turn now — engine work that really happened should not disappear with the error. */}
            <FindingsFeed findings={turn} />

            {/* The draft is PRE-VERIFIER, so its [n] handles stay inert: `chips` needs BOTH `live` AND a
                resolved map, and the map exists only once `result` has landed (`r` is `turn.result`).
                Passing `live` through the whole reveal is therefore safe — and it means the tail of the
                reveal already carries LIVE citations, so the swap into the final Note activates nothing the
                user can see change. */}
            {revealing && shown ? (
              <StreamingNote
                draft={shown}
                resolved={citeResolved}
                live={turn.citationsLive}
                onOpen={openReceipts}
              />
            ) : null}

            {finalReady && (
              // A render error inside a finalized answer (note/map/numbers) degrades to a readable line —
              // it must NEVER unmount the app (S2.1). resetKeys re-mount it on the next question.
              <ErrorBoundary fallback={answerErrorFallback} resetKeys={[question, asof]}>
                <div className="space-y-4">
                  <Banners result={r} />
                  {r.structured ? (
                    <>
                      <Note result={r} onOpenReceipts={openReceipts} afterTldr={mapSlot} />
                      <Numbers calls={r.number_calls ?? []} asof={asof} />
                      {SHOW_INTEGRITY && <IntegrityStrip result={r} />}
                    </>
                  ) : (
                    <>
                      {mapSlot}
                      {/* W1.1.3: numeric turns stream no tokens and carry no structured note — before this,
                          r.answer (the numbers markdown) rendered NOWHERE once settled. Gated on intent, NOT
                          structured==null: floor/refused are also null but already render replacement banners. */}
                      {r.intent === 'numbers_only' && r.answer && (
                        <div
                          className="max-w-3xl font-sans text-14 leading-relaxed text-text"
                          data-testid="numbers-answer"
                        >
                          <FormattedNote text={r.answer} resolved={resolvedFor(r)} onOpen={openReceipts} />
                        </div>
                      )}
                      {(r.evidence?.length ?? 0) > 0 && (
                        <button
                          className="rounded-chip border border-line px-2 py-1 font-mono text-11 text-cyan hover:bg-bg-1"
                          onClick={() => openReceipts()}
                        >
                          open receipts (e)
                        </button>
                      )}
                    </>
                  )}
                </div>
              </ErrorBoundary>
            )}
          </div>
        )}

        {turn.status !== 'streaming' && (
          <ErrorBoundary fallback={null} resetKeys={[suggestKey]}>
            <SuggestionChips items={suggestions} onAsk={onAsk} watchItems={watchChips} onPrefill={onPrefill} />
          </ErrorBoundary>
        )}
      </div>

      <Composer onSubmit={onAsk} streaming={turn.status === 'streaming'} autoFocus={false} />

      {r && (
        <ErrorBoundary fallback={null} resetKeys={[question, asof]}>
          <ReceiptsDrawer
            result={r}
            open={receiptsOpen}
            onClose={() => {
              setReceipts(false);
              setPinnedRef(null);
            }}
            pinnedRef={pinnedRef}
            onClearPin={() => setPinnedRef(null)}
          />
        </ErrorBoundary>
      )}
    </div>
  );
}
