import { useQuery } from '@tanstack/react-query';
import { useRef } from 'react';
import { getGraph, getThreadTurns, suggest } from '@/api/client';
import type { components } from '@/api/types.gen';
import type { TurnState } from '@/api/useTurn';
import { Composer } from '@/shell/Composer';
import { Pipeline } from '@/shell/Pipeline';
import { useAutoScroll } from '@/shell/useAutoScroll';
import { useSession } from '@/store/session';
import { useThread } from '@/store/thread';
import { useUI } from '@/store/ui';
import { EmptyState } from './answer/EmptyState';
import { SuggestionChips } from './answer/SuggestionChips';
import { CascadeDAG } from './dag/CascadeDAG';
import { Banners } from './note/Banners';
import { FormattedNote, renderInline } from './note/inlineFormat';
import { IntegrityStrip } from './note/IntegrityStrip';
import { Note } from './note/Note';
import { StreamingNote } from './note/StreamingNote';
import { useTypewriter } from './note/useTypewriter';
import { Numbers } from './numbers/Numbers';
import { ReceiptsDrawer } from './receipts/ReceiptsDrawer';

type TurnRecord = components['schemas']['TurnRecord'];

const NO_CHIPS = {}; // past turns have no persisted resolved-citation map -> render [n] as plain text
const noop = () => {};
// INTEGRITY strip is an eval/log signal, not user-facing (6.1); show it only in debug (localStorage lv-debug=1).
const SHOW_INTEGRITY = typeof localStorage !== 'undefined' && localStorage.getItem('lv-debug') === '1';

/** One past (durable) turn of the active thread — full answer, ChatGPT-style (5.6 decision). Renders from
 *  the persisted `structured` (backend-sanitized in 6.1, so clean prose — no raw markup or internal ids),
 *  falling back to the legacy `answer` body only when a pre-6.1 turn has no structured fields. Citations
 *  render as plain text on past turns (the resolved map is trace-only, not persisted). */
function PastTurn({ t }: { t: TurnRecord }) {
  const s = (t.structured ?? null) as { tldr?: string; mechanism?: string } | null;
  const tldr = s?.tldr ?? '';
  const mechanism = s?.mechanism ?? '';
  const legacy = !tldr && !mechanism ? (t.answer ?? '') : '';
  return (
    <div className="border-b border-line pb-4" data-testid="past-turn">
      <div className="font-mono text-12 text-cyan">▸ {t.question}</div>
      {tldr && (
        <p className="mt-2 font-sans text-14 font-semibold leading-snug text-text">
          {renderInline(tldr, NO_CHIPS, noop)}
        </p>
      )}
      {mechanism && (
        <div className="mt-1 font-sans text-13 leading-relaxed text-text-dim">
          <FormattedNote text={mechanism} resolved={NO_CHIPS} onOpen={noop} />
        </div>
      )}
      {legacy && (
        <div className="mt-1 font-sans text-13 leading-relaxed text-text-dim">
          <FormattedNote text={legacy} resolved={NO_CHIPS} onOpen={noop} />
        </div>
      )}
      {t.asof && <div className="mt-1 font-mono text-11 text-text-faint">as of {t.asof}</div>}
    </div>
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
  const graphQ = useQuery({
    queryKey: ['graph', contract, asof],
    queryFn: () => getGraph(contract as string, asof),
    enabled: !!contract && !!r?.structured,
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-auto p-4" data-testid="conversation">
        {past.map((t, i) => (
          <PastTurn key={t.ts ?? i} t={t} />
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
              <div className="space-y-4">
                <Banners result={r} />
                {r.structured ? (
                  <>
                    <Note result={r} onOpenReceipts={() => setReceipts(true)} />
                    {graphQ.data ? (
                      <CascadeDAG
                        topo={graphQ.data}
                        firedRegimes={trace.fired_regimes}
                        drivers={trace.drivers}
                        onNodeClick={() => setReceipts(true)}
                      />
                    ) : r.structured.diagram_mermaid ? (
                      <pre className="overflow-auto rounded-panel border border-line bg-bg-1 p-2 font-mono text-11 text-text-dim">
                        {r.structured.diagram_mermaid}
                      </pre>
                    ) : null}
                    <Numbers calls={r.number_calls ?? []} asof={asof} />
                    {SHOW_INTEGRITY && <IntegrityStrip result={r} />}
                  </>
                ) : (
                  (r.evidence?.length ?? 0) > 0 && (
                    <button
                      className="rounded-chip border border-line px-2 py-1 font-mono text-11 text-cyan hover:bg-bg-1"
                      onClick={() => setReceipts(true)}
                    >
                      open receipts (e)
                    </button>
                  )
                )}
              </div>
            )}
          </div>
        )}

        {turn.status !== 'streaming' && (
          <SuggestionChips items={suggestQ.data?.suggestions ?? []} onAsk={onAsk} />
        )}
      </div>

      <Composer onSubmit={onAsk} streaming={turn.status === 'streaming'} autoFocus={false} />

      {r && <ReceiptsDrawer result={r} open={receiptsOpen} onClose={() => setReceipts(false)} />}
    </div>
  );
}
