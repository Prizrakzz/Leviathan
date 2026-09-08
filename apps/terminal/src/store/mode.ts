import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * D-AM-14 / D-DR-3 / D-MW-21 / THE CASCADE NOTCH (2026-09-06) — what the ask bar is set to, and the ONE
 * place its wire rule lives.
 *
 * TWO LAYERS, deliberately not one:
 *
 *  1. INTERNAL MODE IDENTIFIERS (`quick`/`standard`/`deep`) — frozen by the D-CC/D-DR/D-MW-22 naming law.
 *     They ride EMF dimensions, trace stamps and every stored baseline; renaming them mid-estate mixes
 *     dashboard populations (the D-AM-11 warning). `ModeName`, `MODES` and `isMode` below are therefore
 *     UNTOUCHED by every relabel this product has been through, including the `standard` passthrough pin
 *     — the backend (leviathan.graphrag.reasoning_modes) still resolves `standard` to an empty knob dict,
 *     and `modeParam` still omits it, so a no-request/API caller keeps byte-identical semantics.
 *
 *     `max` IS NOT ONE OF THEM, and that is a deliberate refusal rather than an oversight: `MODES` is the
 *     roster the MOCK LANE is keyed on (`api/mock.MOCK_MODE_KNOBS: Record<ModeName, ...>`), and Cascade
 *     has no mock fixture and needs none — the notch is blocked in any bundle whose served roster does not
 *     declare it, and a mock bundle declares nothing. What `max` joins instead is `AskMode`, the union of
 *     names this bundle may put on the `mode` param. See `modeParam`.
 *
 *  2. THE NOTCH (`quick` | `deep` | `cascade`, plus the dossier route below) — what a human selects on the
 *     depth control. The RATIFIED LADDER is three stops: **Scan** (the `quick` preset, free), **Analysis**
 *     (the `deep` preset, one credit a turn) and **Cascade** (the `max` preset, TWO credits — the deepest
 *     walk the estate can run: depth 2, up to six seeds, 63 per seed, the writer at `synth_effort=max`).
 *     The owner's word, 2026-09-06: "keep Cascade just as we designed it to be the third place on the
 *     scaler".
 *
 * DEEP RESEARCH IS OFF THE SLIDER (owner's word, same sitting): "add Cascade in place of Deep Research in
 * the scaler, have Deep Research as a standalone button on the right, but it's turned off (lights are off;
 * it says to the user when he hovers that it will be available in Leviathan V1.2)". So `deep_research` is
 * NO LONGER IN `CHOICES` — it cannot be selected, cannot be stepped onto, and cannot be rehydrated out of
 * a stored blob (`isChoice` reads `CHOICES`, and `merge` coerces anything else to the default). What it
 * KEEPS is its `PickerChoice` membership and its rows in the three tables, because Shell's dossier SUBMIT
 * ROUTE (POST /v1/dossier) is unchanged. THE V1.2 RESTORATION IS TWO EDITS, NOT ONE — see `CHOICES`.
 * The serving revision that ships the notch sets `GRAPHRAG_DOSSIER=off`, so the dark button and the
 * backend agree: every dossier route 404s.
 *
 * THE SERVED-ROSTER GATE (and why the Cascade notch is not simply "on"): `max` is still in the backend's
 * `reasoning_modes.DARK_NAMES`, so it is honored ONLY by a deployment whose `GRAPHRAG_MODES` NAMES it
 * (`quick,deep,max` — the wildcard `on` resolves to `serving_names()` and can never sweep a dark preset
 * in). A notch that asked for a tier the deployment does not honor would be resolved to `standard` with no
 * signal at all — the silent-drop trap this file's parity pin exists to prevent — so the notch is
 * SELECTABLE only when `servedModes()` contains `max`, and renders blocked with its reason otherwise.
 *
 * THE GATE ALSO CORRECTS AN EXISTING SELECTION, and until the 2026-09-07 fix pass it did not — which made
 * it a gate on the GESTURE only. `blocked()` fenced `pick`/`step`/`jump`; nothing fenced the value already
 * in the store. MEASURED through the real Shell before the fix (probe, then deleted): with the store at
 * `cascade` and `VITE_MODES=''` the control rendered "Cascade is not yet enabled on this deployment" AND
 * kept `aria-valuetext="Cascade"` AND submitted `mode=max` — the exact silent-shallower-turn the gate
 * exists to prevent, delivered by the gate's own screen. Two live paths reach it: a v3 blob written by a
 * bundle that WAS told `max` (rehydrated by `merge`, which accepts any `CHOICES` member), and a direct
 * `setState`. `servedChoice` below is the coercion that closes it, and it runs on every seam a value can
 * arrive by: the WRITE (`setChoice`), the REHYDRATE (`merge`) and the READ boundary (`DepthControl`'s
 * derived choice and Shell's `askModeFor` call). It only ever moves SHALLOWER, so a correction can never
 * walk a selection UP into a costlier tier.
 *
 * WHAT IT STILL CANNOT SEE, stated because a comment that overclaims here is how the first version got it
 * wrong: `VITE_MODES` is BAKED AT BUILD TIME. A serving rollback that drops `max` from `GRAPHRAG_MODES`
 * does not reach an already-served bundle, which keeps offering the notch until an FE rebuild lands. That
 * window costs no money (`_credit_gate` prices the HONORED tier, and a downgraded turn honors `standard`,
 * price 0) but it is depth-silent, so THE ROLLBACK IS TWO STEPS, not one — see the recipe in
 * `leviathan.graphrag.server` above `_CREDIT_PRICES`.
 *
 * WHAT IS DELIBERATELY *NOT* HERE (the P5 dark-first pin): the backend's preset table carries a whole DARK
 * set. `DARK_TIERS` below is a hand-kept CENSUS of it, so its staleness is a fact a lint can catch rather
 * than something a reader has to notice; the server-side fence itself is `reasoning_modes.serving_names()`.
 *
 * THE RECORDED DEFAULT-PRODUCT CHANGE (R7-ratified, D-MW-21): no notch maps to `standard` any more, so the
 * ask route always sends an explicit `mode` — **Scan** sends `mode=quick`, it does not omit the field. The
 * omit-when-default idiom survives only as `modeParam`'s treatment of a `standard`/absent/unknown input,
 * which is now reachable ONLY by a no-request/API caller. `standard` remains the backend's fail-open for a
 * mode-less request; it is no longer a thing this UI can ask for.
 *
 * The store persists to localStorage `lv-mode` (its own key, not the `lv-ui` blob: a depth choice is not an
 * appearance preference, and a corrupt/foreign value must never take the accent + workspace tabs down with
 * it). BOTH coercions are present on purpose: `migrate` throws away every older-version blob (a stored
 * selection whose PRICE has changed underneath it must never be re-applied silently — v2's roster had no
 * metered notch at all), and `merge` — which runs on EVERY rehydrate, version match or not — coerces
 * anything that is not a current notch back to the default, so a blob written by a newer bundle cannot
 * graft an unknown name onto the store.
 */
export type ModeName = 'quick' | 'standard' | 'deep';

/** Ratified order: shallow -> deep. The INTERNAL roster; `isMode` and the mock lane are its readers. */
export const MODES: readonly ModeName[] = ['quick', 'standard', 'deep'] as const;

/** The passthrough. Never sent by the UI; needs no server flag. Dark from the UI since D-DR-3. */
export const DEFAULT_MODE: ModeName = 'standard';

/** The Cascade tier's WIRE name — a backend preset that is deliberately not an internal `ModeName`. */
export const CASCADE_MODE = 'max' as const;

/**
 * Every wire name this bundle may put on the `mode` param: the internal roster PLUS the dark tiers it has
 * a gated notch for. `modeParam` recognises exactly this union, which is what stops a Cascade submit from
 * being silently dropped into a mode-less (=> `standard`) request.
 */
export type AskMode = ModeName | typeof CASCADE_MODE;

export function isAskMode(v: unknown): v is AskMode {
  return isMode(v) || v === CASCADE_MODE;
}

/**
 * Backend presets this bundle does not offer WITHOUT A GATE. Stated here so the roster-parity pin can
 * assert the absence in BOTH directions — a backend tier missing from the FE roster is fine ONLY when it
 * is listed here as intentional.
 *
 * THIS LIST IS A RECORD, NOT THE FENCE. The fence is server-side and singular:
 * `leviathan.graphrag.reasoning_modes.serving_names()` = `valid_names() - DARK_NAMES`, i.e. what the
 * wildcard allowlist value (`GRAPHRAG_MODES=on`) is allowed to mean. A dark preset is excluded there so
 * that turning modes on estate-wide can never silently honor an un-adjudicated arm.
 *
 * CENSUS AS OF 2026-09-07 (reasoning_modes.DARK_NAMES at HEAD) — 13 names:
 *   `deep_v2`                                    — D-DV, refused (composition binds)
 *   `max`, `max_c0`                              — the P5 2-notch ship's original two. `max` is NOW THE
 *                                                  CASCADE NOTCH's wire name and is still dark: see
 *                                                  `NOTCHED_DARK_TIERS` directly below
 *   `esc`, `esc_r`                               — D-MW-30 escalated SHAPE + its reserve twin
 *   `max_cc1`, `max_cc2`                         — D-MW-28/P6 + T2, max + cross-market cascade slots
 *   `deep_cc1`                                   — T2-2 (CASCADE_HOME plan), `deep` + one cross-market
 *                                                  cascade slot; the T2-3 gate's ON arm
 *   `quick_hp`, `deep_hp`, `esc_hp`, `esc_r_hp`  — the D-HP-26 flip ladder (flag still dark)
 *   `quick_n3`                                   — LANE S, the Scan-tier 3-round numbers budget arm
 *   `quick_s`, `quick_r0`                        — SCAN RUNG 3, the headline-roster arm: the control
 *                                                  twin (Sonnet writer) and the treatment (the
 *                                                  deterministic, model-free numbers leg)
 * `standard` is NOT and cannot be in it (its all-None dict IS the fail-open guarantee).
 *
 * THE CENSUS HAS GONE STALE TWICE AND THIS FILE'S OWN TEST CANNOT CATCH IT (mode.test.ts says so in
 * writing: the assertion compares this list against a literal copy of itself). Since 2026-09-07 the loop
 * IS closed, from the other side: `leviathan.graphrag.config_check.check_cascade_notch` clause (vi) reads
 * THIS list out of THIS file and asserts it equals `reasoning_modes.DARK_NAMES` name-for-name.
 */
export const DARK_TIERS: readonly string[] = [
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
] as const;

/**
 * The dark tiers this bundle DOES have a notch for. The permitted overlap with `DARK_TIERS`, and the
 * whole reason `max` stays in that census: pricing and offering a tier does not un-darken it server-side.
 * `max` is honored only where `GRAPHRAG_MODES` names it, so its notch is gated on `servedModes()` and is
 * blocked — with its reason on screen — everywhere else.
 */
export const NOTCHED_DARK_TIERS: readonly string[] = [CASCADE_MODE] as const;

/**
 * WHAT THIS DEPLOYMENT SERVES, as this bundle was told at build time.
 *
 * Nothing in the browser can read `GRAPHRAG_MODES`: it lives on the serving ECS task definition and there
 * is no `/modes` route and no field on `/healthz` that publishes it (checked 2026-09-07). So the roster is
 * a BUILD-TIME flag, `VITE_MODES`, whose value mirrors the taskdef's — and the deploy guard
 * (apps/terminal/scripts/deploy.ps1 guard 6/6) is what keeps the two honest, because it reads the DEPLOYED
 * revision's `GRAPHRAG_MODES` and refuses to build when a wire name in `CHOICE_MODE` is missing from it.
 *
 * HOW IT IS SUPPLIED AT DEPLOY TIME: `deploy.ps1` sets the other `VITE_*` values itself and does NOT set
 * this one, so the flip's FE step is run with `$env:VITE_MODES = "quick,deep,max"` in the deploying shell
 * (`vite build` inherits it). Forgetting it is SAFE and silent in the right direction — the notch renders
 * blocked rather than selling a turn serving would downgrade — and guard 6/6 makes the reverse mistake
 * impossible by refusing to build this bundle at all until the taskdef names `max`.
 *
 * AND THAT REFUSAL IS A COST THIS COMMIT PAYS UP FRONT, recorded here because it is a BLOCKING consequence
 * rather than free safety (2026-09-07 fix pass; the first version of this note described only the upside).
 * Guard 6/6 PARSES the wire names out of `CHOICE_MODE` — it cannot see this build-time gate, so as far as
 * it is concerned this bundle "can ask for" `max` whether or not `VITE_MODES` names it. SIMULATED against
 * the live serving env (`GRAPHRAG_MODES=quick,deep`): parsed wires `deep,max,quick`, missing `{max}` ->
 * "ALLOWLIST GUARD: serving does NOT honor max ... REFUSING to build". So from this commit until the
 * taskdef flip (step 1), THE VERIFIED FE DEPLOY LANE IS CLOSED FOR EVERY REASON — an unrelated hotfix
 * included — and `-SkipGate` is not an escape worth taking: it also drops typecheck, lint, unit and
 * playwright e2e and stamps the build UNVERIFIED. The two honest ways out are (a) take step 1, or (b)
 * teach guard 6/6 this gate (skip a wire name listed in `NOTCHED_DARK_TIERS` unless `VITE_MODES` names
 * it). THE OWNER PICKED (a) ON 2026-09-07: "the notch ships AVAILABLE -- the flip order is backend env
 * (GRAPHRAG_MODES=quick,deep,max + GRAPHRAG_DOSSIER=off on one serving rev) THEN the FE deploy with
 * VITE_MODES=quick,deep,max". So `deploy.ps1` is NOT taught the gate and stays the thing that enforces the
 * order; the closed-build window is the interval between the two steps, and it is deliberate. The word is
 * recorded in full beside the recipe it governs — `leviathan.graphrag.server`, above `_CREDIT_PRICES`.
 *
 * THE DEFAULT IS THE CONSERVATIVE ONE: absent/empty/`off`, and the wildcard `on` too, all mean the SHIPPED
 * serving roster — `{quick, standard, deep}` — because that is exactly what `GRAPHRAG_MODES=on` resolves
 * to server-side (`serving_names()`, which excludes every dark preset). A build that was told nothing
 * therefore blocks Cascade, which is the direction that cannot mislead: a blocked notch says why, an
 * un-gated one silently returns a `standard` turn the user paid two credits for.
 */
export const SHIPPED_SERVING_MODES: readonly string[] = ['quick', 'standard', 'deep'] as const;

export function servedModes(): readonly string[] {
  let raw = '';
  try {
    raw = String(import.meta.env.VITE_MODES ?? '')
      .trim()
      .toLowerCase();
  } catch {
    raw = ''; // a bundler that never defined it is the same as a build that was told nothing
  }
  if (!raw || raw === 'off' || raw === 'on' || raw === '1' || raw === 'true') return SHIPPED_SERVING_MODES;
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Does this deployment honor that wire name? `standard` always does (it needs no flag). */
export function isModeServed(m: string | null | undefined): boolean {
  const n = (m ?? '').trim().toLowerCase();
  return n === DEFAULT_MODE || servedModes().includes(n);
}

/** Is this notch's tier one the deployment will actually run? The gate the depth control blocks on. */
export function isChoiceServed(c: PickerChoice): boolean {
  const wire = CHOICE_MODE[c];
  return wire === null ? false : isModeServed(wire);
}

/**
 * THE SELECTION THIS DEPLOYMENT CAN ACTUALLY HONOR — the served-roster gate applied to a VALUE rather than
 * to a gesture. Returns `c` when the deployment serves it; otherwise the deepest notch BELOW it that the
 * deployment does serve; otherwise the default.
 *
 * WHY IT ONLY EVER WALKS DOWN. A correction is not a purchase. Coercing UP would move a one-credit
 * selection onto a two-credit tier because a deployment dropped a middle name — spending someone's grant to
 * fix our own roster drift. Walking down can only ever make a turn cheaper and shallower than the one that
 * was selected, and the reason is on screen under the control the whole time (`depth-blocked-*`).
 *
 * THE DOSSIER ROUTE PASSES THROUGH UNTOUCHED: `deep_research` is a ROUTE, not a tier — `CHOICE_MODE` maps
 * it to `null`, it is not on the slider, and its gate is its own flag + monthly allowance, never
 * `GRAPHRAG_MODES`. Coercing it here would silently turn a dossier submit into a turn.
 *
 * NOT A SUBSTITUTE FOR `blocked()`: a CREDIT shortfall must never move a selection (a balance is transient,
 * and the server refuses at the gate with a 429 before a byte streams). This function reads exactly one
 * fact — what this build was told the deployment serves — which is fixed for the life of the bundle.
 *
 * AN OFF-LADDER INPUT RESETS TO THE DEFAULT AND DOES NOT ENTER THE WALK (2026-09-07 fix pass). The first
 * version started the descent at `CHOICES.length - 1` for anything `indexOf` could not place — so a value
 * that is not on the ladder came back as the TOP of it. MEASURED before this line: on
 * `VITE_MODES='quick,deep,max'`, `servedChoice('garbage')`, `servedChoice(undefined)` and
 * `servedChoice(null)` all returned `'cascade'`, i.e. the two-credit tier, which is the exact direction the
 * three doc blocks above (and `Shell`'s call site) swear this function cannot move in. Unreachable through
 * shipped code TODAY — every caller pre-guards with `isChoice` and the parameter is typed — but the
 * `PickerChoice` union is documented above as GROWING in V1.2, and a walk that starts at the top of the
 * ladder for an unplaceable value is a landmine, not a fallback. There is no shallower notch "below"
 * something that is not on the ladder at all, so the answer is the default.
 */
export function servedChoice(c: PickerChoice): PickerChoice {
  if (isDossierChoice(c) || isChoiceServed(c)) return c;
  const from = CHOICES.indexOf(c);
  if (from < 0) return DEFAULT_CHOICE; // not on the ladder: reset, never enter the walk (see above)
  for (let i = from - 1; i >= 0; i -= 1) {
    const x = CHOICES[i];
    if (x && isChoiceServed(x)) return x;
  }
  return DEFAULT_CHOICE;
}

/** Everything the ask bar can be set to. `deep_research` is a SUBMIT ROUTE, not a mode — and, since the
 *  2026-09-06 amendment, not a slider notch either (see `CHOICES` / `DOSSIER_CHOICE`). */
export type PickerChoice = 'quick' | 'deep' | 'cascade' | 'deep_research';

/** THE SLIDER's notches, shallow -> deep. Cascade is the TOP notch and drives the index arithmetic and
 *  the arrow-key traversal. Deep Research is deliberately ABSENT: it is a standalone, disabled control at
 *  the right of the ask bar until Leviathan V1.2.
 *
 *  THE V1.2 RESTORATION IS TWO EDITS, and the first version of this note said one, which would have shipped
 *  a notch nobody could ever select. Putting `deep_research` back in this list is necessary and NOT
 *  sufficient: `DepthControl.blockedReason`'s first clause runs `isChoiceServed`, which is `false` for any
 *  choice whose `CHOICE_MODE` entry is `null` — and the dossier route's entry is `null` BY DESIGN (it is
 *  not an ask mode). Restored on its own, the notch would render "Deep Research is not yet enabled on this
 *  deployment" forever. So the restoration is: (1) this list, and (2) a dossier clause in `blockedReason`
 *  AHEAD of the served-roster clause, gating it on its own flag + monthly allowance (GET /v1/dossier/quota)
 *  the way the pre-2026-09-06 control did. `servedChoice` already passes the route through untouched. */
export const CHOICES: readonly PickerChoice[] = ['quick', 'deep', 'cascade'] as const;

/** The dossier route's choice value — off the slider, kept as the one name Shell's submit branch reads. */
export const DOSSIER_CHOICE: PickerChoice = 'deep_research';

export const DEFAULT_CHOICE: PickerChoice = 'quick';

/**
 * The WIRE name each notch asks at, or `null` for the notch that is not an ask at all. One table, so
 * "the label is Scan, the wire says quick" is stated once and every call site is a lookup, never a literal.
 */
export const CHOICE_MODE: Record<PickerChoice, AskMode | null> = {
  quick: 'quick',
  deep: 'deep',
  cascade: 'max',
  deep_research: null,
};

/**
 * What a turn at this notch COSTS against the monthly credit grant, and it must equal what the server
 * charges (`leviathan.graphrag.server._CREDIT_PRICES`: deep 1, max 2; quick absent = free). Scan is
 * UNMETERED by ratified policy (the default experience is never metered). Deep Research is 0 HERE because
 * it is metered by its own, separate monthly allowance (GET /v1/dossier/quota) — two meters, two badges,
 * deliberately.
 */
export const CHOICE_COST: Record<PickerChoice, number> = { quick: 0, deep: 1, cascade: 2, deep_research: 0 };

/** Does choosing this notch spend a credit? The predicate the control and the copy branch on. */
export function isMetered(c: PickerChoice): boolean {
  return (CHOICE_COST[c] ?? 0) > 0;
}

/** The `mode` value a submit at this notch carries, or `undefined` for the dossier route. */
export function askModeFor(c: PickerChoice): AskMode | undefined {
  return CHOICE_MODE[c] ?? undefined;
}

/**
 * Every wire name this bundle can put on the `mode` param. The serving allowlist (GRAPHRAG_MODES) MUST
 * contain all of them, or the notch that asks for the missing one must be GATED on `servedModes()` (which
 * is how `max` ships): a name the allowlist does not honor is silently resolved to `standard` by the
 * orchestrator, and the user gets a shallower turn than the one they selected with no signal at all.
 * That is the production half of the silent-drop trap, and this constant is what the pin reads.
 */
export const FE_ASK_MODES: readonly AskMode[] = CHOICES.map((c) => CHOICE_MODE[c]).filter(
  (m): m is AskMode => m !== null,
);

/** Static selector copy. Deliberately RELATIVE — no invented milliseconds (the D-AM-13 rule): per-mode p50s
 *  exist only in the EMF `mode` dimension, and a precise number on screen before that is a number nobody
 *  measured. The dossier's "minutes" is the D-DR-1 design envelope (5-20 min, 20-min wall clock), which is a
 *  shape the user must know before spending one of four monthly runs — not a latency claim. A CREDIT PRICE
 *  is not a latency number: it is the exact, measured thing the server will charge. */
export interface ChoiceCopy {
  /** The LABEL a human reads. Internal identifiers never appear on screen. */
  label: string;
  /** The time expectation, one word/phrase, shown next to the label. */
  time: string;
  /** What it does, in terms the desk can check against the trace chip / the artifact it lands in. */
  detail: string;
}

export const CHOICE_COPY: Record<PickerChoice, ChoiceCopy> = {
  quick: {
    label: 'Scan',
    time: 'one turn',
    detail: 'a grounded, cited answer to this question — free, no credit',
  },
  deep: {
    label: 'Analysis',
    time: 'a longer turn',
    detail: 'a wider walk — more drivers, deeper cascade, more evidence weighed; one credit',
  },
  cascade: {
    label: 'Cascade',
    time: 'the longest turn',
    detail: 'the deepest walk — every driver, every hop, the writer at full effort; two credits',
  },
  deep_research: {
    label: 'Deep Research',
    time: 'minutes',
    detail: 'a planned set of sub-questions, delivered as a saved artifact',
  },
};

/** What the dark Deep Research control says on hover, verbatim (owner's word, 2026-09-06). */
export const DEEP_RESEARCH_DARK_TITLE = 'Deep Research will be available in Leviathan V1.2';

export function isMode(v: unknown): v is ModeName {
  return typeof v === 'string' && (MODES as readonly string[]).includes(v);
}

export function isChoice(v: unknown): v is PickerChoice {
  return typeof v === 'string' && (CHOICES as readonly string[]).includes(v);
}

/** Does this selection submit a DOSSIER instead of a turn? The one predicate Shell branches on. */
export function isDossierChoice(v: unknown): boolean {
  return v === DOSSIER_CHOICE;
}

/**
 * The WIRE value for an internal mode: the ask name for a recognised NON-standard tier, `undefined` for
 * everything else (standard, absent, empty, a name from a newer bundle's store blob).
 *
 * `undefined` means OMIT THE FIELD — not send an empty one. Since D-MW-21 no NOTCH can produce `undefined`
 * here (Scan sends `quick` explicitly); what the rule still buys is the byte-identity of a `standard`
 * request for the no-request/API callers that have one, and a hard floor under a corrupted stored value:
 * an unrecognised name is dropped rather than forwarded.
 *
 * THE RECOGNISED SET IS `AskMode`, NOT `ModeName` (2026-09-06): Cascade's wire name is `max`, a preset
 * that is deliberately absent from the internal roster, and a `modeParam` that only knew `ModeName` would
 * DROP it — turning a two-credit selection into a mode-less request the backend fails open to `standard`.
 * That is the client half of the silent-drop trap, so the union this reads and the union `CHOICE_MODE`
 * writes are the same one.
 */
export function modeParam(mode?: string | null): AskMode | undefined {
  return isAskMode(mode) && mode !== DEFAULT_MODE ? mode : undefined;
}

export interface ModeState {
  choice: PickerChoice;
  setChoice: (c: PickerChoice) => void;
}

export const useMode = create<ModeState>()(
  persist(
    (set) => ({
      choice: DEFAULT_CHOICE,
      // Coerced on the way IN as well as on the way out of storage: the store shape may only ever hold a
      // SLIDER notch THIS DEPLOYMENT SERVES, so no consumer needs its own guard. `deep_research` no longer
      // passes this gate — the dossier route is entered by Shell's own branch, never by a selection a user
      // can make. The `servedChoice` half is the 2026-09-07 fix: `DepthControl.pick` already refuses an
      // unserved notch, but that is a fence around ONE call site, and a store whose only guard is at the
      // control is a store the next call site can put `cascade` into on a deployment that would run
      // `standard`. Down-only, so a coercion can never spend more than the selection it replaces.
      setChoice: (c) => set({ choice: servedChoice(isChoice(c) ? c : DEFAULT_CHOICE) }),
    }),
    {
      name: 'lv-mode',
      // v3 (D-MW-21): the roster gains a METERED notch. v1 held `mode` (three internal names), v2 held
      // `choice` over a two-entry, entirely unmetered roster. Neither can be carried forward: a stored
      // selection made when nothing cost anything must not become a standing instruction to spend.
      //
      // THE 2026-09-06 AMENDMENT DOES NOT BUMP IT, and the reason is the version rule itself: no stored
      // value's PRICE moved. `quick` is still free and `deep` is still one credit; Cascade is a NEW name
      // no v3 blob can contain, and `deep_research` — which v3 blobs CAN contain — is no longer a
      // `CHOICES` member, so `merge` already coerces it to Scan on every rehydrate. Bumping would only
      // discard `deep` selections that are still exactly as priced as when they were made.
      version: 3,
      partialize: (s) => ({ choice: s.choice }),
      // Every older blob resolves to the default, explicitly. (Without a migrate, zustand's own
      // version-mismatch path only logs — relying on that would make the "never silently spends" property
      // an accident of a library's internals rather than something this file states.)
      migrate: () => ({ choice: DEFAULT_CHOICE }),
      // THE REHYDRATE SEAM, and the one the 2026-09-07 fix pass had to widen. `isChoice` alone accepts any
      // CHOICES member, so a blob written by a bundle that WAS told `max` — the same user, after a serving
      // rollback or an FE rebuild without VITE_MODES — rehydrated straight back onto `cascade` and asked at
      // a tier this deployment does not honor, with the blocked sentence on screen and no other signal
      // anywhere. `servedChoice` corrects it once, at boot, before anything can read it.
      merge: (persisted, current) => ({
        ...current,
        choice: servedChoice(
          isChoice((persisted as { choice?: unknown } | null)?.choice)
            ? (persisted as { choice: PickerChoice }).choice
            : DEFAULT_CHOICE,
        ),
      }),
    },
  ),
);
