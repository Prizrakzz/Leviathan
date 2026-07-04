import type { RespondResult, StageEvent } from './schema';

export interface StreamHandlers {
  onStage?: (e: StageEvent) => void;
  onResult?: (r: RespondResult) => void;
  onError?: (err: { error: string }) => void;
}

/**
 * Parse an SSE byte stream (design §7). Blocks are separated by a blank line; each has an `event:` and one
 * or more `data:` lines; a line starting with `:` is a keepalive comment (ignored — the backend sends
 * `: keepalive` across the 30–90s turn). Resolves on the terminal `result`/`error`, or when the stream ends.
 */
export async function parseSSE(stream: ReadableStream<Uint8Array>, h: StreamHandlers): Promise<void> {
  const reader = stream.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (dispatchBlock(block, h)) return; // terminal event
    }
  }
  if (buf.trim()) dispatchBlock(buf, h);
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
  params: { question: string; asof?: string; sessionId?: string },
  h: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const qs = new URLSearchParams({ question: params.question });
  if (params.asof) qs.set('asof', params.asof);
  if (params.sessionId) qs.set('session_id', params.sessionId);
  const res = await fetch(`${base}/v1/respond/stream?${qs.toString()}`, {
    headers: { Accept: 'text/event-stream' },
    signal,
  });
  if (!res.ok || !res.body) {
    h.onError?.({ error: `HTTP ${res.status}` });
    return;
  }
  await parseSSE(res.body, h);
}
