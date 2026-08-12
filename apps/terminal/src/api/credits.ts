import { fetchWithAuth } from '../auth/oidc';
import { httpErrorMessage } from './errors';

/**
 * D-MW-25 — the monthly CREDIT grant, read.
 *
 * The metered tier (Analysis) spends one credit a turn against a monthly grant. This is the generalisation
 * of the dossier allowance seam (api/dossier.getDossierQuota) and it keeps that seam's two properties,
 * because both were load-bearing:
 *
 *  - DARK IS NOT AN ERROR. `GRAPHRAG_CREDITS` absent means the route 404s and NOTHING is metered; the FE
 *    must render that as "no meter here" (no badge at all, every notch selectable), never as a broken
 *    feature. Only a 404 is treated that way -- a 500 still throws, because a server fault is not a
 *    product decision.
 *  - ITS OWN QUERY KEY, declared next to the fetcher, so the badge and every invalidation point (submit,
 *    turn end, a 429) can never drift onto two keys and show two different numbers.
 *
 * The dossier's 4/month allowance stays a SEPARATE meter with a separate badge (the user's directive): a
 * dossier does not spend credits and a credit does not buy a dossier.
 */

const BASE = import.meta.env.VITE_API_BASE ?? '';
const MOCK = import.meta.env.VITE_MOCK === '1';

/** GET /v1/credits. Route named here so the FE half of the contract is greppable from one place. */
export const CREDITS_ROUTE = '/v1/credits';

export const CREDITS_KEY = ['credits'] as const;

export interface CreditsBalance {
  remaining: number;
  limit: number;
  /** ISO instant the grant resets -- the first instant of the next UTC month. */
  reset_at?: string;
}

/** The balance, or `null` when metering is dark (404). See the header note. */
export async function getCredits(): Promise<CreditsBalance | null> {
  if (MOCK) return { remaining: 97, limit: 100, reset_at: mockResetAt() };
  const res = await fetchWithAuth(`${BASE}${CREDITS_ROUTE}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await httpErrorMessage(res, `GET ${CREDITS_ROUTE}`));
  return (await res.json()) as CreditsBalance;
}

/** The first instant of the NEXT UTC month (month+1 with day 1 normalises December -> January). */
function mockResetAt(): string {
  const d = new Date();
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)).toISOString();
}
