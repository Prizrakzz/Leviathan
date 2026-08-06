import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { createShare, saveArtifact } from '@/api/client';
import type { RespondResult } from '@/api/schema';

/** The name box seeds from the question, capped so a paragraph-long ask doesn't become the label. */
const NAME_MAX = 80;

/**
 * D-AM-15 — the two actions a finished answer has never had: KEEP it, and SEND it.
 *
 *  - save   -> POST /v1/artifacts. Private, per-user, and it stores the whole frozen payload, so the saved
 *              copy survives the graph moving under it. The name is prompted INLINE (the ThreadSidebar
 *              rename box idiom: Enter commits, Escape cancels, blur cancels) rather than in a modal —
 *              naming a note is a caption, not a dialog.
 *  - share  -> POST /v1/share (the EXISTING route, public by ratified design) and copy the returned
 *              /s/{id} link. The URL is also rendered as text: clipboard writes fail silently under
 *              permission policies and in non-secure contexts, and a "copied" toast over an empty clipboard
 *              is worse than no toast.
 *
 * Both freeze server-side. This component posts what the browser holds and shows what the server returns.
 */
export function TurnActions({ result, question }: { result: RespondResult; question: string }) {
  const qc = useQueryClient();
  const [naming, setNaming] = useState(false);
  const [savedName, setSavedName] = useState<string | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (naming) inputRef.current?.focus();
  }, [naming]);

  const save = useMutation({
    mutationFn: (name: string) => saveArtifact(name, question, result),
    onSuccess: (_r, name) => {
      setSavedName(name);
      void qc.invalidateQueries({ queryKey: ['artifacts'] });
    },
    onSettled: () => setNaming(false),
  });

  const share = useMutation({
    mutationFn: () => createShare(question, result),
    onSuccess: (ref) => {
      const url = `${window.location.origin}${ref.url}`;
      setShareUrl(url);
      void navigator.clipboard?.writeText(url);
    },
  });

  const btn =
    'rounded-chip border border-line px-2 py-1 font-mono text-11 text-text-dim hover:border-cyan hover:text-cyan disabled:opacity-50';

  if (naming)
    return (
      <div className="max-w-3xl" data-testid="turn-actions">
        <input
          ref={inputRef}
          defaultValue={question.slice(0, NAME_MAX)}
          aria-label="name this artifact"
          className="w-full rounded-chip border border-line bg-bg-0 px-1.5 py-0.5 font-sans text-12 text-text focus:border-cyan"
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              const v = e.currentTarget.value.trim();
              if (v) save.mutate(v);
              else setNaming(false);
            }
            if (e.key === 'Escape') setNaming(false);
          }}
          onBlur={() => setNaming(false)}
        />
      </div>
    );

  return (
    <div className="flex max-w-3xl flex-wrap items-center gap-2" data-testid="turn-actions">
      <button className={btn} onClick={() => setNaming(true)} disabled={save.isPending}>
        {save.isPending ? 'saving…' : 'save artifact'}
      </button>
      <button className={btn} onClick={() => share.mutate()} disabled={share.isPending}>
        {share.isPending ? 'minting…' : 'share link'}
      </button>
      {savedName && (
        <span className="font-mono text-11 text-text-faint" data-testid="artifact-saved">
          saved as “{savedName}”
        </span>
      )}
      {shareUrl && (
        <span className="truncate font-mono text-11 text-cyan" data-testid="share-url">
          {shareUrl}
        </span>
      )}
      {(save.isError || share.isError) && (
        <span className="font-mono text-11 text-neg">
          {(save.error as Error | null)?.message ?? (share.error as Error | null)?.message}
        </span>
      )}
    </div>
  );
}
