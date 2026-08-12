import type { CreditsRefusal } from '@/api/errors';
import { utcDay } from '@/lib/time';

/**
 * D-MW-25 — the credits wall, said out loud.
 *
 * The DossierProgress toast's shape, for the same reason it has that shape: a quota refusal is not an error,
 * it is a product answer with a DATE on it, so it gets its own colour and it always says when the grant
 * comes back. A monthly refusal without a date is the least actionable thing we could put on screen.
 *
 * Non-destructive: it reports, it does not take the question away. Shell hands the exact words back to the
 * composer on the same path that raises this (store/compose.restore), and the last line says so — a user
 * who has just been refused should not have to guess whether their sentence survived.
 */
export function CreditsToast({
  refusal,
  onDismiss,
}: {
  refusal: CreditsRefusal;
  onDismiss: () => void;
}) {
  const day = utcDay(refusal.resetAt);
  return (
    <div
      role="status"
      data-testid="credits-toast"
      className="mb-2 flex items-start gap-2 rounded-panel border border-amber px-2 py-1.5 font-mono text-11 text-amber"
    >
      <span className="min-w-0 flex-1">
        {refusal.message}
        {day && <span data-testid="credits-toast-reset"> — the grant resets {day} (UTC)</span>}
        <span className="block text-text-faint">
          your question is still in the box; Scan is always free
        </span>
      </span>
      <button
        aria-label="dismiss"
        onClick={onDismiss}
        className="shrink-0 rounded-chip border border-line px-1 text-text-dim hover:text-cyan"
      >
        ×
      </button>
    </div>
  );
}
