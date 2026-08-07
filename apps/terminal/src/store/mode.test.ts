import { beforeEach, describe, expect, it } from 'vitest';
import {
  ASK_MODE,
  CHOICE_COPY,
  CHOICES,
  DEFAULT_CHOICE,
  DEFAULT_MODE,
  isChoice,
  isDossierChoice,
  isMode,
  MODES,
  modeParam,
  useMode,
  type PickerChoice,
} from './mode';

const stored = () => JSON.parse(localStorage.getItem('lv-mode') ?? '{}') as { state?: { choice?: string } };

describe('picker choice store (D-DR-3 — two options)', () => {
  beforeEach(() => {
    localStorage.clear();
    useMode.setState({ choice: DEFAULT_CHOICE });
  });

  it('is exactly TWO choices, ask first, defaulting to the ordinary ask', () => {
    expect([...CHOICES]).toEqual(['quick', 'deep_research']);
    expect(DEFAULT_CHOICE).toBe('quick');
    expect(useMode.getState().choice).toBe('quick');
  });

  it('the labels are Standard and Deep Research — internal identifiers never reach the screen', () => {
    expect(CHOICE_COPY.quick.label).toBe('Standard');
    expect(CHOICE_COPY.deep_research.label).toBe('Deep Research');
    // The naming law in one assertion: the LABEL is Standard, the WIRE value is `quick`.
    expect(ASK_MODE).toBe('quick');
  });

  it('every choice carries selector copy, and none of it invents a latency number', () => {
    for (const c of CHOICES) {
      expect(CHOICE_COPY[c].time.length).toBeGreaterThan(0);
      expect(CHOICE_COPY[c].detail.length).toBeGreaterThan(0);
      // D-AM-14 is explicit: static selector copy is RELATIVE. No "12s"/"1200ms" until the EMF `mode`
      // dimension has real traffic behind it.
      expect(`${CHOICE_COPY[c].time} ${CHOICE_COPY[c].detail}`).not.toMatch(/\d+\s*(ms|sec|s\b)/i);
    }
  });

  it('setChoice coerces anything unknown back to the default', () => {
    useMode.getState().setChoice('deep_research');
    expect(useMode.getState().choice).toBe('deep_research');
    useMode.getState().setChoice('deep' as PickerChoice); // an INTERNAL mode name is not a choice
    expect(useMode.getState().choice).toBe('quick');
    useMode.getState().setChoice('ultra' as PickerChoice);
    expect(useMode.getState().choice).toBe('quick');
  });

  it('isChoice / isDossierChoice are the guards the rest of the app leans on', () => {
    expect(isChoice('quick')).toBe(true);
    expect(isChoice('deep_research')).toBe(true);
    expect(isChoice('standard')).toBe(false);
    expect(isChoice('deep')).toBe(false);
    expect(isChoice(undefined)).toBe(false);
    expect(isChoice(3)).toBe(false);

    expect(isDossierChoice('deep_research')).toBe(true);
    expect(isDossierChoice('quick')).toBe(false);
    expect(isDossierChoice('deep')).toBe(false); // the internal deep mode is NOT the dossier
    expect(isDossierChoice(undefined)).toBe(false);
  });
});

// The INTERNAL identifiers survive the relabel untouched (the D-CC/D-DR naming law): they ride EMF
// dimensions, trace stamps and every stored baseline, so the UI change may not move them.
describe('internal mode identifiers (unchanged by D-DR-3)', () => {
  it('is still exactly the three ratified names, in depth order', () => {
    expect([...MODES]).toEqual(['quick', 'standard', 'deep']);
    expect(DEFAULT_MODE).toBe('standard');
  });

  it('isMode still recognises all three, and nothing else', () => {
    expect(isMode('quick')).toBe(true);
    expect(isMode('deep')).toBe(true);
    expect(isMode('standard')).toBe(true);
    expect(isMode('deep_research')).toBe(false); // a picker choice is not a mode
    expect(isMode('ultra')).toBe(false);
    expect(isMode('')).toBe(false);
    expect(isMode(undefined)).toBe(false);
    expect(isMode(null)).toBe(false);
    expect(isMode(3)).toBe(false);
  });
});

// The single rule that keeps a standard turn's request byte-identical to the pre-wave one. No UI path
// reaches `standard` any more, but the no-request/API callers do, so the rule stays pinned.
describe('modeParam — the omit-when-standard wire rule', () => {
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
    // entirely, and a picker choice must never be able to ride the turn's `mode` param.
    expect(modeParam('deep_research')).toBeUndefined();
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

  it('a choice survives into localStorage under its own key', () => {
    useMode.getState().setChoice('deep_research');
    expect(stored().state?.choice).toBe('deep_research');
    expect(localStorage.getItem('lv-ui')).toBeNull(); // its own key -- never grafted onto the ui blob
  });

  it('rehydrates a stored choice', async () => {
    localStorage.setItem('lv-mode', JSON.stringify({ state: { choice: 'deep_research' }, version: 2 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('deep_research');
  });

  it('a foreign/corrupt stored value rehydrates to the default, not onto the store shape', async () => {
    // `merge` (not `migrate`) does this on PURPOSE: at the current version a migrate never runs, so a
    // blob written by a newer bundle -- or hand-edited -- would otherwise graft an unknown name straight
    // into the store and out onto the wire.
    localStorage.setItem('lv-mode', JSON.stringify({ state: { choice: 'ultra' }, version: 2 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('quick');

    localStorage.setItem('lv-mode', JSON.stringify({ state: {}, version: 2 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().choice).toBe('quick');
  });

  it('a v1 blob (the three-mode era) lands on Standard — never on Deep Research', async () => {
    // The quota is three dossiers a WEEK. Promoting a stored `deep` into Deep Research would spend one on
    // a choice the returning user never made, so every legacy value resolves to the ordinary ask.
    for (const legacy of ['deep', 'standard', 'quick']) {
      localStorage.setItem('lv-mode', JSON.stringify({ state: { mode: legacy }, version: 1 }));
      await useMode.persist.rehydrate();
      expect(useMode.getState().choice).toBe('quick');
    }
  });
});
