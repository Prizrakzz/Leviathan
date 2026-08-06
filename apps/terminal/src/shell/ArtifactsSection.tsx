import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { deleteArtifact, listArtifacts } from '@/api/client';
import type { ArtifactItem } from '@/api/schema';
import { relTime } from '@/lib/time';
import { useSession } from '@/store/session';
import { useUI } from '@/store/ui';
import { DELETE_ARM_MS } from './ThreadSidebar';

/**
 * D-AM-15 — the saved-artifacts list, under the threads list in the same sidebar. An artifact is a NAMED
 * FREEZE of one answer (private, per-user), so this list is deliberately not a second thread list: rows
 * open a read-only workspace tab instead of loading a thread, and there is no rename (the name is chosen at
 * freeze time; re-editing it would imply the artifact itself is editable, which it is not).
 *
 * Delete keeps the ThreadRow two-click arm and its SHARED timeout constant — one armed-destructive idiom in
 * this sidebar, not two that drift (D-TW-8).
 */
export function ArtifactsSection() {
  const ready = useSession((s) => s.ready);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['artifacts'], queryFn: listArtifacts, enabled: ready, staleTime: 30_000 });
  const items = q.data?.items ?? [];

  const open = (a: ArtifactItem) => {
    useUI.getState().openTab({
      kind: 'artifact',
      title: a.name || 'artifact',
      params: { artifactId: a.id }, // locator only — the tab reads the payload from this same query
    });
  };

  return (
    <div className="shrink-0 border-t border-line" data-testid="artifacts-section">
      <div className="px-4 py-2 font-mono text-11 uppercase tracking-wider text-text-dim">artifacts</div>
      <div className="max-h-56 space-y-0.5 overflow-auto px-2 pb-2" data-testid="artifact-list">
        {items.map((a) => (
          <ArtifactRow
            key={a.id}
            item={a}
            onOpen={() => open(a)}
            onDeleted={() => void qc.invalidateQueries({ queryKey: ['artifacts'] })}
          />
        ))}
        {/* Same one-state-line rule as the thread list (D-TW-12): a failed fetch also has zero items, and
            "nothing saved" would be an assertion we cannot make. The error wins. */}
        {q.isError ? (
          <div className="px-2 py-1 font-mono text-11 text-neg">couldn't load artifacts — retrying</div>
        ) : (
          ready &&
          !q.isLoading &&
          items.length === 0 && (
            <div className="px-2 py-1 font-sans text-12 text-text-faint">
              no artifacts yet — save an answer to keep it.
            </div>
          )
        )}
      </div>
    </div>
  );
}

function ArtifactRow({
  item,
  onOpen,
  onDeleted,
}: {
  item: ArtifactItem;
  onOpen: () => void;
  onDeleted: () => void;
}) {
  const [armed, setArmed] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!armed) return;
    confirmRef.current?.focus();
    const t = setTimeout(() => setArmed(false), DELETE_ARM_MS);
    return () => clearTimeout(t);
  }, [armed]);

  const del = useMutation({
    mutationFn: () => deleteArtifact(item.id),
    onSettled: () => {
      setArmed(false);
      onDeleted();
    },
  });

  const gv = item.snapshot?.graph_version;
  return (
    <div
      className="group flex items-center gap-1 rounded-panel border border-transparent px-2 py-1.5 hover:bg-bg-1"
      data-testid="artifact-row"
    >
      <button onClick={onOpen} className="min-w-0 flex-1 text-left" title={item.name ?? item.id}>
        <div className="truncate font-sans text-12 text-text">{item.name || item.id}</div>
        <div className="truncate font-mono text-11 text-text-faint">
          {item.snapshot?.asof ? `as of ${item.snapshot.asof}` : relTime(item.updated_at)}
          {gv ? ` · ${gv}` : ''}
        </div>
      </button>
      {armed ? (
        <button
          ref={confirmRef}
          aria-label="confirm delete artifact"
          className="shrink-0 rounded-chip border border-neg px-1.5 font-mono text-11 text-neg"
          onClick={() => del.mutate()}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setArmed(false);
          }}
          onBlur={() => setArmed(false)}
        >
          sure?
        </button>
      ) : (
        <button
          aria-label="delete artifact"
          className="hidden shrink-0 rounded-chip border border-line px-1 font-mono text-11 text-text-dim hover:text-neg group-hover:block"
          onClick={() => setArmed(true)}
        >
          ×
        </button>
      )}
    </div>
  );
}
