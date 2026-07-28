/**
 * An INERT citation handle — what a `[3]` / `[N4]` marker looks like in the PRE-VERIFIER streaming draft.
 *
 * The streamed draft arrives before the citation verifier runs, and the verifier STRIPS unbacked handles
 * (StripCount p50 1, p90 7, max 16). Rendering those handles as live chips while streaming would show the
 * user clickable receipts that then change — richer streaming would make the inconsistency MORE visible,
 * not less. So the handle is visible (the analyst can watch the note cite as it writes) but deliberately
 * NOT interactive: no button, no tab stop, no tooltip, no resolved source. It becomes a real
 * `CitationChip` only once `verified`/`result` lands — so nothing a user could click ever disappears.
 */
export function InertCite({ refId }: { refId: string }) {
  return (
    <span
      data-testid="cite-inert"
      data-ref={refId}
      title="citation pending verification"
      aria-label={`citation ${refId}, pending verification`}
      className="mx-0.5 cursor-default rounded-chip border border-line px-1 align-baseline font-mono text-11 text-text-faint"
    >
      [{refId}]
    </span>
  );
}
