import { beforeEach, describe, expect, it } from 'vitest';
import {
  askModeFor,
  CHOICE_COPY,
  CHOICE_COST,
  CHOICE_MODE,
  CHOICES,
  DARK_TIERS,
  DEFAULT_CHOICE,
  DEFAULT_MODE,
  FE_ASK_MODES,
  isChoice,
  isDossierChoice,
  isMetered,
  isMode,
  MODES,
  modeParam,
  useMode,
  type PickerChoice,
} from './mode';

const stored = () =>
  JSON.parse(localStorage.getItem('lv-mode') ?? '{}') as { state?: { choice?: string }; version?: number };

describe('depth notches (D-MW-21 — the ratified 2-notch ship + the dossier)', () => {
  beforeEach(() => {
    localStorage.clear();
    useMode.setState({ choice: DEFAULT_CHOICE });
  });

  it('is exactly THREE notches, shallow -> deep, with the dossier on top and Scan the default', () => {
    expect([...CHOICES]).toEqual(['quick', 'deep', 'deep_research']);
    expect(DEFAULT_CHOICE).toBe('quick');
    expect(useMode.getState().choice).toBe('quick');
    // The top notch is the JOB, and it stays the top notch: Shell's separate submit route depends on it.
    expect(CHOICES[CHOICES.length - 1]).toBe('deep_research');
  });

  it('the labels are Scan / Analysis / Deep Research — internal identifiers never reach the screen', () => {
    expect(CHOICE_COPY.quick.label).toBe('Scan');
    expect(CHOICE_COPY.deep.label).toBe('Analysis');
    expect(CHOICE_COPY.deep_research.label).toBe('Deep Research');
    // The naming law in two assertions: the LABEL is a product word, the WIRE value is the frozen identifier.
    expect(askModeFor('quick')).toBe('quick');
    expect(askModeFor('deep')).toBe('deep');
  });

  it('every notch carries selector copy, and none of it invents a latency number', () => {
    for (const c of CHOICES) {
      expect(CHOICE_COPY[c].time.length).toBeGreaterThan(0);
      expect(CHOICE_COPY[c].detail.length).toBeGreaterThan(0);
      // D-AM-13 is explicit: static selector copy is RELATIVE. No "12s"/"1200ms" until the EMF `mode`
      // dimension has real traffic behind it.
      expect(`${CHOICE_COPY[c].time} ${CHOICE_COPY[c].detail}`).not.toMatch(/\d+\s*(ms|sec|s\b|min)/i);
    }
  });

  it('prices: Scan is UNMETERED, Analysis costs one credit, the dossier is metered elsewhere', () => {
    expect(CHOICE_COST.quick).toBe(0);
    expect(CHOICE_COST.deep).toBe(1);
    expect(CHOICE_COST.deep_research).toBe(0); // its own monthly allowance, not the credit grant
    expect(isMetered('quick')).toBe(false);
    expect(isMetered('deep')).toBe(true);
    expect(isMetered('deep_research')).toBe(false);
    // The ratified 2-notch ship has NO 3-credit tier, because it has no `max` notch to price.
    expect(Object.values(CHOICE_COST).every((n) => n <= 1)).toBe(true);
  });

  it('setChoice coerces anything unknown back to the default', () => {
    useMode.getState().setChoice('deep_research');
    expect(useMode.getState().choice).toBe('deep_research');
    useMode.getState().setChoice('standard' as PickerChoice); // the passthrough is not a notch
    expect(useMode.getState().choice).toBe('quick');
    useMode.getState().setChoice('max' as PickerChoice); // a DARK backend tier is not a notch either
    expect(useMode.getState().choice).toBe('quick');
    useMode.getState().setChoice('ultra' as PickerChoice);
    expect(useMode.getState().choice).toBe('quick');
  });

  it('isChoice / isDossierChoice are the guards the rest of the app leans on', () => {
    expect(isChoice('quick')).toBe(true);
    expect(isChoice('deep')).toBe(true);
    expect(isChoice('deep_research')).toBe(true);
    expect(isChoice('standard')).toBe(false);
    expect(isChoice('max')).toBe(false);
    expect(isChoice(undefined)).toBe(false);
    expect(isChoice(3)).toBe(false);

    expect(isDossierChoice('deep_research')).toBe(true);
    expect(isDossierChoice('quick')).toBe(false);
    expect(isDossierChoice('deep')).toBe(false); // the deep MODE is an ask, not the dossier job
    expect(isDossierChoice(undefined)).toBe(false);
  });

  it('askModeFor: an ask notch has a wire name, the dossier notch has none', () => {
    expect(askModeFor('deep_research')).toBeUndefined();
    expect(CHOICE_MODE.deep_research).toBeNull();
    // FE_ASK_MODES is exactly the notches that produce a `mode` param, in notch order.
    expect([...FE_ASK_MODES]).toEqual(['quick', 'deep']);
  });
});

// The INTERNAL identifiers survive every relabel untouched (the D-CC/D-DR/D-MW-22 naming law): they ride
// EMF dimensions, trace stamps and every stored baseline, so a UI change may not move them.
describe('internal mode identifiers (unchanged by D-MW-21)', () => {
  it('is still exactly the three ratified names, in depth order', () => {
    expect([...MODES]).toEqual(['quick', 'standard', 'deep']);
    expect(DEFAULT_MODE).toBe('standard');
  });

  it('isMode still recognises all three, and nothing else', () => {
    expect(isMode('quick')).toBe(true);
    expect(isMode('deep')).toBe(true);
    expect(isMode('standard')).toBe(true);
    expect(isMode('deep_research')).toBe(false); // a notch is not a mode
    expect(isMode('max')).toBe(false); // DARK: not in this bundle's roster at all
    expect(isMode('ultra')).toBe(false);
    expect(isMode('')).toBe(false);
    expect(isMode(undefined)).toBe(false);
    expect(isMode(null)).toBe(false);
    expect(isMode(3)).toBe(false);
  });

  it('names the DARK tiers explicitly, so their absence is a decision and not an oversight', () => {
    expect([...DARK_TIERS]).toEqual(['max', 'max_c0']);
    for (const t of DARK_TIERS) {
      expect(MODES as readonly string[]).not.toContain(t);
      expect(CHOICES as readonly string[]).not.toContain(t);
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

  it('a recognised non-standard mode is sent as itself', () => {
    expect(modeParam('quick')).toBe('quick');
    expect(modeParam('deep')).toBe('deep');
  });

  it('anything unrecognised is dropped rather than forwarded', () => {
    // The backend fails open on an unknown name (resolve() -> standard + invalid:true, never a 422), so
    // this is belt-and-braces: what it really buys is that a corrupted stored value cannot silently
    // change a request. `deep_research` is in this set BY DESIGN -- the dossier is a different route
    // entirely, and a notch must never be able to ride the turn's `mode` param.
    expect(modeParam('deep_research')).toBeUndefined();
    expect(modeParam('max')).toBeUndefined();
    expect(modeParam('ultra')).toBeUndefined();
    expect(modeParam('DEEP')).toBeUndefined();
    expect(modeParam(' deep ')).toBeUndefined();
  });
});

describe('choice persistence (localStorage lv-mode)', () => {
  beforeEach(() => {
    localStorage.clear();
    useMode.setState({ choice: DEFAULT_CHOICE });
  });

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

  it('a foreign/corrupt stored value rehydrates to the default, not onto the store shape', async () => {
    // `merge` (not `migrate`) does this on PURPOSE: at the current version a migrate never runs, so a
    // blob written by a newer bundle -- or hand-edited -- would otherwise graft an unknown name straight
    // into the store and out onto the wire. `max` is the live example: a future bundle that ships it
    // must not be able to make THIS bundle spend at a tier it does not know the price of.
    for (const bad of ['ultra', 'max', 'standard']) {
      localStorage.setItem('lv-mode', JSON.stringify({ state: { choice: bad }, version: 3 }));
      await useMode.persist.rehydrate();
      expect(useMode.getState().choice).toBe('quick');
    }
    localStorage.setItem('lv-mode', JSON.stringify({ state: {}, version: 3 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('quick');
  });

  it('EVERY older blob lands on Scan — a stale selection never silently spends', async () => {
    // v1 held `mode` (three internal names); v2 held `choice` over an entirely UNMETERED two-entry roster.
    // Neither may carry forward: `deep` now costs a credit and `deep_research` one of four monthly runs,
    // and no stored value predating those prices is consent to pay them.
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
