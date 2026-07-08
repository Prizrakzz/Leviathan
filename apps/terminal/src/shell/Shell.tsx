import { useQueryClient } from '@tanstack/react-query';
import { lazy, Suspense, useEffect, useState } from 'react';
import { getConvergence } from '@/api/client';
import { useTurn } from '@/api/useTurn';
import { parseCommand } from '@/command/parser';
import { useHotkeys } from '@/hotkeys/useHotkeys';
import { retryImport } from '@/lib/retryImport';
import { useAsOf } from '@/store/asof';
import { usePdf } from '@/store/pdf';
import { useSession } from '@/store/session';
import { useThread } from '@/store/thread';
import { useUI, type ViewName } from '@/store/ui';
import { noteToMarkdown } from '@/views/note/markdown';
import { useUrlSync } from './useUrlSync';
import { CommandPalette } from './CommandPalette';
import { ErrorBoundary } from './ErrorBoundary';
import { ShortcutSheet } from './ShortcutSheet';
import { ThreadSidebar } from './ThreadSidebar';
import { TopBar } from './TopBar';
import { ViewContainer } from './ViewContainer';
import Onboarding from '@/views/onboarding/Onboarding';
import SettingsModal from '@/views/settings/SettingsModal';

// 6.5: the PDF click-to-page modal pulls in pdf.js + its worker — lazy so that whole chunk stays off the
// first-paint critical path (mounted only once `open`, mirroring the CascadeFlow pattern). retryImport
// heals a transient chunk miss in the just-deployed window (S2.1).
const PdfModal = lazy(() => retryImport(() => import('@/views/pdf/PdfModal')));

/** The terminal shell (design §3.1): the fixed top bar, the thread sidebar, the view container (answer =
 *  conversation column + composer), the command palette, and the full hotkey system. Owns the active turn. */
export function Shell() {
  const turn = useTurn();
  const paletteOpen = useUI((s) => s.paletteOpen);
  const threadCollapsed = useUI((s) => s.threadCollapsed);
  const pdfOpen = usePdf((s) => s.open);
  const sessionReady = useSession((s) => s.ready);
  const asof = useAsOf((s) => s.asof);
  const asofStep = useAsOf((s) => s.step);
  const qc = useQueryClient();
  const [cmd, setCmd] = useState('');
  const [question, setQuestion] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  useUrlSync();

  // Warm the convergence heatmap in the background (5.6 W4): the server keeps a live-asof warm cache, so
  // this is a cheap fetch that makes the view instant when the user switches to it.
  useEffect(() => {
    if (!sessionReady) return;
    void qc.prefetchQuery({
      queryKey: ['convergence', asof],
      queryFn: () => getConvergence(asof),
      staleTime: 60_000,
    });
  }, [sessionReady, asof, qc]);

  const submit = (input: string) => {
    setCmd('');
    const p = parseCommand(input);
    const ui = useUI.getState();
    if (p.kind === 'view') return ui.setView(p.view);
    if (p.kind === 'deep') {
      ui.setContract(p.contract);
      return ui.setView('deep');
    }
    if (p.kind === 'compare') {
      ui.setContract(p.contracts[0] ?? null);
      return ui.setView('deep');
    }
    const q = p.kind === 'numbers' ? `${p.contract} ${p.metric}` : p.question;
    if ('contract' in p && p.contract) ui.setContract(p.contract);
    setQuestion(q);
    ui.setView('answer');
    // Thread the turn: session_id = the current thread id. The BACKEND registers the thread index +
    // auto-titles it on the first saved turn (5.6 W2) — no client-side putThread race anymore.
    const thread = useThread.getState();
    if (!thread.title) thread.setTitleIfEmpty(q);
    turn.start(q, { asof: p.asofOverride ?? useAsOf.getState().asof, sessionId: thread.threadId });
  };

  /** Plain-question submit for the composer/empty-state (no command parsing — it's a chat box). */
  const ask = (q: string) => submit(q);

  useHotkeys({
    onPalette: () => useUI.getState().setPalette(true),
    onSubmit: () => {
      const v = cmd.trim();
      if (v) submit(v);
    },
    onToggleThread: () => useUI.getState().toggleThread(),
    onEscape: () => {
      useUI.getState().setPalette(false);
      useUI.getState().setReceipts(false);
      setHelpOpen(false);
    },
    onAsOfStep: (dir, large) => asofStep(dir, large),
    onView: (v: ViewName) => useUI.getState().setView(v),
    onPanel: (n) => useUI.getState().focusPanel(n),
    onReceipts: () => useUI.getState().toggleReceipts(),
    onCopy: () => {
      if (turn.result) void navigator.clipboard?.writeText(noteToMarkdown(turn.result));
    },
    onHelp: () => setHelpOpen(true),
  });

  return (
    <div className="flex h-screen flex-col bg-bg-0 text-text">
      <TopBar cmd={cmd} setCmd={setCmd} onSubmit={submit} onPalette={() => useUI.getState().setPalette(true)} />
      <div className="flex flex-1 overflow-hidden">
        {!threadCollapsed && <ThreadSidebar turn={turn} />}
        <ViewContainer turn={turn} question={question} onAsk={ask} />
      </div>
      <CommandPalette
        open={paletteOpen}
        onClose={() => useUI.getState().setPalette(false)}
        onView={(v) => useUI.getState().setView(v)}
        onRun={submit}
      />
      {helpOpen && <ShortcutSheet onClose={() => setHelpOpen(false)} />}
      {/* Settings + onboarding (6.6) — always mounted, self-gated on open/profile state. Wrapped so a
          fault in either can never blank the terminal (S2.x lesson). */}
      <ErrorBoundary fallback={null}>
        <SettingsModal />
      </ErrorBoundary>
      <ErrorBoundary fallback={null}>
        <Onboarding />
      </ErrorBoundary>
      {/* 6.5: the PDF modal is mounted only while open so pdf.js rides its own lazy chunk. A fault in the
          viewer can never blank the terminal (S2.x lesson). */}
      {pdfOpen && (
        <ErrorBoundary fallback={null}>
          <Suspense fallback={null}>
            <PdfModal />
          </Suspense>
        </ErrorBoundary>
      )}
    </div>
  );
}
