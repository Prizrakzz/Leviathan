import { useCallback, useRef, useState } from 'react';
import { respondStream } from './client';
import type { CreditsRefusal } from './errors';
import { EMPTY_FINDINGS, finalizeFindings, parsePartial, reduceFindings, type Findings } from './partials';
import type { ContextAttachment, RespondResult, StageEvent } from './schema';

export type TurnStatus = 'idle' | 'streaming' | 'done' | 'error';

/** A pipeline milestone stamped with its client arrival time (drives the per-phase elapsed display). */
export type StampedStage = StageEvent & { ts: number };

/** The live turn: transport state (status/draft/result) + the RAW milestone feed the Pipeline reads +
 *  the STRUCTURED findings the F7 feed reads (see api/partials.ts). Findings default to empty, so a
 *  server that emits no partials leaves every one of them at its zero value and the UI is unchanged. */
export interface TurnState extends Findings {
  status: TurnStatus;
  stages: StampedStage[];
  draft: string; // accumulating synthesis deltas (the note streaming in before the verified result lands)
  result?: RespondResult;
  error?: string;
  /** D-MW-25: set ONLY when the turn was refused for credits. `error` still carries the sentence, so a
   *  reader that does not know about credits renders the refusal exactly as it renders any other failure;
   *  this field is what lets Shell add the reset day, hand the question back and re-read the balance. */
  refusal?: CreditsRefusal;
  /** The last terminal failure as a FRESH OBJECT per failure. Two things ride on the identity rather than
   *  the value (P5 review F6): an effect keyed on it fires exactly once per failure even when two turns
   *  fail identically, and `status` lets Shell hand the question back on ANY ask-route 429 — the busy-lease
   *  refusal carries no credits shape, and losing the user's sentence on a retryable refusal is a loss. */
  failure?: TurnFailure;
}

export interface TurnFailure {
  message: string;
  /** HTTP status when the turn failed before the stream opened; absent for in-stream/network failures. */
  status?: number;
  credits?: CreditsRefusal;
}

/** A clean turn. A FACTORY, not a shared constant: every array is fresh, so no two turns can ever alias
 *  the same `stages`/`regimes`/… array (the reducers are pure, but a shared empty array is a footgun). */
const fresh = (status: TurnStatus): TurnState => ({
  status,
  stages: [],
  draft: '',
  ...EMPTY_FINDINGS,
  regimes: [],
  numbers: [],
  chains: [],
  evidence: [],
});

/** A blank turn — exported so tests and stories can build one without restating every findings field
 *  (and so adding a field here can never silently leave a caller with an unsound cast). */
export const emptyTurn = (status: TurnStatus = 'idle'): TurnState => fresh(status);

/**
 * Drive one streamed turn. Accumulates THREE things off the same SSE `stage` transport:
 *   - `token` deltas               -> the synthesis draft (unchanged)
 *   - every other milestone tick   -> `stages[]`, stamped with arrival time (unchanged — the Pipeline reads it)
 *   - F7 content-bearing partials  -> structured findings (plan/walk/regimes/numbers/chains/evidence/phase)
 * Partials ALSO stay in `stages[]`: the split is additive, so nothing reading the raw feed breaks and an
 * unknown kind from a newer backend is simply ignored by both consumers. Starting a new turn aborts the
 * previous stream (design §7 SSE lifecycle).
 */
export function useTurn() {
  const [state, setState] = useState<TurnState>(() => fresh('idle'));
  const abortRef = useRef<AbortController | null>(null);

  // `mode` (D-AM-14) rides `opts` untouched: this hook shapes no request, it forwards one. The
  // omit-when-standard rule is the transport's (api/sse.ts via store/mode.modeParam), so there is exactly
  // one place where "standard means send nothing" is decided.
  const start = useCallback((question: string, opts?: { asof?: string; sessionId?: string; context?: ContextAttachment[]; mode?: string; turnId?: string }) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setState(fresh('streaming'));
    respondStream(
      { question, ...opts },
      {
        onStage: (e) =>
          setState((s) => {
            // `token` stages are synthesis deltas → grow the draft; every other stage is a pipeline
            // milestone (stamped with arrival time for the elapsed-per-phase display).
            if (e.stage === 'token') return { ...s, draft: s.draft + (e.text ?? '') };
            const stages = [...s.stages, { ...e, ts: performance.now() }];
            const p = parsePartial(e); // null = milestone tick, or an unknown kind from a newer server
            return p ? { ...reduceFindings(s, p), stages } : { ...s, stages };
          }),
        // The turn is over: the answer is verified, so citation handles may go live (invariant: this must
        // happen on `result` too, not only on a `verified` stage an older server never sends).
        onResult: (r) => setState((s) => ({ ...finalizeFindings(s), status: 'done', result: r })),
        onError: (er) =>
          setState((s) => ({
            ...s,
            status: 'error',
            error: er.error,
            refusal: er.credits,
            // A credits refusal IS a 429 by construction (errors.creditsRefusalFrom refuses to parse any
            // other status), so a transport that reported one without a status still reads as a 429 here.
            failure: { message: er.error, status: er.status ?? (er.credits ? 429 : undefined), credits: er.credits },
          })),
      },
      ac.signal,
    ).catch((e: unknown) => {
      // D-TW-5(d): this rejection may belong to a turn WE aborted when `start` ran again. An abort rejects the
      // in-flight stream asynchronously — after `start` has already installed the successor's fresh
      // state — so writing 'error' unconditionally marked the LIVE turn failed because its predecessor
      // was cancelled (the ⌘↵ double-submit made that a routine event). Only the controller that is
      // still the current one owns this state.
      if (abortRef.current !== ac) return;
      // `e.message` (not String(e)): with D-TW-6 that message IS the server's sentence, and the view
      // renders it verbatim — "Error: " in front of it is noise.
      const message = e instanceof Error ? e.message : String(e);
      setState((s) => ({ ...s, status: 'error', error: message, failure: { message } }));
    });
  }, []);

  return { ...state, start };
}
