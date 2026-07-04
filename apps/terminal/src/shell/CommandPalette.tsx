import { Command } from 'cmdk';
import type { ViewName } from '@/store/ui';

/** ⌘K palette (design §3.3): fuzzy over commands/contracts/metrics/views/as-of presets. Phase 2 wires the
 *  view switches + a couple of contract entries; the full fuzzy universe binds to backend data in Phase 3. */
export function CommandPalette({
  open,
  onClose,
  onView,
  onRun,
}: {
  open: boolean;
  onClose: () => void;
  onView: (v: ViewName) => void;
  onRun: (code: string) => void;
}) {
  if (!open) return null;
  const item = 'cursor-pointer rounded-chip px-3 py-1.5 text-14 text-text-dim aria-selected:bg-bg-2 aria-selected:text-text';
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-bg-0/70 pt-32"
      onClick={onClose}
      data-testid="palette"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[560px] overflow-hidden rounded-panel border border-line bg-bg-1 shadow-lg"
      >
        <Command label="Command palette">
          <Command.Input
            autoFocus
            placeholder="commands, contracts, metrics, views…"
            className="w-full border-b border-line bg-transparent px-3 py-2.5 font-mono text-14 text-text outline-none placeholder:text-text-faint"
          />
          <Command.List className="max-h-80 overflow-auto p-1">
            <Command.Empty className="px-3 py-2 font-sans text-12 text-text-faint">no matches</Command.Empty>
            <Command.Group heading="views" className="px-1 py-1 font-mono text-11 uppercase tracking-wider text-text-faint">
              <Command.Item className={item} onSelect={() => (onView('convergence'), onClose())}>
                Convergence heatmap
              </Command.Item>
              <Command.Item className={item} onSelect={() => (onView('answer'), onClose())}>
                Answer view
              </Command.Item>
            </Command.Group>
            <Command.Group heading="contracts" className="px-1 py-1 font-mono text-11 uppercase tracking-wider text-text-faint">
              <Command.Item className={item} onSelect={() => (onRun('C deep'), onClose())}>
                Corn — deep-dive
              </Command.Item>
              <Command.Item className={item} onSelect={() => (onRun('KC deep'), onClose())}>
                Arabica coffee — deep-dive
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
