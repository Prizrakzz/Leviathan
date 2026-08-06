import { Mark } from '@/tokens/Mark';
import { AsOfMachine } from './AsOfMachine';
import { CommandBar } from './CommandBar';
import { NotificationBell } from './NotificationBell';
import { TemplateLibrary } from './TemplateLibrary';
import { UserMenu } from './UserMenu';

/** The fixed top bar (design §3.1): mark · command bar · as-of time machine · templates · notifications ·
 *  user menu.
 *  D-TW-14b: the ⌘K button is gone with the palette it opened — the palette had zero commands, and a
 *  flagship-looking dead control is worse than absence. Phase 3 rebuilds it (affordance included).
 *  D-UX-1 adds the template library here — the ONE place that is on screen in every app state, which is the
 *  requirement that moved the gallery off the empty-state landing page. */
export function TopBar({
  cmd,
  setCmd,
  onSubmit,
  streaming,
}: {
  cmd: string;
  setCmd: (v: string) => void;
  onSubmit: (v: string) => void;
  /** D-TW-5(c): a streaming turn locks the command bar, exactly as it locks the composer. */
  streaming: boolean;
}) {
  return (
    <header className="flex items-center gap-4 border-b border-line bg-bg-0 px-4 py-2">
      <div className="flex items-center gap-2">
        <Mark size={20} className="text-amber" />
        <span className="font-mono text-13 font-semibold tracking-wide text-text">LEVIATHAN</span>
      </div>
      <div className="flex-1">
        <CommandBar value={cmd} onChange={setCmd} onSubmit={onSubmit} disabled={streaming} />
      </div>
      <AsOfMachine />
      <TemplateLibrary />
      <NotificationBell setCmd={setCmd} />
      <UserMenu />
    </header>
  );
}
