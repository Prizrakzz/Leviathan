/**
 * The ONE place a non-OK HTTP response becomes a message a human can act on (D-TW-6), plus — since
 * D-MW-25 — the one place a CREDITS refusal becomes a structured fact the depth control can render.
 *
 * The API answers a refusal with its own sentence in FastAPI's `detail` -- "daily limit of 50 turns
 * reached, try again tomorrow" is the one users actually hit. Every caller used to throw a bare
 * `HTTP ${status}`, so that sentence never reached the screen and the quota wall read as `error: HTTP 429`.
 *
 * THE CREDITS 429 IS A DIFFERENT SHAPE, and that is deliberate on the server side: it is raised from the
 * quota dependency as `CreditsExceeded` and rendered by an app-level exception handler as a TOP-LEVEL body
 * `{error, limit, remaining, reset_at, detail}` -- the only construct that can both short-circuit before the
 * stream opens and put `reset_at` where a client can read it without digging through `detail`. The FE half
 * of that contract lives here: the same read produces BOTH the human sentence (from `detail`, exactly as
 * before) and the structured refusal (from the top-level fields). The daily-turn 429, which is an ordinary
 * HTTPException with only a string `detail`, therefore does NOT parse as a credits refusal -- the presence
 * of a top-level `reset_at` alongside a limit/remaining count is the discriminator.
 *
 * The body read is BEST EFFORT by design: on the failure path we must never turn a parse problem into a
 * second, worse failure. A non-JSON body is the realistic case, not a hypothetical -- when CloudFront has
 * no `/v1/*` behavior the SPA fallback answers every API call with index.html (the 2026-07-12 misdeploy).
 * A response body can also be read only ONCE, which is why `readHttpError` exists at all: a caller that
 * wants both the sentence and the refusal must not call two functions that each consume the body.
 */

/** A credits wall, parsed. `message` is always present (the server's sentence, or ours). */
export interface CreditsRefusal {
  /** The server's own `detail` sentence when it sent one, else a plain fallback. Goes on screen verbatim. */
  message: string;
  /** The machine-readable code the handler stamps in `error` — `credits_exceeded` for the monthly grant
   *  (server.py `_CREDITS_ERROR_CODE`). It is a SLUG, never prose: the human sentence is `detail`, which is
   *  what `message` carries. Nothing branches on it today; it exists so that something can, without having
   *  to string-match a sentence that is free to be reworded. */
  code?: string;
  /** The monthly grant and what is left of it -- absent rather than guessed if the body omitted them. */
  limit?: number;
  remaining?: number;
  /** ISO instant the grant resets. The whole reason this shape is top-level: a monthly refusal without a
   *  date is unactionable. */
  resetAt?: string;
}

const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined);
const str = (v: unknown): string | undefined =>
  typeof v === 'string' && v.trim() ? v.trim() : undefined;

/**
 * A credits refusal, or `null` for every other failure.
 *
 * Accepts the nested `detail: {...}` variant as well as the pinned top-level one. Not because the contract
 * is in doubt -- D-MW-24 pins the top-level body and the prod smoke asserts it -- but because the dossier's
 * own 429 taught this exact lesson once already (api/dossier.resetAtOf), and a client that goes blind the
 * day a handler is rewritten as an HTTPException is a worse outcome than four lines of tolerance.
 */
export function creditsRefusalFrom(status: number, body: unknown): CreditsRefusal | null {
  if (status !== 429 || !body || typeof body !== 'object') return null;
  const top = body as Record<string, unknown>;
  const nested = (typeof top.detail === 'object' && top.detail ? top.detail : {}) as Record<string, unknown>;
  const pick = (k: string): unknown => (top[k] !== undefined ? top[k] : nested[k]);

  const resetAt = str(pick('reset_at'));
  const limit = num(pick('limit'));
  const remaining = num(pick('remaining'));
  // A credits wall carries a reset instant AND a count. The daily-turn cap carries neither, so it keeps
  // rendering as the plain sentence it has always been.
  if (!resetAt || (limit === undefined && remaining === undefined)) return null;

  return {
    message: str(top.detail) ?? str(nested.detail) ?? 'no credits left this month',
    code: str(pick('error')),
    limit,
    remaining,
    resetAt,
  };
}

/**
 * Read a failed response ONCE and return both halves: the sentence to show, and the credits refusal if this
 * was one. `where` (a route path) is appended to the STATUS fallback only: it is debugging context, never a
 * substitute for the server's own words.
 */
export async function readHttpError(
  res: Response,
  where?: string,
): Promise<{ message: string; credits: CreditsRefusal | null }> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // no body / not JSON / already consumed -- the status line is all we have
  }
  const credits = creditsRefusalFrom(res.status, body);
  if (credits) return { message: credits.message, credits };
  // Only a plain string is a human sentence. FastAPI's 422 `detail` is an array of validation objects --
  // stringifying that would put "[object Object]" in front of a user, so it falls through to the status.
  const detail = str((body as { detail?: unknown } | null)?.detail);
  return { message: detail ?? `HTTP ${res.status}${where ? ` on ${where}` : ''}`, credits: null };
}

/** The message to SHOW. */
export async function httpErrorMessage(res: Response, where?: string): Promise<string> {
  return (await readHttpError(res, where)).message;
}

/** The same message as a thrown Error (the client.ts helpers' shape). */
export async function httpError(res: Response, where: string): Promise<Error> {
  return new Error(await httpErrorMessage(res, where));
}
