import { Link } from 'react-router-dom';
import { Mark } from '@/tokens/Mark';

/** The landing gate (design §8) — one page, not a marketing site. Near-black canvas, the convex mark, one
 *  line, a one-sentence descriptor, and two actions. Token-driven, so it shares the terminal's skin. */
export function Landing() {
  return (
    <div className="flex h-screen flex-col items-center justify-center bg-bg-0 px-6 text-center text-text">
      <Mark size={48} className="text-amber" />
      <h1 className="mt-6 font-sans text-32 font-semibold">Convexity, grounded.</h1>
      <p className="mt-3 max-w-md font-sans text-14 text-text-dim">
        A point-in-time research terminal for fundamental convexity in agricultural commodities.
      </p>
      <div className="mt-8 flex gap-3 font-mono text-13">
        <a
          href="mailto:access@leviathanconvexity.com"
          className="rounded-chip border border-line px-4 py-2 text-text-dim hover:border-cyan hover:text-cyan"
        >
          Request access
        </a>
        <Link
          to="/app"
          className="rounded-chip border border-amber px-4 py-2 text-amber hover:bg-bg-1"
        >
          Sign in
        </Link>
      </div>
    </div>
  );
}
