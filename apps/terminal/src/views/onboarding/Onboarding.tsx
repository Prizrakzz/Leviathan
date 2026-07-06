import * as Dialog from '@radix-ui/react-dialog';
import { useEffect, useState } from 'react';
import { useProfile, useUpdateProfile } from '@/api/useProfile';
import { COMMODITIES, SEATS } from '@/lib/commodities';
import { useSettings } from '@/store/settings';
import { ChipList, ToggleChip } from '@/views/settings/chips';

const STEPS = 3;

/**
 * First-run onboarding (6.6): three skippable questions that seed the user's `facts` (which personalize the
 * query suggester). Shows when the profile is loaded and NOT onboarded, or when "Redo onboarding" forces it.
 * Never blocks — every step is optional, Esc / overlay-click / "Skip all" all finish with whatever's captured
 * and set `onboarded=true`. Mounted inside the (authed) shell behind an ErrorBoundary, so a render fault here
 * can never blank the terminal.
 */
export default function Onboarding() {
  const { data: profile } = useProfile();
  const update = useUpdateProfile();
  const forceOnboarding = useSettings((s) => s.forceOnboarding);
  const setForceOnboarding = useSettings((s) => s.setForceOnboarding);

  const [finished, setFinished] = useState(false);
  const [step, setStep] = useState(0);
  const [markets, setMarkets] = useState<string[]>([]);
  const [seat, setSeat] = useState('');
  const [regions, setRegions] = useState<string[]>([]);

  // `finished` is a local dismissal flag: once the user finishes/skips, the modal closes REGARDLESS of whether
  // the PUT succeeds, so a failing write (500 / expired token) can never trap a first-run user (never-block
  // contract). A "Redo onboarding" request re-arms it.
  const show = !!profile && !finished && (!profile.onboarded || forceOnboarding);
  useEffect(() => {
    if (forceOnboarding) setFinished(false);
  }, [forceOnboarding]);

  // Seed from any existing facts each time the flow (re)opens (esp. "Redo onboarding") and reset to step 0.
  // Keyed on `show` only — we deliberately seed once per open, not on every background profile refetch.
  useEffect(() => {
    if (!show) return;
    const f = (profile?.facts ?? {}) as Record<string, unknown>;
    setMarkets(Array.isArray(f.markets) ? f.markets.map(String) : []);
    setSeat(typeof f.seat === 'string' ? f.seat : '');
    setRegions(Array.isArray(f.regions) ? f.regions.map(String) : []);
    setStep(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show]);

  if (!show) return null;

  const finish = () => {
    setFinished(true); // close immediately — dismissal must not depend on the PUT succeeding (never-block)
    const facts: Record<string, unknown> = {};
    if (markets.length) facts.markets = markets;
    if (seat) facts.seat = seat;
    if (regions.length) facts.regions = regions;
    update.mutate({ facts, onboarded: true });
    setForceOnboarding(false);
  };
  const next = () => (step < STEPS - 1 ? setStep((s) => s + 1) : finish());

  const toggleMarket = (c: string) => setMarkets((m) => (m.includes(c) ? m.filter((x) => x !== c) : [...m, c]));

  return (
    <Dialog.Root open onOpenChange={(o) => !o && finish()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-bg-0/70" />
        <Dialog.Content
          data-testid="onboarding"
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 z-50 flex w-[520px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 flex-col rounded-panel border border-line bg-bg-1 p-5 shadow-lg"
        >
          <div className="flex items-center justify-between">
            <Dialog.Title className="font-mono text-12 uppercase tracking-wider text-text">
              Welcome — a few quick questions
            </Dialog.Title>
            <div className="font-mono text-11 text-text-faint">step {step + 1} of {STEPS}</div>
          </div>
          <p className="mt-1 font-sans text-12 text-text-dim">
            These tailor your suggested questions. All optional — skip anything.
          </p>

          <div className="mt-4 min-h-[120px]">
            {step === 0 && (
              <div>
                <div className="mb-2 font-sans text-13 text-text">Which commodities do you follow?</div>
                <div className="flex flex-wrap gap-1.5">
                  {COMMODITIES.map((c) => (
                    <ToggleChip key={c} label={c} on={markets.includes(c)} onClick={() => toggleMarket(c)} />
                  ))}
                </div>
              </div>
            )}
            {step === 1 && (
              <div>
                <div className="mb-2 font-sans text-13 text-text">What's your seat?</div>
                <div className="flex flex-wrap gap-1.5">
                  {SEATS.map((s) => (
                    <ToggleChip key={s} label={s} on={seat === s} onClick={() => setSeat(seat === s ? '' : s)} />
                  ))}
                </div>
              </div>
            )}
            {step === 2 && (
              <div>
                <div className="mb-2 font-sans text-13 text-text">Any regions or drivers you watch?</div>
                <ChipList items={regions} onChange={setRegions} placeholder="e.g. Brazil weather — press Enter" />
              </div>
            )}
          </div>

          <div className="mt-5 flex items-center justify-between border-t border-line pt-3">
            <button
              type="button"
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0}
              className="font-mono text-11 text-text-dim hover:text-text disabled:invisible"
            >
              ← back
            </button>
            <div className="flex items-center gap-3">
              <button type="button" onClick={finish} className="font-mono text-11 text-text-faint hover:text-text-dim">
                Skip all
              </button>
              <button
                type="button"
                onClick={next}
                className="rounded-chip border border-cyan px-3 py-1 font-mono text-11 text-cyan hover:bg-bg-2"
              >
                {step < STEPS - 1 ? 'Continue' : 'Finish'}
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
