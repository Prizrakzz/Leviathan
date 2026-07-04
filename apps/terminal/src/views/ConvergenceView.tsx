import { Mark } from '@/tokens/Mark';

/** Convergence heatmap landing (design §4.8) — Phase 2 placeholder. Phase 3 renders the 31-contract ×
 *  regime grid from GET /v1/convergence, colored by proximity-to-firing. */
export function ConvergenceView() {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <Mark size={40} className="text-text-faint" />
      <div className="mt-4 font-mono text-11 uppercase tracking-wider text-text-dim">
        where convexity is building
      </div>
      <p className="mt-2 max-w-md font-sans text-14 text-text-dim">
        The 31-contract convergence heatmap renders here in Phase 3 (from{' '}
        <span className="font-mono text-cyan">/v1/convergence</span>). Cold-start landing.
      </p>
    </div>
  );
}
