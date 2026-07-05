import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAsOf } from '@/store/asof';
import { useUI, type ViewName } from '@/store/ui';

const VIEWS: ViewName[] = ['answer', 'convergence', 'deep'];

/** URL-state sync (design §7): `{view, contract, asof}` <-> the query string, so any screen is shareable /
 *  bookmarkable. Reads once on mount, then mirrors store changes into the URL (replace, no history spam). */
export function useUrlSync() {
  const [params, setParams] = useSearchParams();
  const view = useUI((s) => s.view);
  const contract = useUI((s) => s.contract);
  const asof = useAsOf((s) => s.asof);

  useEffect(() => {
    const v = params.get('view');
    if (v && (VIEWS as string[]).includes(v)) useUI.getState().setView(v as ViewName);
    const c = params.get('contract');
    if (c) useUI.getState().setContract(c);
    const a = params.get('asof');
    if (a) useAsOf.getState().setAsOf(a);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const next = new URLSearchParams(params);
    next.set('view', view);
    if (contract) next.set('contract', contract);
    else next.delete('contract');
    next.set('asof', asof);
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, contract, asof]);
}
