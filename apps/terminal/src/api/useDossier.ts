import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useRef, useState } from 'react';
import { useCompose } from '@/store/compose';
import {
  applyDossierState,
  type DossierJob,
  isTerminal,
  newDossierJob,
  reduceDossierEvent,
} from '@/store/dossier';
import { useUI } from '@/store/ui';
import {
  createDossier,
  DOSSIER_QUOTA_KEY,
  DossierQuotaError,
  getDossier,
  openDossierStream,
} from './dossier';
import type { ArtifactItem } from './schema';

/** What the user is told when a submit could not become a job. `quota` is not an error state -- it is a
 *  product answer with a date on it -- so it gets its own kind and its own colour. */
export interface DossierToast {
  kind: 'quota' | 'error';
  text: string;
  /** ISO instant the weekly allowance resets (quota only). */
  resetAt?: string;
}

export interface DossierApi {
  job: DossierJob | null;
  toast: DossierToast | null;
  /** Submit a question as a dossier. Resolves when the job is ACCEPTED or refused -- not when it finishes. */
  submit: (question: string, opts?: { asof?: string }) => Promise<void>;
  dismissToast: () => void;
  /** Clear a finished job's progress card (it has already landed as an artifact tab). */
  dismiss: () => void;
}

/**
 * D-DR-3 — drive one dossier job, the way `useTurn` drives one turn.
 *
 * A dossier is a JOB, not a turn, and three consequences follow, all of them deliberate:
 *
 *  - The composer is NOT locked while it runs. A turn owns the conversation for 30-90s; a dossier owns a
 *    worker for up to 20 minutes, and freezing the ask bar for that long would make the feature a trap.
 *    A SECOND dossier while one is live is refused with a sentence rather than silently clobbering the
 *    first job's state -- one live job, one progress card.
 *  - The result is never a chat bubble. The terminal event carries an artifact_id; this hook refetches the
 *    artifacts list FIRST and only then opens the tab, so the tab never flashes its
 *    "no longer saved" state against a list that predates the freeze by half a second.
 *  - A refusal hands the words back. The composer clears optimistically on Enter (the send is async), so a
 *    429 restores the exact question through the D-UX-1 compose seam and says when the allowance resets.
 */
export function useDossier(): DossierApi {
  const qc = useQueryClient();
  const [job, setJob] = useState<DossierJob | null>(null);
  const [toast, setToast] = useState<DossierToast | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Read INSIDE the async flow rather than from `job`: the closure would otherwise hold the job as it was
  // when `submit` was created, and the guard would let a second dossier through mid-stream.
  const liveRef = useRef(false);

  const land = useCallback(
    async (artifactId: string, question: string) => {
      // Refetch before opening: ArtifactTab is locator-only and reads the SHARED ['artifacts'] list, so a
      // stale list means the freshly frozen dossier renders as "this artifact is no longer saved".
      try {
        await qc.refetchQueries({ queryKey: ['artifacts'] });
      } catch {
        // The tab carries its own error + retry state; a failed refetch must not swallow the landing.
      }
      const list = qc.getQueryData<{ items: ArtifactItem[] }>(['artifacts']);
      const name = list?.items.find((a) => a.id === artifactId)?.name;
      useUI.getState().openTab({
        kind: 'artifact',
        title: name || question.slice(0, 60) || 'dossier',
        params: { artifactId },
      });
    },
    [qc],
  );

  const submit = useCallback(
    async (question: string, opts?: { asof?: string }) => {
      const q = question.trim();
      if (!q) return;
      if (liveRef.current) {
        setToast({ kind: 'error', text: 'a dossier is already running -- it will open as a tab when it lands' });
        return;
      }
      setToast(null);
      let accepted: { dossier_id: string };
      try {
        liveRef.current = true;
        accepted = await createDossier(q, opts?.asof);
      } catch (e: unknown) {
        liveRef.current = false;
        // The allowance moved either way (a 429 proves it is 0); re-read it so the badge stops promising
        // a run the server just refused.
        void qc.invalidateQueries({ queryKey: DOSSIER_QUOTA_KEY });
        useCompose.getState().restore(q); // non-destructive: the words come back
        if (e instanceof DossierQuotaError)
          setToast({ kind: 'quota', text: e.message, resetAt: e.resetAt });
        else setToast({ kind: 'error', text: e instanceof Error ? e.message : String(e) });
        return;
      }

      void qc.invalidateQueries({ queryKey: DOSSIER_QUOTA_KEY }); // one run spent
      const started = newDossierJob(accepted.dossier_id, q);
      setJob(started);

      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;

      let current = started;
      let landed: string | undefined;
      await openDossierStream(
        accepted.dossier_id,
        {
          onEvent: (e) => {
            current = reduceDossierEvent(current, e);
            setJob(current);
            if (isTerminal(current) && current.artifactId) landed = current.artifactId;
          },
          onDrop: (reason) => {
            // The stream died; the JOB may not have. Ask the server what actually happened before telling
            // the user anything -- a dropped socket is not a failed dossier (D-DR-1 honest-partial).
            current = { ...current, error: reason };
          },
        },
        ac.signal,
      );

      if (!isTerminal(current)) {
        try {
          current = applyDossierState(current, await getDossier(accepted.dossier_id));
        } catch {
          current = { ...current, status: 'failed', error: current.error ?? 'lost contact with the dossier job' };
        }
        setJob(current);
        if (isTerminal(current) && current.artifactId) landed = current.artifactId;
      }

      liveRef.current = false;
      if (landed) await land(landed, q);
    },
    [land, qc],
  );

  return {
    job,
    toast,
    submit,
    dismissToast: useCallback(() => setToast(null), []),
    dismiss: useCallback(() => setJob(null), []),
  };
}
