import { useState } from 'react';
import { useDossier } from '@/api/useDossier';
import { useTurn } from '@/api/useTurn';
import { parseCommand } from '@/command/parser';
import { useHotkeys } from '@/hotkeys/useHotkeys';
import { useAsOf } from '@/store/asof';
import { toContext } from '@/store/chips';
import { ASK_MODE, isDossierChoice, useMode } from '@/store/mode';
import { useThread } from '@/store/thread';
import { useUI } from '@/store/ui';
import { noteToMarkdown } from '@/views/note/markdown';
import { useUrlSync } from './useUrlSync';
import { DossierProgress } from './DossierProgress';
import { ErrorBoundary } from './ErrorBoundary';
import { ShortcutSheet } from './ShortcutSheet';
import { ThreadSidebar } from './ThreadSidebar';
import { TopBar } from './TopBar';
import { Workspace } from './Workspace';
import Onboarding from '@/views/onboarding/Onboarding';
import SettingsModal from '@/views/settings/SettingsModal';

/** The terminal shell (design §3.1): the fixed top bar, the thread sidebar, the view container (answer =
 *  conversation column + composer), and the full hotkey system. Owns the active turn. */
export function Shell() {
  const turn = useTurn();
  const dossier = useDossier();
  const threadCollapsed = useUI((s) => s.threadCollapsed);
  const asofStep = useAsOf((s) => s.step);
  const [cmd, setCmd] = useState('');
  const [question, setQuestion] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  useUrlSync();

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
    if (isDossierChoice(useMode.getState().choice)) {
      void dossier.submit(q, { asof: p.asofOverride ?? useAsOf.getState().asof });
      return;
    }

    setQuestion(q);
    // Thread the turn: session_id = the current thread id. The BACKEND registers the thread index +
    // auto-titles it on the first saved turn (5.6 W2) — no client-side putThread race anymore.
    const thread = useThread.getState();
    if (!thread.title) thread.setTitleIfEmpty(q);
    // P2: attached context chips ride the turn, then CLEAR — the turn consumed them (leaving them would
    // silently re-attach to the next unrelated question).
    const chips = ui.attachedChips;
    // D-AM-14 / D-DR-3: every ask now runs at the `quick` preset -- the picker's **Standard** entry IS that
    // preset relabelled, and it is the only ask entry left. `ASK_MODE` is the single constant that states
    // the label->wire mapping (store/mode), so this call site carries no literal and no rule: the raw name
    // goes down, and the transport drops it only for `standard`, which no UI path can reach any more.
    turn.start(q, {
      asof: p.asofOverride ?? useAsOf.getState().asof,
      sessionId: thread.threadId,
      context: chips.length ? toContext(chips) : undefined,
      mode: ASK_MODE,
    });
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
