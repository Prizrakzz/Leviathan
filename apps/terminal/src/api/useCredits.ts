import { useQuery } from '@tanstack/react-query';
import { useSession } from '@/store/session';
import { CREDITS_KEY, getCredits, type CreditsBalance } from './credits';

export interface CreditsView {
  /** The server's own count, or `null` when there is none to show (dark, still loading, or a failed read). */
  balance: CreditsBalance | null;
  /** Metering is OFF on this deployment (the route 404s). Every notch is selectable and free. */
  dark: boolean;
  /** The grant is spent. Only ever true against a REAL balance -- never inferred from a missing one. */
  exhausted: boolean;
  refetch: () => void;
}

/**
 * D-MW-25 — the credits balance as the UI needs it, in one hook so the badge and the depth control read the
 * SAME cache entry rather than two queries that can disagree on screen.
 *
 * `staleTime` 30s (the DOSSIER_QUOTA_KEY pattern): a balance is worth re-reading often enough that a page
 * left open does not promise a turn the server just refused, and rarely enough that typing a question does
 * not generate traffic. Every point where the number provably moved -- a submit, a turn ending, a 429 --
 * invalidates the key explicitly (Shell), so the 30s is a floor on staleness, not the mechanism.
 *
 * A FAILED read is deliberately NOT `dark`: dark means "the server told us there is no meter" (404), and it
 * unlocks the metered notch. A network failure tells us nothing, so the badge simply does not render and
 * the notch stays selectable -- the same fail-open posture the backend takes when the ledger is unreachable.
 */
export function useCredits(): CreditsView {
  const ready = useSession((s) => s.ready);
  const q = useQuery({
    queryKey: CREDITS_KEY,
    queryFn: getCredits,
    enabled: ready,
    staleTime: 30_000,
  });
  const balance = q.data ?? null;
  return {
    balance,
    dark: q.isSuccess && balance === null,
    exhausted: !!balance && balance.remaining <= 0,
    refetch: () => void q.refetch(),
  };
}
