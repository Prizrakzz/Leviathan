import { Mark } from '@/tokens/Mark';
import { AsOfMachine } from './AsOfMachine';
import { CommandBar } from './CommandBar';
import { UserMenu } from './UserMenu';

/** The fixed top bar (design §3.1): mark · command bar · as-of time machine · ⌘K · user menu. */
export function TopBar({
  cmd,
  setCmd,
  onSubmit,
  onPalette,
}: {
  cmd: string;
  setCmd: (v: string) => void;
  onSubmit: (v: string) => void;
  onPalette: () => void;
}) {
  return (
    <header className="flex items-center gap-4 border-b border-line bg-bg-0 px-4 py-2">
      <div className="flex items-center gap-2">
        <Mark size={20} className="text-amber" />
        <span className="font-mono text-13 font-semibold tracking-wide text-text">LEVIATHAN</span>
      </div>
      <div className="flex-1">
        <CommandBar value={cmd} onChange={setCmd} onSubmit={onSubmit} />
      </div>
      <AsOfMachine />
      <button
        aria-label="open command palette"
        className="rounded-chip border border-line px-1.5 py-0.5 font-mono text-11 text-text-faint hover:border-cyan hover:text-cyan"
        onClick={onPalette}
      >
        ⌘K
      </button>
      <UserMenu />
    </header>
  );
}
