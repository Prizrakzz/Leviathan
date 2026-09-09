import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { getShare } from '@/api/client';
import { FrozenTurn } from './FrozenTurn';

/**
 * D-AM-15 — the public share reader at /s/:id. POST /v1/share has been minting these links since 1.7 and
 * nothing has ever served the page they point at; this is that page.
 *
 * PUBLIC on purpose (ratified): GET /v1/share/{id} carries no auth dependency, so this route must NOT sit
 * behind the terminal's auth gate and must NOT gate its fetch on `useSession.ready` — the whole point is a
 * forwarded link that opens for someone who has never signed in. It is also strictly read-only: no composer,
 * no receipts drawer, no ask affordance, just the frozen turn and a way into the product.
 */
export default function SharePage() {
  const { id = '' } = useParams();
  const q = useQuery({
    queryKey: ['share', id],
    queryFn: () => getShare(id),
    enabled: !!id,
    staleTime: Infinity, // a share snapshot is immutable by construction — refetching can only cost, never gain
    retry: false,
  });

  return (
    <div className="min-h-screen bg-bg-0 text-text">
      <header className="flex items-center justify-between border-b border-line px-4 py-2">
        <div className="font-mono text-11 uppercase tracking-wider text-text-dim">
          leviathan · shared research note
        </div>
        <Link to="/" className="font-mono text-11 text-cyan hover:text-amber">
          open the terminal ↗
        </Link>
      </header>

      <main className="p-4" data-testid="share-page">
        {q.isError && (
          <div className="font-mono text-12 text-text-faint" data-testid="share-missing">
            this link has expired or never existed
          </div>
        )}
        {!q.isError && !q.data && <div className="h-40 animate-pulse rounded-panel bg-bg-1" />}
        {/* D-UX-5: `liveSeries={false}`. GET /v1/share is public; GET /v1/series is NOT (`_require_identity`),
            so a signed-out reader's numbers panel and chart cards would resolve to 401 and this page would
            grow a row of "couldn't load this chart · retry" on every forwarded link. The frozen prose,
            the pins and the sources are the whole of what a public reader can be shown honestly. */}
        {q.data && <FrozenTurn snapshot={q.data} liveSeries={false} />}
      </main>
    </div>
  );
}
