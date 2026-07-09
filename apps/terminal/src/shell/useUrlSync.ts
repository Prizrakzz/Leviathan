import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAsOf } from '@/store/asof';
import { useUI, type ViewName } from '@/store/ui';

const VIEWS: ViewName[] = ['answer'];

/** URL-state sync (design §7): `{view, asof}` <-> the query string, so any screen is shareable / bookmarkable.
 *  Reads once on mount, then mirrors store changes into the URL (replace, no history spam). A stale bookmarked
 *  `?view=deep`/`?contract=…` is ignored by the `VIEWS.includes` guard, then the write effect self-heals the
 *  URL to `view=answer` (5.6 view-prune). */
export function useUrlSync() {
  const [params, setParams] = useSearchParams();
  const view = useUI((s) => s.view);
  const asof = useAsOf((s) => s.asof);

  useEffect(() => {
    const v = params.get('view');
    if (v && (VIEWS as string[]).includes(v)) useUI.getState().setView(v as ViewName);
    const a = params.get('asof');
    if (a) useAsOf.getState().setAsOf(a);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const next = new URLSearchParams(params);
    next.set('view', view);
    next.delete('contract'); // dropped in the 5.6 view-prune; strip any stale param
    next.set('asof', asof);
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, asof]);
}
