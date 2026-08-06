import { useQuery } from '@tanstack/react-query';
import { listArtifacts } from '@/api/client';
import { useSession } from '@/store/session';
import type { ArtifactTabParams } from '@/store/tabs';
import { FrozenTurn } from '@/views/artifact/FrozenTurn';

/** D-AM-15: a saved artifact as a workspace tab. The query key is IDENTICAL to the sidebar's (['artifacts'])
 *  so opening one is a cache hit, never a second GET — and a delete from the sidebar invalidates both at
 *  once, which is what makes the "deleted" state below reachable instead of stale. */
export default function ArtifactTab({ params }: { params: ArtifactTabParams }) {
  const ready = useSession((s) => s.ready);
  const q = useQuery({ queryKey: ['artifacts'], queryFn: listArtifacts, enabled: ready, staleTime: 30_000 });
  const item = q.data?.items.find((a) => a.id === params.artifactId);

  if (q.isError)
    return (
      <div className="p-4 font-mono text-12 text-text-faint">
        couldn’t load your artifacts ·{' '}
        <button onClick={() => q.refetch()} className="text-cyan hover:text-amber">
          retry
        </button>
      </div>
    );
  if (!q.data) return <div className="h-full animate-pulse bg-bg-1" data-testid="artifact-tab-loading" />;
  // A rehydrated tab whose artifact was deleted (here or in another session) says so. The tab is
  // locator-only, so this is the ONLY place that truth can surface.
  if (!item)
    return (
      <div className="p-4 font-mono text-12 text-text-faint" data-testid="artifact-tab-missing">
        this artifact is no longer saved — close the tab
      </div>
    );

  return (
    <div className="h-full overflow-auto p-4" data-testid="artifact-tab">
      <div className="mb-3 font-mono text-11 uppercase tracking-wider text-text-dim">
        artifact · {item.name}
      </div>
      {item.snapshot ? (
        <FrozenTurn snapshot={item.snapshot} />
      ) : (
        <div className="font-mono text-12 text-text-faint">this artifact carries no frozen answer</div>
      )}
    </div>
  );
}
