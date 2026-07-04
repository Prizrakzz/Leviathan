import { useState } from 'react';
import { useTurn } from '@/api/useTurn';
import { parseCommand } from '@/command/parser';
import { useHotkeys } from '@/hotkeys/useHotkeys';
import { useAsOf } from '@/store/asof';
import { useUI, type ViewName } from '@/store/ui';
import { CommandPalette } from './CommandPalette';
import { ShortcutSheet } from './ShortcutSheet';
import { ThreadPane } from './ThreadPane';
import { TopBar } from './TopBar';
import { ViewContainer } from './ViewContainer';

/** The terminal shell (design §3.1): the fixed top bar, the thread pane, the view container, the command
 *  palette, and the full hotkey system. Owns the active turn (mock-driven in Phase 2). */
export function Shell() {
  const turn = useTurn();
  const paletteOpen = useUI((s) => s.paletteOpen);
  const threadCollapsed = useUI((s) => s.threadCollapsed);
  const asofStep = useAsOf((s) => s.step);
  const [cmd, setCmd] = useState('');
  const [question, setQuestion] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);

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
    turn.start(q, { asof: p.asofOverride ?? useAsOf.getState().asof });
  };

  useHotkeys({
    onPalette: () => useUI.getState().setPalette(true),
    onSubmit: () => {
      const v = cmd.trim();
      if (v) submit(v);
    },
    onToggleThread: () => useUI.getState().toggleThread(),
    onEscape: () => {
      useUI.getState().setPalette(false);
      setHelpOpen(false);
    },
    onAsOfStep: (dir, large) => asofStep(dir, large),
    onView: (v: ViewName) => useUI.getState().setView(v),
    onPanel: (n) => useUI.getState().focusPanel(n),
    onHelp: () => setHelpOpen(true),
  });

  return (
    <div className="flex h-screen flex-col bg-bg-0 text-text">
      <TopBar cmd={cmd} setCmd={setCmd} onSubmit={submit} onPalette={() => useUI.getState().setPalette(true)} />
      <div className="flex flex-1 overflow-hidden">
        {!threadCollapsed && <ThreadPane turn={turn} question={question} />}
        <ViewContainer turn={turn} />
      </div>
      <CommandPalette
        open={paletteOpen}
        onClose={() => useUI.getState().setPalette(false)}
        onView={(v) => useUI.getState().setView(v)}
        onRun={submit}
      />
      {helpOpen && <ShortcutSheet onClose={() => setHelpOpen(false)} />}
    </div>
  );
}
