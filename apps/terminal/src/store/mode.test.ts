import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  askModeFor,
  CASCADE_MODE,
  CHOICE_COPY,
  CHOICE_COST,
  CHOICE_MODE,
  CHOICES,
  DARK_TIERS,
  DEEP_RESEARCH_DARK_TITLE,
  DEFAULT_CHOICE,
  DEFAULT_MODE,
  DOSSIER_CHOICE,
  FE_ASK_MODES,
  isAskMode,
  isChoice,
  isChoiceServed,
  isDossierChoice,
  isMetered,
  isMode,
  isModeServed,
  MODES,
  modeParam,
  NOTCHED_DARK_TIERS,
  servedChoice,
  servedModes,
  SHIPPED_SERVING_MODES,
  useMode,
  type PickerChoice,
} from './mode';

const stored = () =>
  JSON.parse(localStorage.getItem('lv-mode') ?? '{}') as { state?: { choice?: string }; version?: number };

/** A deployment whose GRAPHRAG_MODES NAMES the dark preset -- i.e. one that has taken the Cascade flip. */
const CASCADE_SERVED = 'quick,deep,max';

describe('depth notches (the ratified 3-notch ladder: Scan / Analysis / Cascade)', () => {
  beforeEach(() => {
    localStorage.clear();
    useMode.setState({ choice: DEFAULT_CHOICE });
    // THIS DESCRIBE IS ABOUT THE LADDER, SO IT RUNS ON A DEPLOYMENT THAT HAS THE LADDER. Before the
    // 2026-09-07 fix `setChoice` took `cascade` on any build at all, and the case below asserted it stuck
    // -- on a default env that does NOT serve `max`. That assertion was a small copy of the defect the
    // served-roster gate exists to prevent, so the env the ladder needs is now declared out loud.
    vi.stubEnv('VITE_MODES', CASCADE_SERVED);
  });

  afterEach(() => vi.unstubAllEnvs());

  it('is exactly THREE notches, shallow -> deep, with Cascade on top and Scan the default', () => {
    expect([...CHOICES]).toEqual(['quick', 'deep', 'cascade']);
    expect(DEFAULT_CHOICE).toBe('quick');
    expect(useMode.getState().choice).toBe('quick');
    // The owner's word, 2026-09-06: "keep Cascade just as we designed it to be the third place on the
    // scaler". The TOP notch is the deepest ASK now, not a different submit route.
    expect(CHOICES[CHOICES.length - 1]).toBe('cascade');
  });

  it('Deep Research LEFT the slider: it is not a notch, cannot be selected, and keeps its route', () => {
    // Owner's word, same sitting: Deep Research becomes a standalone control at the right of the ask bar,
    // lights off, until V1.2. Off the ramp means off `CHOICES` -- so `isChoice` rejects it, `setChoice`
    // coerces it, and `merge` cannot rehydrate it. What survives is the SUBMIT ROUTE Shell branches on.
    expect(CHOICES as readonly string[]).not.toContain('deep_research');
    expect(isChoice('deep_research')).toBe(false);
    expect(DOSSIER_CHOICE).toBe('deep_research');
    expect(isDossierChoice(DOSSIER_CHOICE)).toBe(true);
    expect(CHOICE_MODE.deep_research).toBeNull(); // still never an ask mode
    expect(CHOICE_COPY.deep_research.label).toBe('Deep Research'); // the copy comes back with the notch
    expect(DEEP_RESEARCH_DARK_TITLE).toBe('Deep Research will be available in Leviathan V1.2');
  });

  it('the labels are Scan / Analysis / Cascade — internal identifiers never reach the screen', () => {
    expect(CHOICE_COPY.quick.label).toBe('Scan');
    expect(CHOICE_COPY.deep.label).toBe('Analysis');
    expect(CHOICE_COPY.cascade.label).toBe('Cascade');
    // The naming law in three assertions: the LABEL is a product word, the WIRE value is the frozen
    // identifier, and Cascade's identifier is a preset that is NOT in the internal `MODES` roster.
    expect(askModeFor('quick')).toBe('quick');
    expect(askModeFor('deep')).toBe('deep');
    expect(askModeFor('cascade')).toBe('max');
    expect(CASCADE_MODE).toBe('max');
  });

  it('every notch carries selector copy, and none of it invents a latency number', () => {
    for (const c of [...CHOICES, DOSSIER_CHOICE]) {
      expect(CHOICE_COPY[c].time.length).toBeGreaterThan(0);
      expect(CHOICE_COPY[c].detail.length).toBeGreaterThan(0);
      // D-AM-13 is explicit: static selector copy is RELATIVE. No "12s"/"1200ms" until the EMF `mode`
      // dimension has real traffic behind it.
      expect(`${CHOICE_COPY[c].time} ${CHOICE_COPY[c].detail}`).not.toMatch(/\d+\s*(ms|sec|s\b|min)/i);
    }
    expect(CHOICE_COPY.cascade.time).toBe('the longest turn');
    expect(CHOICE_COPY.cascade.detail).toContain('two credits');
  });

  it('prices: Scan free, Analysis one credit, Cascade two — and the ladder only ever rises', () => {
    expect(CHOICE_COST.quick).toBe(0);
    expect(CHOICE_COST.deep).toBe(1);
    expect(CHOICE_COST.cascade).toBe(2);
    expect(CHOICE_COST.deep_research).toBe(0); // its own monthly allowance, not the credit grant
    expect(isMetered('quick')).toBe(false);
    expect(isMetered('deep')).toBe(true);
    expect(isMetered('cascade')).toBe(true);
    expect(isMetered('deep_research')).toBe(false);
    // THESE ARE THE SERVER'S OWN NUMBERS (leviathan.graphrag.server._CREDIT_PRICES: deep 1, max 2, quick
    // absent = free), and the backend lint `config_check.check_cascade_notch` clause (vi) reads THIS file
    // to assert it. A price on screen that is not the price charged is the one defect a badge cannot show.
    const ladder = CHOICES.map((c) => CHOICE_COST[c] ?? 0);
    expect(ladder).toEqual([0, 1, 2]);
    for (let i = 1; i < ladder.length; i += 1) expect(ladder[i]!).toBeGreaterThan(ladder[i - 1]!);
  });

  it('setChoice coerces anything unknown back to the default', () => {
    useMode.getState().setChoice('cascade');
    expect(useMode.getState().choice).toBe('cascade');
    useMode.getState().setChoice('deep_research'); // OFF the slider since 2026-09-06
    expect(useMode.getState().choice).toBe('quick');
    useMode.getState().setChoice('standard' as PickerChoice); // the passthrough is not a notch
    expect(useMode.getState().choice).toBe('quick');
    useMode.getState().setChoice('max' as PickerChoice); // the WIRE name is not the NOTCH name
    expect(useMode.getState().choice).toBe('quick');
    useMode.getState().setChoice('ultra' as PickerChoice);
    expect(useMode.getState().choice).toBe('quick');
  });

  it('setChoice ALSO refuses a notch this deployment does not serve, and lands DOWN the ladder', () => {
    // The write half of the 2026-09-07 fix. `DepthControl.pick` already refused the gesture, but that is a
    // fence around ONE call site: any other caller could put `cascade` into the store on a build whose
    // deployment resolves `max` to `standard`, and the submit path would then ask for a tier nobody honors.
    vi.stubEnv('VITE_MODES', ''); // a build told nothing -> the SHIPPED roster, which has no `max`
    useMode.getState().setChoice('cascade');
    expect(useMode.getState().choice).toBe('deep'); // the deepest notch this deployment will actually run
    vi.stubEnv('VITE_MODES', 'quick'); // and with Analysis gone too, all the way down to the free tier
    useMode.getState().setChoice('cascade');
    expect(useMode.getState().choice).toBe('quick');
  });

  it('isChoice / isDossierChoice are the guards the rest of the app leans on', () => {
    expect(isChoice('quick')).toBe(true);
    expect(isChoice('deep')).toBe(true);
    expect(isChoice('cascade')).toBe(true);
    expect(isChoice('deep_research')).toBe(false);
    expect(isChoice('standard')).toBe(false);
    expect(isChoice('max')).toBe(false);
    expect(isChoice(undefined)).toBe(false);
    expect(isChoice(3)).toBe(false);

    expect(isDossierChoice('deep_research')).toBe(true);
    expect(isDossierChoice('quick')).toBe(false);
    expect(isDossierChoice('deep')).toBe(false); // the deep MODE is an ask, not the dossier job
    expect(isDossierChoice('cascade')).toBe(false);
    expect(isDossierChoice(undefined)).toBe(false);
  });

  it('askModeFor: every slider notch has a wire name, the dossier route has none', () => {
    expect(askModeFor('deep_research')).toBeUndefined();
    // FE_ASK_MODES is exactly the notches that produce a `mode` param, in notch order.
    expect([...FE_ASK_MODES]).toEqual(['quick', 'deep', 'max']);
  });
});

// The INTERNAL identifiers survive every relabel untouched (the D-CC/D-DR/D-MW-22 naming law): they ride
// EMF dimensions, trace stamps and every stored baseline, so a UI change may not move them.
describe('internal mode identifiers (unchanged by the Cascade notch)', () => {
  it('is still exactly the three ratified names, in depth order', () => {
    expect([...MODES]).toEqual(['quick', 'standard', 'deep']);
    expect(DEFAULT_MODE).toBe('standard');
  });

  it('isMode still recognises all three, and NOT `max` — which is the point', () => {
    expect(isMode('quick')).toBe(true);
    expect(isMode('deep')).toBe(true);
    expect(isMode('standard')).toBe(true);
    expect(isMode('deep_research')).toBe(false); // a notch is not a mode
    // `max` is Cascade's WIRE name but never an internal roster name: `MODES` is what the mock lane is
    // keyed on (api/mock.MOCK_MODE_KNOBS: Record<ModeName, ...>) and Cascade has no mock fixture. What it
    // joins instead is `AskMode` -- see `isAskMode` below.
    expect(isMode('max')).toBe(false);
    expect(isMode('ultra')).toBe(false);
    expect(isMode('')).toBe(false);
    expect(isMode(undefined)).toBe(false);
    expect(isMode(null)).toBe(false);
    expect(isMode(3)).toBe(false);
  });

  it('isAskMode is the wider union: the internal roster PLUS the gated dark tiers this bundle notches', () => {
    for (const m of MODES) expect(isAskMode(m)).toBe(true);
    expect(isAskMode('max')).toBe(true);
    expect(isAskMode('max_c0')).toBe(false); // a dark tier with no notch is not askable
    expect(isAskMode('deep_research')).toBe(false);
    expect(isAskMode(undefined)).toBe(false);
    expect(isAskMode(7)).toBe(false);
  });

  it('names the DARK tiers explicitly, so their absence is a decision and not an oversight', () => {
    // The census is the server-side `reasoning_modes.DARK_NAMES` roster at HEAD, in the order mode.ts
    // records it. The real fence is `serving_names()` (= valid_names() - DARK_NAMES), which no FE test can
    // read -- so this pin's job is to make a STALE census fail loudly here rather than mislead a reader,
    // and it must be updated on the same change that flips or mints a dark tier.
    //
    // T2-2 (2026-08-15) IS THE FIRST TIME THAT RULE WAS TESTED, AND IT FAILED ON THE FIRST TRY: minting
    // `deep_cc1` into the backend's DARK_NAMES left this census at 10 names one commit after T1-7 had
    // just repaired it. IT THEN WENT STALE AGAIN, by two names (`max_cc2`, `quick_n3`), which is what the
    // 2026-09-06 sitting found. THE REASON THIS PIN CANNOT CATCH IT, recorded: the assertion compares the
    // FE list against a LITERAL COPY OF ITSELF, so it stays green through any backend drift and "the
    // parity pin is still green" is true and NON-PROBATIVE.
    //
    // SINCE 2026-09-07 THE LOOP IS CLOSED FROM THE OTHER SIDE, and that is the fix rather than a third
    // repair of a list: `leviathan.graphrag.config_check.check_cascade_notch` clause (vi) reads THIS
    // literal out of store/mode.ts and asserts it equals `reasoning_modes.DARK_NAMES` name-for-name. The
    // backend lint is now what fails when the census drifts -- 15 names there, 15 names here, as of
    // 2026-09-08. AND IT WORKED, first time it was tested from the backend side: SCAN RUNG 3 minted
    // `quick_s` + `quick_r0` into DARK_NAMES, `check_cascade_notch` clause (vi) went red naming both
    // missing names, and this literal and store/mode.ts moved in that same change.
    expect([...DARK_TIERS]).toEqual([
      'deep_v2',
      'max',
      'max_c0',
      'esc',
      'esc_r',
      'max_cc1',
      'max_cc2',
      'deep_cc1',
      'quick_hp',
      'deep_hp',
      'esc_hp',
      'esc_r_hp',
      'quick_n3',
      'quick_s',
      'quick_r0',
    ]);
    expect(DARK_TIERS).toHaveLength(15);
    // `standard` can never be dark: its all-None knob dict IS the backend's fail-open guarantee.
    expect(DARK_TIERS).not.toContain('standard');
    for (const t of DARK_TIERS) {
      // Still true of every one of them, INCLUDING `max`: the notch is named `cascade` and the internal
      // roster never grew a dark name. The permitted overlap is stated once, in NOTCHED_DARK_TIERS.
      expect(MODES as readonly string[]).not.toContain(t);
      expect(CHOICES as readonly string[]).not.toContain(t);
    }
  });

  it('the ONE dark tier this bundle notches is `max`, and it is listed as such', () => {
    expect([...NOTCHED_DARK_TIERS]).toEqual(['max']);
    for (const t of NOTCHED_DARK_TIERS) expect(DARK_TIERS).toContain(t);
    // Everything else stays un-offered: a dark tier with a notch is a decision, not a default.
    for (const t of DARK_TIERS) {
      if (NOTCHED_DARK_TIERS.includes(t)) continue;
      expect(FE_ASK_MODES as readonly string[]).not.toContain(t);
    }
  });
});

// THE SERVED-ROSTER GATE. `max` is dark server-side, so it is honored ONLY where GRAPHRAG_MODES names it.
// Nothing in the browser can read that env (no /modes route, no healthz field -- checked 2026-09-07), so
// the bundle is TOLD at build time via VITE_MODES and the notch is gated on it.
describe('servedModes — what this build was told the deployment honors', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('told nothing, it assumes the SHIPPED roster — so Cascade is blocked, never silently downgraded', () => {
    vi.stubEnv('VITE_MODES', '');
    expect([...servedModes()]).toEqual([...SHIPPED_SERVING_MODES]);
    expect(isModeServed('quick')).toBe(true);
    expect(isModeServed('deep')).toBe(true);
    expect(isModeServed('max')).toBe(false);
    expect(isChoiceServed('cascade')).toBe(false);
    expect(isChoiceServed('quick')).toBe(true);
  });

  it('the WILDCARD is not a licence: `on` means serving_names(), which excludes every dark preset', () => {
    // This mirrors the backend exactly (orchestrator._modes_enabled: 'on' -> rm.serving_names()). A build
    // told `on` must not offer Cascade, because a deployment told `on` will not honor it.
    for (const v of ['on', '1', 'true', 'off']) {
      vi.stubEnv('VITE_MODES', v);
      expect(isModeServed('max')).toBe(false);
    }
  });

  it('a NAMED allowlist that carries `max` is what unlocks the notch', () => {
    vi.stubEnv('VITE_MODES', 'quick,deep,max');
    expect(isModeServed('max')).toBe(true);
    expect(isChoiceServed('cascade')).toBe(true);
    // Whitespace and case are the taskdef's, not ours to be strict about.
    vi.stubEnv('VITE_MODES', ' QUICK , DEEP , MAX ');
    expect(isModeServed('max')).toBe(true);
  });

  it('`standard` is served everywhere — it is the fail-open passthrough and needs no flag', () => {
    vi.stubEnv('VITE_MODES', 'quick');
    expect(isModeServed('standard')).toBe(true);
    expect(isModeServed('deep')).toBe(false); // and a roster that drops a tier really does drop it
  });

  it('the dossier route is never "served" — it is not an ask mode at all', () => {
    vi.stubEnv('VITE_MODES', 'quick,deep,max');
    expect(isChoiceServed(DOSSIER_CHOICE)).toBe(false);
  });
});

// THE GATE APPLIED TO A VALUE (2026-09-07). `isChoiceServed` answers a question; `servedChoice` acts on the
// answer. The distinction is the whole defect the fix pass closed: blocking `pick`/`step`/`jump` fences the
// GESTURES, and a store that already holds `cascade` never makes one. Measured through the real Shell
// before this function existed: the control rendered "Cascade is not yet enabled on this deployment", the
// slider still read `Cascade`, and the submit sent `mode=max` -- which serving resolves to `standard` with
// no chip (views/answer/ModeChip.tsx draws nothing for `standard`) and no error anywhere.
describe('servedChoice — the correction, and the direction it is allowed to move in', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('leaves a selection alone when the deployment serves it', () => {
    vi.stubEnv('VITE_MODES', 'quick,deep,max');
    for (const c of CHOICES) expect(servedChoice(c)).toBe(c);
  });

  it('walks DOWN to the deepest served notch — the rehydrated-blob case, exactly', () => {
    // What a returning user's v3 blob holds after their bundle was rebuilt without VITE_MODES, or after a
    // serving rollback: a perfectly valid `CHOICES` member that this deployment will not run.
    vi.stubEnv('VITE_MODES', '');
    expect(servedChoice('cascade')).toBe('deep');
    vi.stubEnv('VITE_MODES', 'quick');
    expect(servedChoice('cascade')).toBe('quick');
    expect(servedChoice('deep')).toBe('quick');
  });

  it('NEVER walks up — a correction may not spend more than the selection it replaces', () => {
    // A deployment serving Scan and Cascade but not Analysis. Coercing the missing middle notch UP would
    // turn a one-credit selection into a two-credit turn because OUR roster drifted. It goes down.
    vi.stubEnv('VITE_MODES', 'quick,max');
    expect(servedChoice('deep')).toBe('quick');
    expect(servedChoice('deep')).not.toBe('cascade');
    // And when nothing at or below is served, the free default — never the dearest thing on offer.
    vi.stubEnv('VITE_MODES', 'max');
    expect(servedChoice('deep')).toBe(DEFAULT_CHOICE);
    expect(CHOICE_COST[servedChoice('deep')]).toBe(0);
  });

  it('a value that is NOT ON THE LADDER resets to the default — it never enters the walk', () => {
    // THE BOUNDARY THE FIRST VERSION GOT BACKWARDS, and it got it backwards in the one direction three
    // doc blocks and Shell's call site all swear this function cannot move in. `CHOICES.indexOf` returns
    // -1 for anything off the ladder, and the descent started at `CHOICES.length - 1` for it — so an
    // unplaceable value came back as the TOP notch. MEASURED before the fix, on this exact roster:
    // servedChoice('garbage') === 'cascade', cost 2. Unreachable through shipped code today (every caller
    // pre-guards with `isChoice`), which is exactly why only a test can hold it: the `PickerChoice` union
    // is documented as GROWING in V1.2, and the loops below only ever feed it CHOICES members.
    vi.stubEnv('VITE_MODES', 'quick,deep,max');
    for (const junk of ['garbage', '', 'max', 'MAX', 'deep_v2', undefined, null, 0, {}]) {
      const out = servedChoice(junk as unknown as PickerChoice);
      expect(out).toBe(DEFAULT_CHOICE);
      expect(CHOICE_COST[out]).toBe(0);
    }
  });

  it('the dossier ROUTE passes through untouched, on any roster', () => {
    // `deep_research` maps to a null wire by design, so `isChoiceServed` is false for it forever. Coercing
    // it here would silently turn a dossier submit into a turn — the one thing Shell's branch must never do.
    for (const v of ['', 'quick,deep,max', 'quick']) {
      vi.stubEnv('VITE_MODES', v);
      expect(servedChoice(DOSSIER_CHOICE)).toBe(DOSSIER_CHOICE);
    }
  });

  it('the coerced result is always something this deployment actually runs', () => {
    for (const v of ['', 'on', 'quick,deep,max', 'quick', 'quick,max', 'deep']) {
      vi.stubEnv('VITE_MODES', v);
      for (const c of CHOICES) {
        const out = servedChoice(c);
        // The one exception the fall-through allows: a roster serving NO notch at all lands on the free
        // default, whose wire name (`quick`) the backend fails open on anyway — and which bills nothing.
        if (!isChoiceServed(out)) {
          expect(out).toBe(DEFAULT_CHOICE);
          expect(CHOICE_COST[out]).toBe(0);
        }
        expect(CHOICE_COST[out]).toBeLessThanOrEqual(CHOICE_COST[c]);
      }
    }
  });
});

// The wire rule. Since D-MW-21 no NOTCH can reach the omit branch -- Scan sends `quick` explicitly -- so
// what this now pins is the no-request/API caller's passthrough and the floor under a corrupt stored value.
describe('modeParam — the omit-when-standard wire rule (now reachable only without a notch)', () => {
  it('standard, absent and empty all mean SEND NOTHING', () => {
    expect(modeParam('standard')).toBeUndefined();
    expect(modeParam(undefined)).toBeUndefined();
    expect(modeParam(null)).toBeUndefined();
    expect(modeParam('')).toBeUndefined();
  });

  it('a recognised non-standard ask mode is sent as itself — `max` INCLUDED', () => {
    expect(modeParam('quick')).toBe('quick');
    expect(modeParam('deep')).toBe('deep');
    // THE CASCADE HALF OF THE SILENT-DROP TRAP: a `modeParam` that only knew `ModeName` would drop `max`
    // and send a mode-LESS request, which the backend fails open to `standard`. A two-credit selection
    // would then deliver a free turn's depth with no error anywhere.
    expect(modeParam('max')).toBe('max');
  });

  it('anything unrecognised is dropped rather than forwarded', () => {
    // The backend fails open on an unknown name (resolve() -> standard + invalid:true, never a 422), so
    // this is belt-and-braces: what it really buys is that a corrupted stored value cannot silently
    // change a request. `deep_research` is in this set BY DESIGN -- the dossier is a different route
    // entirely, and a notch must never be able to ride the turn's `mode` param.
    expect(modeParam('deep_research')).toBeUndefined();
    expect(modeParam('max_c0')).toBeUndefined(); // a dark tier with no notch is still not askable
    expect(modeParam('ultra')).toBeUndefined();
    expect(modeParam('DEEP')).toBeUndefined();
    expect(modeParam(' deep ')).toBeUndefined();
  });
});

describe('choice persistence (localStorage lv-mode)', () => {
  beforeEach(() => {
    localStorage.clear();
    useMode.setState({ choice: DEFAULT_CHOICE });
    vi.stubEnv('VITE_MODES', CASCADE_SERVED); // a flipped deployment, so a Cascade selection means something
  });

  afterEach(() => vi.unstubAllEnvs());

  it('a choice survives into localStorage under its own key, at version 3', () => {
    useMode.getState().setChoice('deep');
    expect(stored().state?.choice).toBe('deep');
    expect(stored().version).toBe(3);
    expect(localStorage.getItem('lv-ui')).toBeNull(); // its own key -- never grafted onto the ui blob
  });

  it('rehydrates a stored choice at the CURRENT version', async () => {
    localStorage.setItem('lv-mode', JSON.stringify({ state: { choice: 'deep' }, version: 3 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('deep');
  });

  it('the version does NOT move for the Cascade amendment, and a stored deep_research still lands on Scan', async () => {
    // No stored value's PRICE moved: `quick` is still free and `deep` is still one credit. `cascade` is a
    // name no v3 blob can contain, and `deep_research` -- which v3 blobs CAN contain -- is no longer a
    // `CHOICES` member, so `merge` coerces it on every rehydrate without a version bump. Bumping would
    // only discard `deep` selections that are exactly as priced as when they were made.
    localStorage.setItem('lv-mode', JSON.stringify({ state: { choice: 'deep_research' }, version: 3 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('quick');
    useMode.getState().setChoice('cascade');
    expect(stored().version).toBe(3);
  });

  it('a foreign/corrupt stored value rehydrates to the default, not onto the store shape', async () => {
    // `merge` (not `migrate`) does this on PURPOSE: at the current version a migrate never runs, so a
    // blob written by a newer bundle -- or hand-edited -- would otherwise graft an unknown name straight
    // into the store and out onto the wire. `max` is the live example: the WIRE name is not the NOTCH
    // name, and a blob carrying it must not be able to make this bundle spend at a tier it cannot price.
    for (const bad of ['ultra', 'max', 'standard', 'deep_research']) {
      localStorage.setItem('lv-mode', JSON.stringify({ state: { choice: bad }, version: 3 }));
      await useMode.persist.rehydrate();
      expect(useMode.getState().choice).toBe('quick');
    }
    localStorage.setItem('lv-mode', JSON.stringify({ state: {}, version: 3 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('quick');
  });

  it('a stored Cascade rehydrates as Cascade where it is served, and DOWN where it is not', async () => {
    // THE RETURNING-USER PATH, and the second of the two live routes into the 2026-09-07 defect (the first
    // is a direct setState). `merge` accepted any CHOICES member, so a v3 blob written by a bundle that WAS
    // told `max` came straight back as `cascade` on a bundle that was not — and the next submit asked for a
    // tier that deployment resolves to `standard`, unbilled and unannounced. No version bump can catch it:
    // the blob is current, and its PRICE never moved. The correction belongs at the rehydrate.
    localStorage.setItem('lv-mode', JSON.stringify({ state: { choice: 'cascade' }, version: 3 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('cascade'); // this build was told `max` is honored

    vi.stubEnv('VITE_MODES', ''); // the same blob, on a bundle rebuilt without VITE_MODES
    useMode.setState({ choice: 'cascade' });
    localStorage.setItem('lv-mode', JSON.stringify({ state: { choice: 'cascade' }, version: 3 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('deep'); // corrected once, at boot, before anything reads it
  });

  it('EVERY older blob lands on Scan — a stale selection never silently spends', async () => {
    // v1 held `mode` (three internal names); v2 held `choice` over an entirely UNMETERED two-entry roster.
    // Neither may carry forward: `deep` now costs a credit, `cascade` two, and no stored value predating
    // those prices is consent to pay them.
    for (const blob of [
      { state: { mode: 'deep' }, version: 1 },
      { state: { mode: 'standard' }, version: 1 },
      { state: { choice: 'deep_research' }, version: 2 },
      { state: { choice: 'quick' }, version: 2 },
    ]) {
      useMode.setState({ choice: 'deep' }); // start from a NON-default, so a no-op would be visible
      localStorage.setItem('lv-mode', JSON.stringify(blob));
      await useMode.persist.rehydrate();
      expect(useMode.getState().choice).toBe('quick');
    }
  });
});
