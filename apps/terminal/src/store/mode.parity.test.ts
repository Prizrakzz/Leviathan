import { describe, expect, it } from 'vitest';
import { MOCK_MODE_KNOBS, mockRespondStream } from '@/api/mock';
import type { RespondResult } from '@/api/schema';
import { CHOICE_MODE, CHOICES, DARK_TIERS, FE_ASK_MODES, isMode, MODES, modeParam } from './mode';

/**
 * THE SILENT-DROP PIN (D-MW-21), BOTH DIRECTIONS.
 *
 * A depth control is only honest if the tier it shows is the tier that runs. Two ways that breaks, and
 * neither of them produces an error anywhere — the turn just comes back shallower than it was sold:
 *
 *   DIRECTION 1 (client-side): a tier the FE offers whose wire name `modeParam` does not recognise is
 *   DROPPED from the query string, and a mode-less request is resolved to `standard` by the backend's
 *   fail-open. The user selected Analysis and got standard.
 *
 *   DIRECTION 2 (serving-side, and the one that actually bites in production): a tier the FE offers that
 *   serving's GRAPHRAG_MODES allowlist does not contain. The orchestrator intersects the request against
 *   the allowlist and resolves the miss to `standard` — same silent shallower turn, and no client change
 *   can detect it. So the FE roster is pinned against the allowlist this bundle SHIPS AGAINST, and the
 *   env flip that adds those names to GRAPHRAG_MODES is part of the same change (the flip law: an env
 *   flag and the code that reads it are ONE change).
 *
 * The mock lane is pinned with them, because `VITE_MOCK=1` is where this UI is developed: a mock that
 * silently honors `standard` for a tier the real backend honors would reproduce the exact defect inside
 * our own fixtures.
 */

/**
 * The tier names serving's GRAPHRAG_MODES must contain for this bundle to be honest. `standard` is the
 * fail-open passthrough and is always resolvable; the rest is exactly what the notches ask for.
 *
 * THIS CONSTANT IS A MANUAL CONTRACT, NOT AN OBSERVATION (P5 review F8). GRAPHRAG_MODES lives ONLY on the
 * live ECS task definition — nothing in this repo can read it from a test — so what follows can catch an
 * FE-side regression and nothing else. The PRODUCTION direction of this pin is closed at the DEPLOY seam
 * instead: apps/terminal/scripts/deploy.ps1 guard 6/6 reads the DEPLOYED serving revision's
 * GRAPHRAG_MODES and REFUSES to build when any wire name in store/mode.CHOICE_MODE is missing from it.
 * That guard parses the FE roster out of mode.ts, so it cannot fall behind a new notch.
 *
 * IF YOU ADD A NOTCH: this list, the serving env, and the taskdef flip move together or the notch lies.
 */
const SERVING_ALLOWLIST_CONTRACT: readonly string[] = ['quick', 'standard', 'deep'];

describe('roster parity — direction 1: every FE notch survives the transport', () => {
  it('each ask notch has a wire name the transport recognises and forwards UNCHANGED', () => {
    expect(FE_ASK_MODES.length).toBeGreaterThan(0);
    for (const m of FE_ASK_MODES) {
      expect(isMode(m)).toBe(true);
      // The omit branch is what a silent drop looks like from here: `undefined` means "send nothing",
      // and a mode-less turn runs standard.
      expect(modeParam(m)).toBe(m);
    }
  });

  it('the notch -> wire table is total, and only the dossier notch maps to nothing', () => {
    for (const c of CHOICES) {
      const wire = CHOICE_MODE[c];
      if (c === 'deep_research') expect(wire).toBeNull();
      else expect(isMode(wire)).toBe(true);
    }
  });

  it('no notch maps to `standard` any more — the omit-when-default idiom is retired on the ask route', () => {
    // The R7-ratified default-product change: Scan sends `mode=quick` EXPLICITLY. `standard` survives only
    // as the backend's fail-open for a request that carries no mode at all (no-request / API callers).
    expect(Object.values(CHOICE_MODE)).not.toContain('standard');
    expect(FE_ASK_MODES).not.toContain('standard');
  });
});

describe('roster parity — direction 2: the serving allowlist', () => {
  it('every tier this bundle can ask for is one serving is expected to honor', () => {
    for (const m of FE_ASK_MODES) expect(SERVING_ALLOWLIST_CONTRACT).toContain(m);
  });

  it('the DARK tiers are in neither roster — a tier serving honors may still be one we do not offer', () => {
    // The permitted asymmetry, stated: a backend tier absent from the FE roster is fine ONLY when it is
    // listed as deliberately dark. `max`/`max_c0` ship DARK in P5 and never enter the notch roster.
    for (const t of DARK_TIERS) {
      expect(CHOICES as readonly string[]).not.toContain(t);
      expect(MODES as readonly string[]).not.toContain(t);
      expect(SERVING_ALLOWLIST_CONTRACT).not.toContain(t);
      expect(modeParam(t)).toBeUndefined(); // and a corrupt blob carrying one cannot reach the wire
    }
  });
});

describe('roster parity — the mock lane reads the same roster', () => {
  it('MOCK_MODE_KNOBS covers every internal mode, with no invented entries', () => {
    expect(Object.keys(MOCK_MODE_KNOBS).sort()).toEqual([...MODES].sort());
  });

  it('a mock turn HONORS every FE notch instead of quietly resolving it to standard', async () => {
    for (const m of FE_ASK_MODES) {
      let out: RespondResult | undefined;
      await mockRespondStream(
        { question: 'why is corn tight?', asof: '2021-07-20', mode: m },
        { onResult: (r) => (out = r) },
        { delay: 0 },
      );
      const decision = out?.intent_decision?.mode as
        | { requested?: string; honored?: string; invalid?: boolean }
        | undefined;
      expect(decision?.requested).toBe(m);
      expect(decision?.honored).toBe(m);
      expect(decision?.invalid).toBe(false);
    }
  });

  it('an unknown tier is still reported as invalid and honored as standard (the fail-open, unchanged)', async () => {
    let out: RespondResult | undefined;
    await mockRespondStream(
      { question: 'why is corn tight?', asof: '2021-07-20', mode: 'max' },
      { onResult: (r) => (out = r) },
      { delay: 0 },
    );
    const decision = out?.intent_decision?.mode as
      | { requested?: string; honored?: string; invalid?: boolean }
      | undefined;
    expect(decision?.honored).toBe('standard');
    expect(decision?.invalid).toBe(true);
  });
});
