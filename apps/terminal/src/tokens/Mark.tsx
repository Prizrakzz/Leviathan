/** The convex-curve monogram (design §2.3): flat → kink → convex steepening (an option payoff; an `L`
 *  reads in the flat-then-rising stroke). Amber, single-stroke, favicon-safe. Also the motif every regime
 *  gauge reuses (§4.4). Stroke uses `currentColor` so callers set it via a token utility (`text-amber`). */
export function Mark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      role="img"
      aria-label="Leviathan"
      className={className}
    >
      <path
        d="M3 17 H11 C15 17 17 12 21 4"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
