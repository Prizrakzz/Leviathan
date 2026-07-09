import * as Tooltip from '@radix-ui/react-tooltip';
import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { getGraph, getThreadTurns, suggest } from '@/api/client';
import type { components } from '@/api/types.gen';
import type { TurnState } from '@/api/useTurn';
import { retryImport } from '@/lib/retryImport';
import { Composer } from '@/shell/Composer';
import { ErrorBoundary } from '@/shell/ErrorBoundary';
import { Pipeline } from '@/shell/Pipeline';
import { useAutoScroll } from '@/shell/useAutoScroll';
import { useSession } from '@/store/session';
import { useThread } from '@/store/thread';
import { useUI } from '@/store/ui';
import { EmptyState } from './answer/EmptyState';
import { SuggestionChips } from './answer/SuggestionChips';
import { Banners } from './note/Banners';
import { resolvedFor } from './note/citations';
import { FormattedNote, renderInline } from './note/inlineFormat';
import { IntegrityStrip } from './note/IntegrityStrip';
import { Note } from './note/Note';
import { StreamingNote } from './note/StreamingNote';
import { useTypewriter } from './note/useTypewriter';
import { Numbers } from './numbers/Numbers';
import { ReceiptsDrawer } from './receipts/ReceiptsDrawer';

type TurnRecord = components['schemas']['TurnRecord'];

// 6.3: the interactive causal map is lazy — @xyflow/react + dagre + its CSS ride an async chunk off the
// first-paint critical path (the map only mounts on a finalized answer). retryImport heals a transient
// chunk miss (e.g. the just-deployed window); a hard failure surfaces to the map's ErrorBoundary (S2.1).
const CascadeFlow = lazy(() => retryImport(() => import('./dag/CascadeFlow')));

const noop = () => {};

// A caught render error inside a finalized answer degrades to a readable line instead of blanking the app.
const answerErrorFallback = (
  <div className="rounded-panel border border-line bg-bg-1 p-3 font-mono text-12 text-neg">
    couldn’t render this answer ·{' '}
    <button onClick={() => window.location.reload()} className="text-cyan hover:text-amber">
      reload
    </button>
  </div>
);
// A failed map chunk keeps the note intact. resetKeys can re-render a render-time throw, but React.lazy
// caches a REJECTED import forever — so for a genuinely missing chunk the honest escape is a reload (S2.1 review).
const mapErrorFallback = (
  <div className="rounded-panel border border-line bg-bg-1 p-3 font-mono text-11 text-text-faint">
    causal map unavailable ·{' '}
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
 *  + citation locator snippet); click is a noop on past turns (the receipts drawer is a live-turn surface). */
export function PastTurn({ t }: { t: TurnRecord }) {
  const s = (t.structured ?? null) as { tldr?: string; mechanism?: string } | null;
  const tldr = s?.tldr ?? '';
  const mechanism = s?.mechanism ?? '';
  const legacy = !tldr && !mechanism ? (t.answer ?? '') : '';
  const resolved = resolvedFor(t as Parameters<typeof resolvedFor>[0]);
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
            {renderInline(tldr, resolved, noop)}
          </p>
        )}
        {mechanism && (
          <div className="mt-1 font-sans text-13 leading-relaxed text-text-dim">
            <FormattedNote text={mechanism} resolved={resolved} onOpen={noop} />
          </div>
        )}
        {legacy && (
          <div className="mt-1 font-sans text-13 leading-relaxed text-text-dim">
            <FormattedNote text={legacy} resolved={resolved} onOpen={noop} />
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
}: {
  turn: TurnState;
  question: string;
  onAsk: (q: string) => void;
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

  const contract = r?.contract ?? r?.contracts?.[0] ?? null;
  const asof = r?.asof ?? '';
  // 6.3 cross-commodity swap: clicking a tracked hop shows that contract's map; reset on a new answer.
  const [mapContract, setMapContract] = useState<string | null>(null);
  useEffect(() => setMapContract(null), [contract]);
  const shownContract = mapContract ?? contract;
  const graphQ = useQuery({
    queryKey: ['graph', shownContract, asof],
    queryFn: () => getGraph(shownContract as string, asof),
    // W1.2-FE: numeric turns mount the map too (contract resolved backend-side, structured stays null).
    // NOT bare !!shownContract — a floor turn keeps its contract with structured=null and would mount a
    // map under the Service-notice banner; this gate targets exactly the two map-eligible states.
    enabled: !!shownContract && (!!r?.structured || r?.intent === 'numbers_only'),
    staleTime: 300_000,
  });

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

  const scrollRef = useRef<HTMLDivElement>(null);
  useAutoScroll(
    scrollRef,
    `${shown.length}:${turn.stages.length}:${past.length}:${turn.status}:${suggestQ.data?.suggestions.length ?? 0}`,
  );

  // Brand-new thread, nothing asked yet → the hero landing.
  if (turn.status === 'idle' && !question && past.length === 0 && !turnsQ.isLoading)
    return <EmptyState onAsk={onAsk} />;

  const finalReady = turn.status === 'done' && settled && !!r;
  const trace = (r?.trace ?? {}) as { fired_regimes?: { matched?: string[] }[]; drivers?: string[] };

  // The causal map, computed once and shared by BOTH finalReady branches (W1.1/W1.2-FE):
  // fetch error → a readable "unavailable" line (never a silent vanish — the old code kept the error
  // boundary INSIDE the data guard, so a dead /v1/graph meant no map and no message on every causal turn);
  // data → the lazy interactive DAG (its own boundary; a failed chunk keeps the answer intact); else null.
  // graphQ.enabled guarantees data only exists for structured OR numbers_only turns, so rendering it in
  // the non-structured branch stays null for floor/refused/no-match.
  const mapSlot = graphQ.isError ? (
    mapErrorFallback
  ) : graphQ.data ? (
    <ErrorBoundary fallback={mapErrorFallback} resetKeys={[shownContract]}>
      <Suspense
        fallback={<div className="h-[300px] animate-pulse rounded-panel border border-line bg-bg-1" />}
      >
        {mapContract && (
          <button
            onClick={() => setMapContract(null)}
            className="mb-1 font-mono text-11 text-text-faint hover:text-cyan"
          >
            ← back to {(contract ?? '').replace(/_/g, ' ')}
          </button>
        )}
        <CascadeFlow
          topo={graphQ.data}
          firedRegimes={mapContract ? undefined : trace.fired_regimes}
          drivers={mapContract ? undefined : trace.drivers}
          onNodeClick={() => openReceipts()}
          onSwap={(id) => setMapContract(id)}
        />
      </Suspense>
    </ErrorBoundary>
  ) : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-auto p-4" data-testid="conversation">
        {past.map((t, i) => (
          <ErrorBoundary key={t.ts ?? i} fallback={pastTurnErrorFallback} resetKeys={[t.ts ?? i]}>
            <PastTurn t={t} />
          </ErrorBoundary>
        ))}

        {showLive && (
          <div className="space-y-3">
            <div className="font-mono text-12 text-cyan">▸ {question}</div>

            {turn.status === 'streaming' && (
              <>
                <div className="rounded-panel border border-line bg-bg-1 p-3">
                  <Pipeline stages={turn.stages} done={false} />
                </div>
                {shown ? <StreamingNote draft={shown} /> : null}
              </>
            )}

            {turn.status === 'error' && (
              <div className="font-mono text-12 text-neg">error: {turn.error}</div>
            )}

            {turn.status === 'done' && !settled && (
              <>
                <div className="rounded-panel border border-line bg-bg-1 p-3">
                  <Pipeline stages={turn.stages} done={true} />
                </div>
                {shown ? <StreamingNote draft={shown} /> : null}
              </>
            )}

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
            <SuggestionChips items={suggestQ.data?.suggestions ?? []} onAsk={onAsk} />
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
