/**
 * The ONE place a non-OK HTTP response becomes a message a human can act on (D-TW-6).
 *
 * The API answers a refusal with its own sentence in FastAPI's `detail` -- "daily limit of 50 turns
 * reached, try again tomorrow" is the one users actually hit. Every caller used to throw a bare
 * `HTTP ${status}`, so that sentence never reached the screen and the quota wall read as `error: HTTP 429`.
 *
 * The body read is BEST EFFORT by design: on the failure path we must never turn a parse problem into a
 * second, worse failure. A non-JSON body is the realistic case, not a hypothetical -- when CloudFront has
 * no `/v1/*` behavior the SPA fallback answers every API call with index.html (the 2026-07-12 misdeploy).
 */

/** The message to SHOW. `where` (a route path) is appended to the STATUS fallback only: it is debugging
 *  context, never a substitute for the server's own words. */
export async function httpErrorMessage(res: Response, where?: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown } | null;
    const detail = body?.detail;
    // Only a plain string is a human sentence. FastAPI's 422 `detail` is an array of validation objects --
    // stringifying that would put "[object Object]" in front of a user, so it falls through to the status.
    if (typeof detail === 'string' && detail.trim()) return detail.trim();
  } catch {
    // no body / not JSON / already consumed -- the status line is all we have
  }
  return `HTTP ${res.status}${where ? ` on ${where}` : ''}`;
}

/** The same message as a thrown Error (the client.ts helpers' shape). */
export async function httpError(res: Response, where: string): Promise<Error> {
  return new Error(await httpErrorMessage(res, where));
}
