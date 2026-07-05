import { useCallback, useRef, useState } from 'react';
import { respondStream } from './client';
import type { RespondResult, StageEvent } from './schema';

export type TurnStatus = 'idle' | 'streaming' | 'done' | 'error';

/** A pipeline milestone stamped with its client arrival time (drives the per-phase elapsed display). */
export type StampedStage = StageEvent & { ts: number };

export interface TurnState {
  status: TurnStatus;
  stages: StampedStage[];
  draft: string; // accumulating synthesis deltas (the note streaming in before the verified result lands)
  result?: RespondResult;
  error?: string;
}

/**
 * Drive one streamed turn. Accumulates the granular `stage` ticks (the staged-pipeline UI reads them) and
 * the terminal `result` (the note). Starting a new turn aborts the previous stream (design §7 SSE lifecycle).
 */
export function useTurn() {
  const [state, setState] = useState<TurnState>({ status: 'idle', stages: [], draft: '' });
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback((question: string, opts?: { asof?: string; sessionId?: string }) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setState({ status: 'streaming', stages: [], draft: '' });
    respondStream(
      { question, ...opts },
      {
        // `token` stages are synthesis deltas → grow the draft; every other stage is a pipeline milestone
        // (stamped with arrival time for the elapsed-per-phase display).
        onStage: (e) =>
          setState((s) =>
            e.stage === 'token'
              ? { ...s, draft: s.draft + (e.text ?? '') }
              : { ...s, stages: [...s.stages, { ...e, ts: performance.now() }] },
          ),
        onResult: (r) => setState((s) => ({ ...s, status: 'done', result: r })),
        onError: (er) => setState((s) => ({ ...s, status: 'error', error: er.error })),
      },
      ac.signal,
    ).catch((e: unknown) => setState((s) => ({ ...s, status: 'error', error: String(e) })));
  }, []);

  return { ...state, start };
}
