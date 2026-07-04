/**
 * Stub auth gate (Phase 2). Real Cognito lives at the deploy step (Phase 4, backend `GRAPHRAG_AUTH`); until
 * then the terminal is reachable so the shell can be built + smoke-tested. When Cognito lands, this becomes a
 * real session check and the `/app` route stays gated behind it.
 */
export function isAuthed(): boolean {
  return true;
}
