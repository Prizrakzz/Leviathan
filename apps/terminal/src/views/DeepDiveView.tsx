import { useUI } from '@/store/ui';

/** Commodity deep-dive (design §3.2) — Phase 2 placeholder. Phase 3 renders the full causal DAG, all
 *  regime gauges, the numbers history, and evidence coverage for the active contract. */
export function DeepDiveView() {
  const contract = useUI((s) => s.contract);
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <div className="font-mono text-11 uppercase tracking-wider text-text-dim">deep-dive</div>
      <div className="mt-2 font-mono text-18 text-amber">{contract ?? 'no contract selected'}</div>
      <p className="mt-2 max-w-md font-sans text-14 text-text-dim">
        Full causal DAG, regime gauges, numbers history, and evidence coverage render here in Phase 3.
      </p>
    </div>
  );
}
