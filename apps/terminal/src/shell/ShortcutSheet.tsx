import { OVERLAY_SCRIM } from '@/tokens/tokens';

const KEYS: [string, string][] = [
  ['‹ / ›  ( , . )', 'nudge as-of (Shift = larger)'],
  ['1–4', 'focus panels'],
  ['g a / g c / g d', 'switch view (answer / convergence / deep-dive)'],
  ['⌘K', 'command palette'],
  ['⌘↵', 'submit'],
  ['⌘\\', 'toggle thread'],
  ['y', 'copy note as markdown'],
  ['e', 'open receipts'],
  ['?', 'this sheet'],
];

/** The shortcut sheet (design §3.3, `?`). */
export function ShortcutSheet({ onClose }: { onClose: () => void }) {
  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center ${OVERLAY_SCRIM}`}
      onClick={onClose}
      data-testid="shortcuts"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[460px] rounded-panel border border-line bg-bg-1 p-4"
      >
        <div className="mb-3 font-mono text-11 uppercase tracking-wider text-text-dim">keyboard</div>
        <dl className="grid grid-cols-[160px_1fr] gap-y-1.5">
          {KEYS.map(([k, d]) => (
            <div key={k} className="contents">
              <dt className="font-mono text-12 text-amber">{k}</dt>
              <dd className="font-sans text-12 text-text-dim">{d}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
