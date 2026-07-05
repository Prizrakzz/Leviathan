import type { RespondResult } from '@/api/schema';
import { computeIntegrity } from './integrity';

/** The answer-integrity strip (design §4.6): the system's rigor legible in one line. */
export function IntegrityStrip({ result }: { result: RespondResult }) {
  const g = computeIntegrity(result);
  return (
    <div className="mt-4 border-t border-line pt-2 font-mono text-11 text-text-dim" data-testid="integrity">
      <span className="tracking-wider text-text-faint">INTEGRITY</span>&nbsp;&nbsp;
      <span className="text-pos">as-of✓</span> · citations <span className="text-pos">{g.verified}✓</span>{' '}
      <span className={g.stripped ? 'text-neg' : ''}>{g.stripped}✗</span> · numbers {g.lookedUp}/{g.requested}
      {g.notYetPub ? ` (${g.notYetPub} not-yet-pub)` : ''} · served-by <span className="text-text">{g.model}</span>
      {g.degraded ? <span className="text-amber"> [degraded ▸ {g.degraded}]</span> : null}
      {g.floor ? <span className="text-cyan"> [floor ▸ evidence-only]</span> : null} · graph{' '}
      <span className="text-amber">{g.graphVersion}</span>
    </div>
  );
}
