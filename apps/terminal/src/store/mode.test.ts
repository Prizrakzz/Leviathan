import { beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_MODE, isMode, MODE_COPY, MODES, modeParam, useMode, type ModeName } from './mode';

const stored = () => JSON.parse(localStorage.getItem('lv-mode') ?? '{}') as { state?: { mode?: string } };

describe('mode store (D-AM-14)', () => {
  beforeEach(() => {
    localStorage.clear();
    useMode.setState({ mode: DEFAULT_MODE });
  });

  it('is exactly the three ratified names, in depth order, defaulting to standard', () => {
    expect([...MODES]).toEqual(['quick', 'standard', 'deep']);
    expect(DEFAULT_MODE).toBe('standard');
    expect(useMode.getState().mode).toBe('standard');
  });

  it('every mode carries selector copy, and none of it invents a latency number', () => {
    for (const m of MODES) {
      expect(MODE_COPY[m].time.length).toBeGreaterThan(0);
      expect(MODE_COPY[m].detail.length).toBeGreaterThan(0);
      // D-AM-14 is explicit: static v1 copy is RELATIVE. No "12s"/"1200ms" until the EMF `mode`
      // dimension has real traffic behind it.
      expect(`${MODE_COPY[m].time} ${MODE_COPY[m].detail}`).not.toMatch(/\d+\s*(ms|sec|s\b)/i);
    }
  });

  it('setMode coerces anything that is not a known mode back to standard', () => {
    useMode.getState().setMode('deep');
    expect(useMode.getState().mode).toBe('deep');
    useMode.getState().setMode('ultra' as ModeName);
    expect(useMode.getState().mode).toBe('standard');
  });

  it('isMode is the guard the rest of the app leans on', () => {
    expect(isMode('quick')).toBe(true);
    expect(isMode('deep')).toBe(true);
    expect(isMode('standard')).toBe(true);
    expect(isMode('ultra')).toBe(false);
    expect(isMode('')).toBe(false);
    expect(isMode(undefined)).toBe(false);
    expect(isMode(null)).toBe(false);
    expect(isMode(3)).toBe(false);
  });
});

// The single rule that keeps a standard turn's request byte-identical to the pre-wave one.
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
    // change a request. The control only ever produces lowercase, so nothing normalises case here.
    expect(modeParam('ultra')).toBeUndefined();
    expect(modeParam('DEEP')).toBeUndefined();
    expect(modeParam(' deep ')).toBeUndefined();
  });
});

describe('mode persistence (localStorage lv-mode)', () => {
  beforeEach(() => {
    localStorage.clear();
    useMode.setState({ mode: DEFAULT_MODE });
  });

  it('a choice survives into localStorage under its own key', () => {
    useMode.getState().setMode('deep');
    expect(stored().state?.mode).toBe('deep');
    expect(localStorage.getItem('lv-ui')).toBeNull(); // its own key -- never grafted onto the ui blob
  });

  it('rehydrates a stored choice', async () => {
    localStorage.setItem('lv-mode', JSON.stringify({ state: { mode: 'quick' }, version: 1 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().mode).toBe('quick');
  });

  it('a foreign/corrupt stored value rehydrates to standard, not onto the store shape', async () => {
    // `merge` (not `migrate`) does this on PURPOSE: at the current version a migrate never runs, so a
    // blob written by a newer bundle -- or hand-edited -- would otherwise graft an unknown name straight
    // into the store and out onto the wire.
    localStorage.setItem('lv-mode', JSON.stringify({ state: { mode: 'ultra' }, version: 1 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().mode).toBe('standard');

    localStorage.setItem('lv-mode', JSON.stringify({ state: {}, version: 1 }));
    await useMode.persist.rehydrate();
    expect(useMode.getState().mode).toBe('standard');
  });
});
