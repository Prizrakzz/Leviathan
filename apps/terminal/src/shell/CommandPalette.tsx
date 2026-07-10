import { Command } from 'cmdk';
import { OVERLAY_SCRIM } from '@/tokens/tokens';

/** ⌘K palette (design §3.3): fuzzy over commands/contracts/metrics/as-of presets. After the 5.6 view-prune
 *  Answer is the only view, so the palette drops the view/deep-dive entries; the full fuzzy universe binds to
 *  backend data in Phase 3. */
export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div
      className={`fixed inset-0 z-50 flex items-start justify-center pt-32 ${OVERLAY_SCRIM}`}
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
            placeholder="ask a question, or a code…"
            className="w-full border-b border-line bg-transparent px-3 py-2.5 font-mono text-14 text-text outline-none placeholder:text-text-faint"
          />
          <Command.List className="max-h-80 overflow-auto p-1">
            <Command.Empty className="px-3 py-2 font-sans text-12 text-text-faint">no matches</Command.Empty>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
