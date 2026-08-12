import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { CREDITS_KEY } from '@/api/credits';
import { useDossier } from '@/api/useDossier';
import { useTurn } from '@/api/useTurn';
import { parseCommand } from '@/command/parser';
import { useHotkeys } from '@/hotkeys/useHotkeys';
import { useAsOf } from '@/store/asof';
import { toContext } from '@/store/chips';
import { useCompose } from '@/store/compose';
import { askModeFor, isDossierChoice, useMode } from '@/store/mode';
import { useThread } from '@/store/thread';
import { useUI } from '@/store/ui';
import { noteToMarkdown } from '@/views/note/markdown';
import { useUrlSync } from './useUrlSync';
import { CreditsToast } from './CreditsToast';
import { DossierProgress } from './DossierProgress';
import { ErrorBoundary } from './ErrorBoundary';
import { ShortcutSheet } from './ShortcutSheet';
import { ThreadSidebar } from './ThreadSidebar';
import { TopBar } from './TopBar';
import { Workspace } from './Workspace';
import Onboarding from '@/views/onboarding/Onboarding';
import SettingsModal from '@/views/settings/SettingsModal';

/** A fresh per-question turn id (P5 review F4). `crypto.randomUUID` where it exists — which is everywhere
 *  this app runs, since it requires a secure context and so does Cognito — with a plain random fallback so a
 *  test environment or an http:// dev host can never make a submit throw. */
function newTurnId(): string {
  const c: Crypto | undefined = globalThis.crypto;
  return c?.randomUUID ? c.randomUUID() : `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** The terminal shell (design §3.1): the fixed top bar, the thread sidebar, the view container (answer =
 *  conversation column + composer), and the full hotkey system. Owns the active turn. */
export function Shell() {
  const turn = useTurn();
  const dossier = useDossier();
  const qc = useQueryClient();
  const threadCollapsed = useUI((s) => s.threadCollapsed);
  const asofStep = useAsOf((s) => s.step);
  const [cmd, setCmd] = useState('');
  const [question, setQuestion] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  // The exact words of the last ASK, kept in a ref: a credits refusal has to hand them back to the composer
  // (which cleared optimistically on Enter), and by then `turn` is an error state that no longer carries them.
  const askedRef = useRef('');
  const [refusalDismissed, setRefusalDismissed] = useState<unknown>(null);
  useUrlSync();

  // D-MW-25 — a turn REFUSED at the ask route (HTTP 429). Two things happen exactly once per refusal, and
  // the failure object's identity is what makes "once" true (a new failure is a new object; a re-render is
  // not): the question goes back in the box, and the balance is re-read, because a 429 proves it moved.
  //
  // P5 review F6: this is keyed on the STATUS, not on the credits shape. The busy-lease refusal ("a metered
  // turn is already running on this account") is deliberately NOT the credits shape — different copy, no
  // reset day — but it is just as retryable, and the composer cleared optimistically on Enter. Restoring
  // only on the credits shape meant that user watched their sentence disappear. Only the COPY differs
  // between the two refusals: the toast below still renders for the credits one alone.
  const refusal = turn.refusal;
  const failure = turn.failure;
  useEffect(() => {
    if (failure?.status !== 429) return;
    useCompose.getState().restore(askedRef.current);
    void qc.invalidateQueries({ queryKey: CREDITS_KEY });
  }, [failure, qc]);

  // Every terminal turn also re-reads the balance: the charge commits when the result is enqueued, so the
  // number on screen is only true after the turn ends.
  const turnStatus = turn.status;
  useEffect(() => {
    if (turnStatus === 'done' || turnStatus === 'error') void qc.invalidateQueries({ queryKey: CREDITS_KEY });
  }, [turnStatus, qc]);

  const submit = (input: string) => {
    // D-TW-5(c): ONE chokepoint for every submit path (command bar, ⌘↵, composer, suggestion chips).
    // A submit mid-turn aborts the live stream and starts a different question — with no stop button
    // (deliberate) and a disabled composer, the user never asked for that. The command bar is disabled
    // while streaming too; this catches the keyboard route into the same function.
    if (turn.status === 'streaming') return;
    setCmd('');
    const p = parseCommand(input);
    const ui = useUI.getState();
    const q = p.kind === 'numbers' ? `${p.contract} ${p.metric}` : p.question;

    // D-DR-3: Deep Research is NOT an ask mode -- it is a different ROUTE. The branch sits here, at the one
    // submit chokepoint, and BEFORE anything turn-shaped happens: a dossier does not set `question`, does
    // not title the thread, does not consume the context chips (POST /v1/dossier takes {question, asof}),
    // and never touches the transcript. Its one as-of is stamped at submission and governs every sub-query
    // (D-DR-1, PIT by construction), so it reads the same as-of a turn would and sends it in the body.
    const choice = useMode.getState().choice;
    if (isDossierChoice(choice)) {
      void dossier.submit(q, { asof: p.asofOverride ?? useAsOf.getState().asof });
      return;
    }

    askedRef.current = q;
    // P5 review F4: ONE turn id per QUESTION. It is minted here, at the submit chokepoint, and rides every
    // attempt at that question (the SSE reconnect/retry path reuses the same `turn.start` opts), so the
    // server's credit charge is idempotent across requests instead of billing a retry as a second turn.
    // A new question is a new id — idempotency must never collapse two real turns into one.
    const turnId = newTurnId();
    setQuestion(q);
    // Thread the turn: session_id = the current thread id. The BACKEND registers the thread index +
    // auto-titles it on the first saved turn (5.6 W2) — no client-side putThread race anymore.
    const thread = useThread.getState();
    if (!thread.title) thread.setTitleIfEmpty(q);
    // P2: attached context chips ride the turn, then CLEAR — the turn consumed them (leaving them would
    // silently re-attach to the next unrelated question).
    const chips = ui.attachedChips;
    // D-MW-21: the ask runs at THE SELECTED NOTCH's preset. `askModeFor` (store/mode) is the single place
    // the label->wire mapping lives, so this call site carries no literal and no rule -- Scan sends
    // `mode=quick` and Analysis sends `mode=deep`, both EXPLICITLY. The omit-when-default idiom is retired
    // on this route by the R7-ratified 2-notch ship: no notch maps to `standard` any more, and `standard`
    // survives only as the backend's fail-open for a mode-less (no-request/API) caller.
    turn.start(q, {
      asof: p.asofOverride ?? useAsOf.getState().asof,
      sessionId: thread.threadId,
      context: chips.length ? toContext(chips) : undefined,
      mode: askModeFor(choice),
      turnId,
    });
    // A metered submit moves the balance at the gate, before a single byte streams: re-read it now so the
    // badge is not a turn behind, and again when the turn ends (the effect above).
    void qc.invalidateQueries({ queryKey: CREDITS_KEY });
    if (chips.length) ui.clearChips();
  };

  /** Plain-question submit for the composer/empty-state (no command parsing — it's a chat box). */
  const ask = (q: string) => submit(q);

  useHotkeys({
    onSubmit: () => {
      const v = cmd.trim();
      if (v) submit(v);
    },
    onToggleThread: () => useUI.getState().toggleThread(),
    onEscape: () => {
      useUI.getState().setReceipts(false);
      setHelpOpen(false);
    },
    onAsOfStep: (dir, large) => asofStep(dir, large),
    onReceipts: () => useUI.getState().toggleReceipts(),
    onCopy: () => {
      if (turn.result) void navigator.clipboard?.writeText(noteToMarkdown(turn.result));
    },
    onHelp: () => setHelpOpen(true),
  });

  return (
    <div className="flex h-screen flex-col bg-bg-0 text-text">
      <TopBar cmd={cmd} setCmd={setCmd} onSubmit={submit} streaming={turn.status === 'streaming'} />
      {/* D-DR-3: the dossier JOB surface -- above the workspace, never inside the conversation column (the
          result lands as a frozen artifact tab, not as a bubble). Renders nothing at all with no job and no
          toast, so an estate with GRAPHRAG_DOSSIER dark is byte-identical to today. Wrapped: a fault in a
          progress card must not blank the terminal (the S2.x lesson). */}
      <ErrorBoundary fallback={null}>
        {/* D-MW-25: the credits wall, in the same strip and for the same reason -- it is a product answer
            about a job that did not start, not a line in the transcript. Dismissal is tracked by the
            refusal's IDENTITY, so dismissing one wall does not suppress the next one. */}
        {refusal && refusal !== refusalDismissed && (
          <div className="shrink-0 border-b border-line bg-bg-0 px-4 pt-2">
            <CreditsToast refusal={refusal} onDismiss={() => setRefusalDismissed(refusal)} />
          </div>
        )}
        <DossierProgress
          job={dossier.job}
          toast={dossier.toast}
          onDismiss={dossier.dismiss}
          onDismissToast={dossier.dismissToast}
        />
      </ErrorBoundary>
      <div className="flex flex-1 overflow-hidden">
        {threadCollapsed ? (
          // W1.6: collapsed → a slim expand rail, never NOTHING (the old branch rendered no affordance;
          // only the hotkey could bring the sidebar back).
          <button
            onClick={() => useUI.getState().toggleThread()}
            aria-label="expand threads"
            title="expand threads (Ctrl+\)"
            className="flex w-8 shrink-0 flex-col items-center gap-2 border-r border-line bg-bg-0 pt-2 font-mono text-11 text-text-dim hover:bg-bg-2 hover:text-cyan"
          >
            <span>›</span>
            <span className="uppercase tracking-wider [writing-mode:vertical-rl]">threads</span>
          </button>
        ) : (
          <ThreadSidebar turn={turn} />
        )}
        {/* P9-E1a: watch chips prefill the top command bar through the SAME setCmd the bell uses. */}
        <Workspace turn={turn} question={question} onAsk={ask} onPrefill={setCmd} />
      </div>
      {helpOpen && <ShortcutSheet onClose={() => setHelpOpen(false)} />}
      {/* Settings + onboarding (6.6) — always mounted, self-gated on open/profile state. Wrapped so a
          fault in either can never blank the terminal (S2.x lesson). */}
      <ErrorBoundary fallback={null}>
        <SettingsModal />
      </ErrorBoundary>
      <ErrorBoundary fallback={null}>
        <Onboarding />
      </ErrorBoundary>
    </div>
  );
}
