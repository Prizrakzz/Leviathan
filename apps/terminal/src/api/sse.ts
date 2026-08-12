import { fetchWithAuth } from '../auth/oidc';
import { type CreditsRefusal, readHttpError } from './errors';
import type { ContextAttachment, RespondResult, StageEvent } from './schema';
import { MAX_ATTACH } from '@/store/chips';
import { modeParam } from '@/store/mode';

/**
 * A turn that ended badly. `error` is the sentence to show and has always been the whole payload.
 *
 * D-MW-25 adds `credits`, present ONLY for the credits wall: the depth control needs the reset day and the
 * balance, and a string cannot carry them. It rides ALONGSIDE the sentence rather than replacing it, so
 * every existing reader (useTurn -> the answer view) keeps working unchanged and a client that ignores the
 * field degrades to exactly today's behaviour.
 */
export interface TurnError {
  error: string;
  credits?: CreditsRefusal;
  /** The HTTP status, when the turn failed BEFORE the stream opened. P5 review F6: the composer has to hand
   *  the question back on ANY ask-route 429 — the busy-lease refusal ("a metered turn is already running")
   *  is deliberately NOT the credits shape, so keying the restore on `credits` alone lost the user's typed
   *  sentence on a refusal that is, by construction, retryable. Absent for in-stream failures. */
  status?: number;
}

export interface StreamHandlers {
  onStage?: (e: StageEvent) => void;
  onResult?: (r: RespondResult) => void;
  onError?: (err: TurnError) => void;
}

/** No-bytes watchdog (D-TW-4). The backend emits `: keepalive` after every 10s of silence (server.py),
 *  so 90s without a single BYTE is ~9 missed keepalives: the connection is DEAD, not slow -- an ALB idle
 *  drop or an ECS task replaced mid-turn, with the reader politely waiting forever. The margin is
 *  deliberately generous; this is a last-resort unstick, not a latency SLO. */
export const SSE_IDLE_MS = 90_000;

/**
 * Parse an SSE byte stream (design §7). Blocks are separated by a blank line; each has an `event:` and one
 * or more `data:` lines; a line starting with `:` is a keepalive comment (ignored — the backend sends
 * `: keepalive` across the 30-90s turn). Resolves on the terminal `result`/`error`.
 *
 * D-TW-4: a stream that ends (or stalls) WITHOUT a terminal event is a failure, and is now reported as one.
 * Before this it resolved silently: useTurn stayed at status 'streaming' forever, the composer stayed
 * disabled, the pipeline sat at "—", and only a reload recovered — which lost the question. The idle
 * watchdog is what turns the second, quieter shape of that hang (bytes simply stop arriving) into the
 * same honest error.
 */
export async function parseSSE(
  stream: ReadableStream<Uint8Array>,
  h: StreamHandlers,
  idleMs: number = SSE_IDLE_MS,
): Promise<void> {
  const { terminated, stalled } = await readSSEBlocks(stream, (block) => dispatchBlock(block, h), idleMs);
  if (terminated) return;
  h.onError?.({
    error: stalled
      ? `stream stalled — nothing received for ${Math.round(idleMs / 1000)}s, retry`
      : 'stream ended without a result — retry',
  });
}

/**
 * The TRANSPORT half of parseSSE, split out for D-DR-3: read an SSE byte stream, hand each `\n\n`-delimited
 * block to `onBlock`, and stop the moment `onBlock` says the block was terminal.
 *
 * Split rather than duplicated because the dossier's event stream (api/dossier.ts) is a DIFFERENT protocol
 * on the same transport — its own event vocabulary (plan/subquery/synthesis/done/partial), its own terminal
 * rule, its own honest-partial semantics — but the same framing, the same keepalive comments, the same
 * multi-byte-split decoder flush and the same D-TW-4 watchdog. One place gets those four right.
 *
 * Returns WHY the read ended: `terminated` (onBlock claimed a block as terminal — the only clean end) and
 * `stalled` (the idle watchdog fired). Each protocol turns that pair into its own error sentence.
 */
export async function readSSEBlocks(
  stream: ReadableStream<Uint8Array>,
  onBlock: (block: string) => boolean,
  idleMs: number = SSE_IDLE_MS,
): Promise<{ terminated: boolean; stalled: boolean }> {
  const reader = stream.getReader();
  const dec = new TextDecoder();
  let buf = '';
  let stalled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  // Re-armed on every chunk. On fire we CANCEL the reader, which resolves the pending read as `done` --
  // so the stall exits through the same path as a real end-of-stream (no dangling read, no second code
  // path to keep correct) and the socket is released instead of leaking for the tab's lifetime.
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      stalled = true;
      void reader.cancel();
    }, idleMs);
  };
  try {
    arm();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      arm();
      buf += dec.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (onBlock(block)) return { terminated: true, stalled }; // the ONLY clean end of a stream
      }
    }
    // Flush the decoder: `stream: true` holds back a multi-byte character split across chunk boundaries,
    // and the final chunk's tail is only released by a decode() with no argument.
    buf += dec.decode();
    // A stalled stream's leftover is a HALF block by definition -- dispatching it would invent an event.
    if (!stalled && buf.trim() && onBlock(buf)) return { terminated: true, stalled };
  } finally {
    clearTimeout(timer);
  }
  return { terminated: false, stalled };
}

function dispatchBlock(block: string, h: StreamHandlers): boolean {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue; // blank or keepalive comment
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).trim());
  }
  if (!data.length) return false;
  let payload: unknown;
  try {
    payload = JSON.parse(data.join('\n'));
  } catch {
    return false;
  }
  if (event === 'stage') {
    h.onStage?.(payload as StageEvent);
    return false;
  }
  if (event === 'result') {
    h.onResult?.(payload as RespondResult);
    return true;
  }
  if (event === 'error') {
    h.onError?.(payload as { error: string });
    return true;
  }
  return false;
}

/** Open the real SSE endpoint and pump it through parseSSE. Mock mode routes elsewhere (client.ts). */
export async function openRespondStream(
  base: string,
  params: { question: string; asof?: string; sessionId?: string; context?: ContextAttachment[]; mode?: string; turnId?: string },
  h: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const qs = new URLSearchParams({ question: params.question });
  if (params.asof) qs.set('asof', params.asof);
  if (params.sessionId) qs.set('session_id', params.sessionId);
  // P5 review F4: the per-question TURN ID. It is what makes the credit charge idempotent across requests —
  // the gate derives its ledger op from `sub + turn_id`, so a reconnect or a retry of the SAME question is
  // one charge, not two. Minted once at submit (Shell) and reused for every attempt at that question; a
  // caller that sends none is charged per request (the lease is then its only protection).
  if (params.turnId) qs.set('turn_id', params.turnId);
  // P2: attachments ride a JSON-encoded param (the stream is GET-only); cap mirrors the store's MAX_ATTACH
  if (params.context?.length) qs.set('context', JSON.stringify(params.context.slice(0, MAX_ATTACH)));
  // D-AM-14: the reasoning mode, LAST and CONDITIONAL. `modeParam` is the one place the omit rule lives
  // (standard/absent/unknown -> undefined), so a standard turn's query string is byte-for-byte the one
  // this route sent before the wave -- which is the client half of the backend's passthrough pin.
  const mode = modeParam(params.mode);
  if (mode) qs.set('mode', mode);
  // fetch-based SSE (not EventSource) -> fetchWithAuth attaches the bearer AND does the shared
  // 401-retry-after-forced-refresh (D-W6.2); a still-401 replay falls through to onError below.
  const res = await fetchWithAuth(`${base}/v1/respond/stream?${qs.toString()}`, {
    headers: { Accept: 'text/event-stream' },
    signal,
  });
  if (!res.ok || !res.body) {
    if (res.ok) {
      h.onError?.({ error: 'stream did not open — retry' });
      return;
    }
    // D-TW-6: the server's own sentence (FastAPI `detail`) — the 50-turn daily cap is the one users hit,
    // and it used to render as `error: HTTP 429`. No route context appended: this string goes ON SCREEN.
    // D-MW-25: the SAME single read also yields the credits refusal when this is the credits wall (the
    // body can be consumed once, so the sentence and the structured fields must come out together).
    // This is the only place the wall can surface: the gate refuses BEFORE the StreamingResponse opens,
    // by construction, so a credits 429 is always a non-OK response and never an in-stream `error` event.
    const { message, credits } = await readHttpError(res);
    h.onError?.(credits
      ? { error: message, credits, status: res.status }
      : { error: message, status: res.status });
    return;
  }
  await parseSSE(res.body, h);
}
