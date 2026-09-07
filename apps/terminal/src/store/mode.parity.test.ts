import { afterEach, describe, expect, it, vi } from 'vitest';
import { MOCK_MODE_KNOBS, mockRespondStream } from '@/api/mock';
import type { RespondResult } from '@/api/schema';
import {
  CASCADE_MODE,
  CHOICE_MODE,
  CHOICES,
  DARK_TIERS,
  DOSSIER_CHOICE,
  FE_ASK_MODES,
  isAskMode,
  isChoiceServed,
  isMode,
  MODES,
  modeParam,
  NOTCHED_DARK_TIERS,
} from './mode';

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
 *   can detect it.
 *
 * THE CASCADE NOTCH (2026-09-06) IS THE FIRST TIER TO SHIP WITH DIRECTION 2 OPEN, deliberately: `max` is
 * a DARK backend preset (`reasoning_modes.DARK_NAMES`), honored only where GRAPHRAG_MODES NAMES it, and
 * the notch ships before that env flip. So the answer is not "pin it into the allowlist contract" — it is
 * a GATE: `isChoiceServed` blocks the notch in any build not told the deployment honors `max`, and the
 * user sees the reason instead of a downgraded turn. Both halves are pinned below.
 *
 * A GATE ON THE GESTURE IS NOT A GATE (2026-09-07). The first version blocked `pick`/`step`/`jump` and left
 * the STORED value alone, so a rehydrated `cascade` submitted `mode=max` under the very sentence saying the
 * deployment does not run it — direction 2, reopened by the fix for direction 2. `servedChoice` is the
 * coercion that closes it on all three seams (write, rehydrate, read); mode.test.ts holds its properties
 * and Shell.dossier.test.tsx holds the wire pin.
 *
 * The mock lane is pinned with them, because `VITE_MOCK=1` is where this UI is developed: a mock that
 * silently honors `standard` for a tier the real backend honors would reproduce the exact defect inside
 * our own fixtures.
 */

/**
 * The tier names serving's GRAPHRAG_MODES contains TODAY, and that this bundle may therefore ask for
 * UNGATED. `standard` is the fail-open passthrough and is always resolvable.
 *
 * THIS CONSTANT IS A MANUAL CONTRACT, NOT AN OBSERVATION (P5 review F8). GRAPHRAG_MODES lives ONLY on the
 * live ECS task definition — nothing in this repo can read it from a test — so what follows can catch an
 * FE-side regression and nothing else. The PRODUCTION direction of this pin is closed at the DEPLOY seam
 * instead: apps/terminal/scripts/deploy.ps1 guard 6/6 reads the DEPLOYED serving revision's
 * GRAPHRAG_MODES and REFUSES to build when any wire name in store/mode.CHOICE_MODE is missing from it.
 * That guard parses the FE roster out of mode.ts, so it cannot fall behind a new notch.
 *
 * IF YOU ADD A NOTCH: this list, the serving env, and the taskdef flip move together, or the notch is
 * GATED on `servedModes()` until they do. Cascade is the second kind.
 *
 * AND THE SECOND KIND HAS A PRICE THE GUARD DOES NOT KNOW ABOUT, recorded 2026-09-07: guard 6/6 parses the
 * wire names out of `CHOICE_MODE` and cannot see the FE's build-time `VITE_MODES` gate, so it treats this
 * bundle as one that asks for `max` unconditionally. Against today's live `GRAPHRAG_MODES=quick,deep` it
 * therefore REFUSES every terminal FE build — hotfixes included — until the taskdef flip lands. That is a
 * blocking consequence of shipping this notch dark, not a benefit of it. SETTLED BY THE OWNER'S WORD
 * (2026-09-07, 'available, not dark'): the flip is taken -- one serving revision carries
 * GRAPHRAG_MODES=quick,deep,max + GRAPHRAG_DOSSIER=off, THEN the FE build runs with
 * VITE_MODES=quick,deep,max (deploy.ps1 -Modes; guard 7 refuses a build that omits a notch). The guard
 * is deliberately NOT taught the build-time gate: it stays the thing that enforces the order. Full
 * record: server.py's flip comment beside `_CREDIT_PRICES`.
 */
const SERVING_ALLOWLIST_CONTRACT: readonly string[] = ['quick', 'standard', 'deep'];

describe('roster parity — direction 1: every FE notch survives the transport', () => {
  it('each ask notch has a wire name the transport recognises and forwards UNCHANGED', () => {
    expect(FE_ASK_MODES.length).toBeGreaterThan(0);
    for (const m of FE_ASK_MODES) {
      // `isAskMode`, not `isMode`: Cascade's wire name is a preset deliberately absent from the internal
      // roster, and `modeParam` reads the wider union for exactly that reason.
      expect(isAskMode(m)).toBe(true);
      // The omit branch is what a silent drop looks like from here: `undefined` means "send nothing",
      // and a mode-less turn runs standard.
      expect(modeParam(m)).toBe(m);
    }
  });

  it('the notch -> wire table is total, and only the dossier route maps to nothing', () => {
    for (const c of CHOICES) expect(isAskMode(CHOICE_MODE[c])).toBe(true);
    expect(CHOICE_MODE[DOSSIER_CHOICE]).toBeNull();
  });

  it('no notch maps to `standard` any more — the omit-when-default idiom is retired on the ask route', () => {
    // The R7-ratified default-product change: Scan sends `mode=quick` EXPLICITLY. `standard` survives only
    // as the backend's fail-open for a request that carries no mode at all (no-request / API callers).
    expect(Object.values(CHOICE_MODE)).not.toContain('standard');
    expect(FE_ASK_MODES).not.toContain('standard');
  });
});

describe('roster parity — direction 2: the serving allowlist', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('every ungated tier this bundle asks for is one serving is expected to honor', () => {
    for (const m of FE_ASK_MODES) {
      if ((NOTCHED_DARK_TIERS as readonly string[]).includes(m)) continue; // gated, see the next case
      expect(SERVING_ALLOWLIST_CONTRACT).toContain(m);
    }
  });

  it('the GATED tier is exactly `max`, and it is unreachable unless the build was told otherwise', () => {
    expect([...NOTCHED_DARK_TIERS]).toEqual([CASCADE_MODE]);
    expect(SERVING_ALLOWLIST_CONTRACT).not.toContain(CASCADE_MODE); // still dark on today's serving rev
    vi.stubEnv('VITE_MODES', '');
    expect(isChoiceServed('cascade')).toBe(false); // -> the control renders it blocked, with the reason
    vi.stubEnv('VITE_MODES', 'quick,deep,max'); // the flip: the taskdef NAMES the dark preset
    expect(isChoiceServed('cascade')).toBe(true);
  });

  it('the DARK tiers this bundle does NOT notch are in neither roster', () => {
    // The permitted asymmetry, stated: a backend tier absent from the FE roster is fine ONLY when it is
    // listed as deliberately dark. The ONE exception is `max`, which has a gated notch and is pinned
    // above; every other dark name is unreachable from this bundle by construction.
    for (const t of DARK_TIERS) {
      if ((NOTCHED_DARK_TIERS as readonly string[]).includes(t)) continue;
      expect(CHOICES as readonly string[]).not.toContain(t);
      expect(MODES as readonly string[]).not.toContain(t);
      expect(SERVING_ALLOWLIST_CONTRACT).not.toContain(t);
      expect(modeParam(t)).toBeUndefined(); // and a corrupt blob carrying one cannot reach the wire
    }
    // `max` differs in exactly one of those four: it CAN reach the wire, because a Cascade submit must.
    expect(CHOICES as readonly string[]).not.toContain(CASCADE_MODE);
    expect(MODES as readonly string[]).not.toContain(CASCADE_MODE);
    expect(modeParam(CASCADE_MODE)).toBe(CASCADE_MODE);
  });
});

describe('roster parity — the mock lane reads the same roster', () => {
  it('MOCK_MODE_KNOBS covers every internal mode, with no invented entries', () => {
    expect(Object.keys(MOCK_MODE_KNOBS).sort()).toEqual([...MODES].sort());
  });

  it('a mock turn HONORS every FE notch the mock lane has a fixture for', async () => {
    for (const m of FE_ASK_MODES) {
      if (!isMode(m)) continue; // `max` has no mock fixture -- see the case below for why that is safe
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

  it('the mock lane has no Cascade fixture, and a mock build must not declare one', async () => {
    // THE HONEST STATE OF THIS SEAM, written down rather than papered over. `MOCK_MODE_KNOBS` is keyed on
    // `ModeName`, which `max` deliberately is not (see store/mode's header), so a mock turn asked at `max`
    // reports invalid + honored `standard` -- the fail-open, unchanged. That is SAFE because the Cascade
    // notch is gated on `servedModes()` and a mock build (VITE_MOCK=1, VITE_MODES unset) never declares
    // `max`; setting VITE_MODES=...,max on a MOCK build is the one combination that would reproduce the
    // silent-drop trap inside our own fixtures, and it is not a combination anything ships.
    let out: RespondResult | undefined;
    await mockRespondStream(
      { question: 'why is corn tight?', asof: '2021-07-20', mode: CASCADE_MODE },
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
