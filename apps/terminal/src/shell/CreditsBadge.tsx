import { useCredits } from '@/api/useCredits';
import { utcDay } from '@/lib/time';

/**
 * D-MW-25 — the credits balance, beside the depth control.
 *
 * It renders the SERVER'S OWN count or nothing at all. There is no "100 of 100" placeholder while the read
 * is in flight and none when metering is dark: a balance a client invented is exactly the lie a balance
 * exists to prevent (the dossier badge's rule, kept).
 */

/**
 * THE CHARGE TRADE, STATED IN PRODUCT COPY (D-MW-24 requires it to be user-visible somewhere in the credits
 * surface, and this is that place). The turn route is a GET SSE stream with no delivery signal: a client
 * that disconnects mid-turn is invisible to the server, the worker finishes the work and persists the turn
 * either way. So the charge commits when the answer is produced, and a disconnect after that point is still
 * charged. Saying so is the whole difference between a recorded trade and a surprise on someone's balance.
 */
export const CHARGE_NOTE =
  'a credit is spent when the answer is produced — if you close the tab after that, it still counts';

export function CreditsBadge() {
  const { balance, exhausted } = useCredits();
  if (!balance) return null; // dark, in flight, or an unreadable balance -- never a guessed one
  const day = utcDay(balance.reset_at);
  return (
    <span
      data-testid="credits-badge"
      title={`${CHARGE_NOTE}${day ? ` · the grant resets ${day} (UTC)` : ''}`}
      className={`rounded-chip border px-1 font-mono text-11 ${
        exhausted ? 'border-neg text-neg' : 'border-line text-text-faint'
      }`}
    >
      {balance.remaining} of {balance.limit} this month
    </span>
  );
}
