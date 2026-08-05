import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAsOf } from '@/store/asof';

/** URL-state sync (design §7): `asof` <-> the query string, so any screen is shareable / bookmarkable.
 *  Reads once on mount, then mirrors store changes into the URL (replace, no history spam).
 *  D-TW-15: `view` left both directions. It had been a single-member enum since the 5.6 view-prune, so the
 *  write effect stamped `?view=answer` onto every URL to say nothing, and the read effect guarded against
 *  values that no longer exist. A stale bookmarked `?view=…`/`?contract=…` is now simply carried and
 *  ignored — nothing reads it, and rewriting a shared link's params is not this hook's business. */
export function useUrlSync() {
  const [params, setParams] = useSearchParams();
  const asof = useAsOf((s) => s.asof);

  useEffect(() => {
    const a = params.get('asof');
    if (a) useAsOf.getState().setAsOf(a);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const next = new URLSearchParams(params);
    next.set('asof', asof);
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asof]);
}
