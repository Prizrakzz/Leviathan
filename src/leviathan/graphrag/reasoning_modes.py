"""Reasoning modes (D-AM-9..12) -- the per-turn REASONING-SCALE presets, ONE producer.

A LEAF module by construction, copying `response_contracts.py`'s shape exactly: it imports NOTHING
from leviathan.graphrag (pure data + pure functions), so orchestrator.py, answer.py, server.py and
eval.py can all import it without cycles, and the preset table cannot be hand-copied into a second
module and drift (the COMPAT-9 duplicate-and-pin defect class).

PRESETS -- `quick` / `standard` / `deep`, plus the DARK `deep_v2` / `max` / `max_c0`, the D-MW-30 escalated
pair `esc` / `esc_r`, the D-MW-28 P6 arm `max_cc1`, and the D-HP-8 handle-prose set
`quick_hp` / `deep_hp` / `esc_hp` / `esc_r_hp`. `standard` is ALL-NONE:
`knobs("standard")` is the EMPTY DICT, every kwarg builder returns `{}`, and every call site therefore
stays byte-identical under the omit-when-default idiom. That empty dict IS the fail-open guarantee (the
same role the `default` response contract's empty directive plays), not a promise anyone has to keep by
hand. `deep_v2` is requestable BY NAME (the eval arm) but is excluded from `serving_names()`, so the
wildcard `GRAPHRAG_MODES=on` can never honor it -- it stays dark until the D-DV-2 verdict.

FAIL-OPEN, NEVER A 400: an unknown or absent `mode` resolves to `standard` and stamps
`invalid=True`; a desk turn must not die on a typo. `resolve()` is the ONE place that decides, and
it also applies the honor allowlist -- a mode that is accepted and stamped but NOT in the allowlist
runs `standard` knobs (the DARK stage, D-AM-12).

v1 KNOBS ARE CLASS-1 ONLY -- every one is already an accepted keyword of its callee, so this wave
THREADS values, it does not redesign seams:
  walk      node_budget / depth / max_seeds        -> planner.grounded_subgraph
  ground    k_by_depth / evidence_cap / probe_cap  -> planner.ground
            cap_policy                             -> planner.ground (D-DV-2; None == today's FIFO cap)
  retrieval fetch_k                                -> evidence.retrieve, via a per-call partial rebind
  silver    silver_cap                             -> silverleg.make_silver_lookup(cap=)
  scaffold  scaffold_max_bullets / _max_absence    -> the episode-scaffold caps (params-driven today)
  contract  budget_scale                           -> scales the ACTIVE response contract's word range
  gate      xc_force                               -> the reroute-v2 request gate (force off / force on)
  render    order_policy                           -> answer._render_order (evidence render + flat list)
  walk/seed per_seed_budget / per_seed_reserve     -> planner.grounded_subgraph (D-MW-13; totals =
                                                      value x the REALIZED seed count, not a flat number)
  ground    per_seed_evidence_cap / _probe_cap     -> planner.ground, via `scaled_ground_kwargs()` ONLY
                                                      (the ONE producer of the seed-scaled totals)
  synth     synth_model                            -> answer.answer's DEFAULT-ONLY model branch (D-MW-30,
                                                      F5: mode > env > params; an explicit caller wins)
  render    provenance_prompt                      -> answer._l2_blocks + answer._system (D-MW-30, 30c:
                                                      structural-admission provenance + the INVITATION)
  walk      cascade_contract_slots                 -> planner.grounded_subgraph (D-MW-28/P6: PAID slots
                                                      for foreign contracts the seed CASCADES INTO)
  grammar   handle_prose                           -> answer._system(handles=) + the [E]/[N] render passes
                                                      + the digit-lint CHARGE (D-HP-8, R9: ONE knob for the
                                                      whole bundle; GRAPHRAG_HANDLE_PROSE kills, never enables)

`max` / `max_c0` (D-MW-13, STEP-0-CALIBRATED + RATIFIED 2026-08-11) -- the Full-cascade tier. `max_seeds`
KEEPS its name and becomes the tier seed CEILING (6); the dispatch planner decides the REALIZED cardinality
under it, and every budget scales PER SEED from that realized count: 63 cosine slots/seed (the measured p75
of per-seed above-tau demand) plus 4 DEDICATED reserve slots/seed for graph admission, so cosine and
structural admission can never displace each other. `max_c0` is now byte-identical (12c zeroed both)
-- 0 is a VALUE, not None: it survives `knobs()` and forces the reservation OFF outright (the closure kwarg
beats the env, a shipped pin), which is what makes the P3-A arms differ by exactly ONE variable at identical
width. Both are DARK until P4 adjudicates the bundle; `max_c0` stays dark permanently as the OFF control.

`esc` / `esc_r` (D-MW-30, ratified 12e) -- THE ESCALATED BUNDLE, the max_c0 twin pattern re-used. Width is a
QUESTION SHAPE, not a tier: `deep` is the priced envelope and the dispatch planner escalates an
evidence-hungry <= 2-seed question to the measured max SHAPE inside it. `esc` is therefore deep's identity
for every pre-plan and non-walk knob (F9 -- `max_seeds` STAYS 4: escalation never changes ROUTING, only
width) with the 12e-measured walk/ground width bolted on (per-seed 63/24/24, depth 2, k (7,5,3), score +
relevance) plus the synthesis seat `synth_model='claude-opus-5'` -- the 12e width-deck verdict was max+opus,
so the bundle ships AS MEASURED and is never re-derived. `esc_r` is `esc` plus the reserve BUNDLE:
per_seed_reserve 4 + `provenance_prompt=True`, the
12c reserve retry with the missing half (the writer could not tell a structural node from a cosine one, so the
reserved rows rendered anonymously and were never cited). Both permanently DARK as presets: serving reaches
them ONLY through the escalation seam, which stamps mode_decision.honored=deep + escalation_decision.fired.

`quick_hp` / `deep_hp` / `esc_hp` / `esc_r_hp` (D-HP-8, R9 ratified) -- THE HANDLE-PROSE CONTROL SURFACE, and
the ONE enabling lever of that treatment. Each is CONSTRUCTED from its base preset plus `handle_prose=True`
(`HANDLE_PROSE_PRESETS` below), so the gate arm `deep` vs `deep_hp` differs by exactly ONE variable and cannot
drift the day a base preset is amended. The set is MATCHED because the escalation seam swaps the knob dict
WHOLE: a `deep_hp` turn escalating into `esc` would revert the prompt contract mid-turn while the renderer and
the lint reverted with it (or half-reverted), silently gutting two of the four judged gates. All four are DARK
at birth; `standard` is excluded from the ladder entirely (its empty knob dict IS the fail-open guarantee, and
a field on it would red the passthrough pin). A SERVING FLIP OF `deep_hp` MAY NOT OPEN WHILE
`GRAPHRAG_SHAPE_ESC` IS ON UNLESS `esc_hp` SHIPS WITH IT.

`max_cc1` (D-MW-28, P6) -- `max` + ONE cross-market cascade contract slot, the two-preset arm pattern for the
THIRD time. The P6 gate runs `--mode max` vs `--mode max_cc1`: one variable, identical width, neither arm
constructible by mixing a preset with a kwarg (the kwarg beats the preset OUTRIGHT -- a shipped pin). DARK.

EXCLUDED FROM v1, each with its recorded reason (do NOT add these without a new ratification):
  * rerank pool          -- a module-global read at the slice site; per-request mutation bleeds
                            across the shared threadpool.
  * coalescer window / quiescence -- process singleton; a per-request window re-arms the documented
                            cross-turn quota defect (rankers.py).
  * timeline floors      -- under the artifact-stamp governance fence (timeline.py).
  * recency_days         -- changes which regimes FIRE, i.e. changes FACTS, not depth.
  * synthesis max_tokens -- truncation history; the contract word budget is the length lever.
  * cascade_quant        -- read inside verify.py, so varying it per request moves the strip-rate
                            DEFINITION and makes arms incomparable.
  * the episode/contract FLAGS themselves -- they are the D-RC soak surface.

PIT SAFETY (stated once, for the record -- do not re-derive at the call sites): widening k /
fetch_k / node_budget / evidence and probe caps CANNOT leak post-asof evidence, by construction.
The as-of leakage filter runs BEFORE any width slicing on BOTH evidence backends (evidence.py and
pgstore.py), so a wider read returns MORE of the same already-filtered population, never anything
newer than the turn's horizon. `deep` is therefore PIT-neutral, and `quick` only narrows.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace

QUICK = "quick"
STANDARD = "standard"
DEEP = "deep"
DEEP_V2 = "deep_v2"
MAX = "max"
MAX_C0 = "max_c0"
ESC = "esc"                                   # D-MW-30: the escalated SHAPE (deep's envelope, max's width)
ESC_R = "esc_r"                               # ...plus the reserve bundle (reserve 4 + the provenance prompt)
MAX_CC1 = "max_cc1"                           # D-MW-28 (P6): max + ONE cross-market cascade contract slot
# D-HP-8 (H1, R9): THE MATCHED DARK PRESET SET -- the handle-prose treatment's ONE enabling lever. Four
# names, minted in ONE commit, all four in DARK_NAMES. `standard` is NOT in the set and cannot be (its
# all-None dict IS the fail-open guarantee), and `max`/`max_c0`/`max_cc1` are out of the ladder entirely.
QUICK_HP = "quick_hp"                         # the FIRST tier in the D-HP-26 flip ladder
DEEP_HP = "deep_hp"                           # the second; the reference arm for G1/G2
ESC_HP = "esc_hp"                             # the escalation TARGET a deep_hp turn must reach
ESC_R_HP = "esc_r_hp"                         # ...and the reserve twin (D-HP-25's arm)

# D-MW-13: the TOTAL ceilings the seed-scaled ground caps may never exceed, whatever the realized seed
# count is. They live here (not at a call site) because `scaled_ground_kwargs()` is the ONE producer of
# the scaled totals -- cap arithmetic duplicated at a seam is the COMPAT-9 drift class all over again.
TOTAL_EVIDENCE_CAP = 144
TOTAL_PROBE_CAP = 96


@dataclass(frozen=True)
class Mode:
    """One preset. EVERY knob defaults to None = "leave the callee's own default alone"; the
    all-None `standard` entry is the passthrough pin. `k_by_depth` is a TUPLE so the dataclass stays
    hashable and the table stays immutable (planner's own default is a tuple too)."""
    name: str
    # walk (planner.grounded_subgraph)
    node_budget: int | None = None
    depth: int | None = None
    max_seeds: int | None = None
    # ground (planner.ground)
    k_by_depth: tuple | None = None
    evidence_cap: int | None = None
    probe_cap: int | None = None
    # retrieval (evidence.retrieve, rebound per call)
    fetch_k: int | None = None
    # silver leg (silverleg.make_silver_lookup)
    silver_cap: int | None = None
    # episode-scaffold noise caps
    scaffold_max_bullets: int | None = None
    scaffold_max_absence: int | None = None
    # response-contract word budget multiplier (applied only when a contract is ACTIVE)
    budget_scale: float | None = None
    # reroute-v2 cross-commodity gate: None = leave the flag's decision alone; False = force OFF;
    # True = force ON *where the existing realizability gate already allows it* (the gate still
    # decides; this only lets it be consulted on a turn the flag would have skipped).
    xc_force: bool | None = None
    # D-DV-2 explore-wide-cite-narrow. Both None on every pre-D-DV preset, and None is a PROVEN
    # passthrough at both seams (planner._dedup_and_cap and answer._render_order return the exact
    # pre-wave sequence), so the byte-identity law survives the two new fields.
    #   cap_policy   None = the FIFO evidence cap; "score" = per-node relevance-proportional quota.
    #   order_policy None = walk-order render; "relevance" = (depth,-relevance) REVERSED, strongest
    #                rows nearest the question (attention basin). Consumed in answer.py, NOT a
    #                planner keyword -- so it rides mode_knobs directly, like fetch_k.
    cap_policy: str | None = None
    order_policy: str | None = None
    # D-MW-13 (R7): PER-SEED allocations. `max_seeds` above stops being a flat fan-in number and becomes
    # the tier seed CEILING -- the dispatch planner picks the realized cardinality under it -- and these
    # four scale the walk from that REALIZED count. Appended after order_policy, `per_seed_reserve` LAST
    # (the appended-last law; D-MW-28's cascade_contract_slots moves the tail again in P6).
    #   per_seed_budget       cosine node slots per seed (total = value x realized seeds); when set it
    #                         REPLACES the flat node_budget for that walk.
    #   per_seed_evidence_cap / per_seed_probe_cap  ground caps per seed, totalled and clamped to
    #                         TOTAL_EVIDENCE_CAP / TOTAL_PROBE_CAP by scaled_ground_kwargs() ONLY.
    #   per_seed_reserve      DEDICATED additive graph-admission slots per seed -- never displaced by
    #                         cosine and never backfilled with it. 0 is a VALUE (forces the reservation
    #                         OFF, beating the env); None leaves the shipped env-driven path alone.
    per_seed_budget: int | None = None
    per_seed_evidence_cap: int | None = None
    per_seed_probe_cap: int | None = None
    per_seed_reserve: int | None = None
    # D-MW-30 (F7): the escalated bundle's two fields, appended AFTER per_seed_reserve -- the appended-last
    # law again (D-MW-28's cascade_contract_slots moves this tail a third time in P6). BOTH are None on
    # every other preset, and None is the ONLY correct absent value here: `knobs()` filters `is not None`,
    # so a literal False or "" would MINT the key into deep's trace stamp and break the byte-identity law
    # that the whole mode table rests on.
    #   synth_model        the synthesis writer for THIS turn, consumed at the ONE default-only branch in
    #                      answer.answer (mode > env > params; an explicit caller --model still wins).
    #   provenance_prompt  True = render each structurally-admitted node's admission provenance on its
    #                      evidence header AND append the invitation paragraph to the persona. None
    #                      everywhere else -> both seams are byte-identical (they take `False` defaults).
    synth_model: str | None = None
    provenance_prompt: bool | None = None
    # D-MW-28 (P6): the CROSS-MARKET CASCADE slot count, appended LAST -- the appended-last law, FOURTH
    # application (KNOB_FIELDS order IS the trace-stamp column order; 12f records what a shift costs).
    # N PAID slots for FOREIGN CONTRACTS reached by the seeds' INVERTED inter_commodity edges (the markets
    # a seed cascades INTO), threaded to planner.grounded_subgraph -- Class-1 by this module's own rule.
    # A KNOB AND NOT AN ENV, deliberately: a process-global GRAPHRAG_CASCADE_CONTRACTS re-opens the exact
    # defect that forced the reserve into this table -- every quick/standard turn on the task would pay a
    # ~2.8k-token foreign contract block. None (every shipped preset) == 0 == byte-identical.
    cascade_contract_slots: int | None = None
    # D-HP-8 (H1, R9): THE HANDLE-PROSE GRAMMAR FLAG, appended LAST -- the appended-last law, FIFTH
    # application (KNOB_FIELDS order IS the trace-stamp column order; 12f records what a shift costs).
    # ONE knob gates the WHOLE treatment bundle (B8): the prompt contract (`_system(handles=...)`), the
    # [E]/[N] render passes, and the digit-lint's CHARGE. Two knobs would re-create the
    # GRAPHRAG_VERIFY_ALLNUM hazard PHASE9_B deliberately refused.
    # A KNOB AND NOT AN ENV, and the reason is measured, not stylistic: the escalation seam swaps the knob
    # dict WHOLE (orchestrator.py:2138-2139, "never a merge"), so a process env would leave the PROMPT
    # contract on while the renderer reverted mid-turn -- or half-revert -- on exactly the two judged gates
    # (D-HP-23 rung 2, D-HP-25) that ride escalation. `GRAPHRAG_HANDLE_PROSE` survives as a ONE-WAY KILL
    # only (`handle_prose_arm` / `handle_prose_on` below are the ONE producer of that resolution).
    # None on every non-`_hp` preset, and None is the ONLY correct absent value: `knobs()` filters
    # `is not None`, so a literal False would MINT the key into deep's trace stamp and break the
    # byte-identity law the whole table rests on.
    handle_prose: bool | None = None


MODES: dict[str, Mode] = {m.name: m for m in (
    # D-MW-13 (R7, RATIFIED 2026-08-11): max_seeds 1 -> 2 is a CEILING, not a fan-in raise -- a
    # two-market question on the DEFAULT tier stops being a one-market answer. P4-ARM COMMIT
    # (2026-08-12, after the P3 gates -- plan 12c): per_seed_budget=12, the ratified Scan
    # allocation, replaces the flat node_budget=6 (the walk derives 12 x realized seeds).
    Mode(name=QUICK,
         depth=1, max_seeds=2,
         k_by_depth=(4, 2), evidence_cap=12, probe_cap=12,
         fetch_k=40, silver_cap=4,
         scaffold_max_bullets=6, scaffold_max_absence=3,
         budget_scale=0.7, xc_force=False,
         per_seed_budget=12),
    Mode(name=STANDARD),          # LOAD-BEARING: all-None IS the byte-identical passthrough guarantee
    # D-DV-1: four knobs amended on the FORENSICS, not on taste. fetch_k 120 -> 60: RERANK_POOL is 60 and
    # the pool cut runs AFTER fusion, so at 120 the pool collapsed to ~dense-top-60 and the BM25 leg (the
    # one that doubled exact-token recall) was mechanically OFF -- 120 was strictly harmful. depth 3 -> 1
    # and k_by_depth (7,5,3) -> (7,5): DEAD knobs, measured -- node_budget saturated 36/36 turns inside
    # wave 1 (seed fan-in 21-42 fills it), max depth reached was 1, wave 2 never ran. xc_force True ->
    # None: forcing the reroute-v2 leg widened the [N] namespace and mis-paired indices (number_mismatch
    # 2/2/11, clean dose-response off/flag/forced-on). budget_scale 1.5 -> None: H-verbosity KILLED
    # (realized length ratio 1.14x; the worst-stripped row was SHORTER than its quick twin).
    #
    # D-GD (2026-08-08) -- depth=1 STAYS PINNED, and that is a POSITIVE decision, not an oversight.
    # docs/private/GUIDED_DEPTH_WAVE_PLAN.md's core item (D-GD-1, the cascade-closure reservation) lives
    # entirely in WAVE-1 ADMISSION: the schema forces every driver parent to be a driver of the SAME
    # contract and the walk enqueues every driver of a contract into wave 1, so the seed cascade's depth-2
    # set is provably empty (measured 0 new keys in 33 of 33 DAGs at any budget -- dgd-walk-admission.md
    # V1). Un-pinning `depth` here would buy the reservation nothing and would reverse D-DV-1's measured
    # verdict for no reason. The reservation is flagged separately (GRAPHRAG_CLOSURE_RESERVE) and is NOT a
    # mode knob in v1: it is the A/B's single variable, so it must not ride a preset that also moves
    # node_budget / caps / fetch_k.
    # D-MW-13 (R7): max_seeds 3 -> 4 = deep's tier CEILING. P4-ARM COMMIT (2026-08-12, plan 12c):
    # per_seed_budget=32, the ratified Analysis allocation, replaces the flat node_budget=16.
    Mode(name=DEEP,
         depth=1, max_seeds=4,
         k_by_depth=(7, 5), evidence_cap=48, probe_cap=36,
         fetch_k=60, silver_cap=12,
         scaffold_max_bullets=12, scaffold_max_absence=6,   # == today's params default
         budget_scale=None, xc_force=None,
         per_seed_budget=32),
    # D-DV-2 THE ARM: explore WIDE (same 16-node walk, same 3 seeds), cite NARROW (cap 48 -> 24) and
    # spend that narrower cap by relevance rather than by arrival order, with the strongest rows rendered
    # last. Everything else is deep's, so the A/B moves the cap policy + the order + the cap size only.
    # DARK: excluded from serving_names(), eval-only until the D-DV-2 verdict.
    Mode(name=DEEP_V2,
         node_budget=16, depth=1, max_seeds=3,
         k_by_depth=(7, 5), evidence_cap=24, probe_cap=36,
         fetch_k=60, silver_cap=8,
         cap_policy="score", order_policy="relevance"),
    # D-MW-13 THE FULL-CASCADE TIER (STEP-0-CALIBRATED 2026-08-11: per-seed cosine demand p75 = 63,
    # eligible-ancestor demand p75 = 4). node_budget / evidence_cap / probe_cap stay None ON PURPOSE --
    # they are DERIVED from the realized seed count at walk/ground time, so a flat number pinned here
    # would silently win over the per-seed arithmetic. depth=2 buys hop DRIVERS only (the walk fences
    # contract expansion at d >= 2). DARK until P4.
    Mode(name=MAX,
         depth=2, max_seeds=6,
         k_by_depth=(7, 5, 3),
         fetch_k=60, silver_cap=12,
         scaffold_max_bullets=12, scaffold_max_absence=6,
         cap_policy="score", order_policy="relevance",
         # per_seed_reserve 4 -> 0: THE P3 GATE TERMINATION (plan 12c, 2026-08-12). P3-A: 0/8 live
         # rows cited a reserved node, both runs; P3-B: the reserve cost strip 1.17x/1.31x at
         # identical width. Reservation ships OFF, no fix cycle (D-GD-3 discipline); re-open paths
         # are D-MW-17's token budget and D-HP. The admission MACHINERY stays built and dark.
         per_seed_budget=63, per_seed_evidence_cap=24, per_seed_probe_cap=24, per_seed_reserve=0),
    # THE P3 OFF CONTROL, retained as the historical arm identity (P3 artifacts stamp honored=max_c0).
    # Since the 12c termination zeroed max's own reserve the two presets are now BYTE-IDENTICAL except
    # name; max_c0 stays permanently dark and is NEVER the shipped tier.
    Mode(name=MAX_C0,
         depth=2, max_seeds=6,
         k_by_depth=(7, 5, 3),
         fetch_k=60, silver_cap=12,
         scaffold_max_bullets=12, scaffold_max_absence=6,
         cap_policy="score", order_policy="relevance",
         per_seed_budget=63, per_seed_evidence_cap=24, per_seed_probe_cap=24, per_seed_reserve=0),
    # ── D-MW-30 THE ESCALATED BUNDLE (ratified 12e, 2026-08-12) ─────────────────────────────────────────
    # `esc` = DEEP's identity + the 12e-measured max SHAPE. Every pre-plan knob (silver_cap, max_seeds,
    # xc_force) and every non-walk knob (fetch_k, scaffold caps, budget_scale) is DEEP's VALUE, not max's --
    # F9: those three are consumed BEFORE the plan exists (orchestrator :1845/:1871/:2032), so an escalation
    # that moved them would change the turn's ROUTING and pre-plan shape, not its width, and the arm would
    # measure two variables. `max_seeds` therefore STAYS 4: escalation buys DEPTH OF EVIDENCE on a <= 2-seed
    # question, never a wider fan-in. Only the width quartet + the two policies + depth/k_by_depth + the two
    # new fields differ from deep, and that difference IS the bundle under test.
    # node_budget / evidence_cap / probe_cap stay None for max's reason, restated because it matters MORE
    # here (deep carries FLAT 48/36): they are DERIVED from the realized seed count by scaled_ground_kwargs,
    # so inheriting deep's flat numbers would put a stale pair in the trace stamp beside the per-seed values
    # that actually ran -- an artifact that lies about the arm. The per-seed quartet REPLACES them.
    # synth_model rides the bundle because 12e measured the bundle: the width-deck verdict (usefulness 5/6,
    # composition 5/6, strips 0.023-0.027) was max+OPUS, and the writer-alone leg was already measured flat
    # (12e's lift read), so the bundle ships as measured and a bundle win attributes to WIDTH (F13).
    Mode(name=ESC,
         depth=2, max_seeds=4,
         k_by_depth=(7, 5, 3),
         fetch_k=60, silver_cap=12,
         scaffold_max_bullets=12, scaffold_max_absence=6,
         budget_scale=None, xc_force=None,
         cap_policy="score", order_policy="relevance",
         # 0 is a VALUE (the max_c0 lesson): it survives knobs() and forces the reservation OFF outright,
         # so the esc arm cannot silently run the ON mechanism because GRAPHRAG_CLOSURE_RESERVE was set.
         per_seed_budget=63, per_seed_evidence_cap=24, per_seed_probe_cap=24, per_seed_reserve=0,
         synth_model="claude-opus-5"),
    # `esc_r` = `esc` + the RESERVE BUNDLE, one variable in the D-MW-30 arm-B sense: per_seed_reserve 4
    # (12c's dedicated graph-admission slots, re-opened) AND the provenance rendering + invitation that
    # P3-A lacked. The two ride TOGETHER on purpose -- 12e's finding was that admission works and citation
    # does not follow when the writer cannot tell a structural node from a cosine one, so re-testing the
    # reserve without the provenance half would re-run a measurement that already returned its verdict.
    # Every other field is esc's, byte-for-byte (the pin below proves it).
    Mode(name=ESC_R,
         depth=2, max_seeds=4,
         k_by_depth=(7, 5, 3),
         fetch_k=60, silver_cap=12,
         scaffold_max_bullets=12, scaffold_max_absence=6,
         budget_scale=None, xc_force=None,
         cap_policy="score", order_policy="relevance",
         per_seed_budget=63, per_seed_evidence_cap=24, per_seed_probe_cap=24, per_seed_reserve=4,
         synth_model="claude-opus-5", provenance_prompt=True),
    # ── D-MW-28 THE P6 ON-ARM (2026-08-12) ──────────────────────────────────────────────────────────────
    # `max_cc1` = `max`'s EXACT fields + one cascade-contract slot. The D-MW-13 two-preset arm pattern,
    # third application (max/max_c0, esc/esc_r, max/max_cc1): the P6 gate's arms are `--mode max` vs
    # `--mode max_cc1`, so they differ by EXACTLY ONE variable and neither arm can be built by mixing a
    # preset with a kwarg (the kwarg beats the preset outright -- a shipped pin -- which is what made
    # "max with the mechanism off" unconstructible from one preset in the first place).
    # `max` carries None, NOT 0: 0 is the value that would MINT the key into max's trace stamp and move
    # the OFF arm's artifact, and None is what every other shipped preset carries here.
    # RERANK CHUNK ARITHMETIC, RE-CHECKED AGAINST THE NEW BOUND (D-MW-11/D-MW-9): fetch_k 60 and
    # rankers._COALESCE_MAX_DOCS 1000 pack 16 WHOLE nodes per request, and the ceiling is now
    # 63 x seeds + 1. At every realized cardinality the request count is UNCHANGED --
    # 63/126/189/252/315/378 -> 4/8/12/16/20/24 requests, and +1 node changes none of them (no capacity
    # width is a multiple of 16; the residues are 15/14/13/12/11/10). A realized fill that lands exactly
    # on a multiple of 16 costs ONE more concurrent request on a 1,000 req/min lane -- a request-shape
    # detail, not a quota event. The plan's "33-34 x 60 = still 2 chunks" was written at the 32-node
    # framing; under whole-node packing 33-34 is 3 chunks, and the P6 delta is 0-or-1 either way.
    # DARK at birth, like every arm this wave has minted.
    Mode(name=MAX_CC1,
         depth=2, max_seeds=6,
         k_by_depth=(7, 5, 3),
         fetch_k=60, silver_cap=12,
         scaffold_max_bullets=12, scaffold_max_absence=6,
         cap_policy="score", order_policy="relevance",
         per_seed_budget=63, per_seed_evidence_cap=24, per_seed_probe_cap=24, per_seed_reserve=0,
         cascade_contract_slots=1),
)}

# ── D-HP-8 THE MATCHED DARK PRESET SET (H1, R9 ratified) ────────────────────────────────────────────────
# base name -> `_hp` twin. THE ONE PRODUCER of the pairing: every consumer that must follow a turn from a
# base preset to its handle-prose twin (or back) reads this table instead of retyping a name -- the
# escalation target, the census mandate set, the credit price and the eval arm stamp are all the same join.
HANDLE_PROSE_PRESETS: dict[str, str] = {QUICK: QUICK_HP, DEEP: DEEP_HP, ESC: ESC_HP, ESC_R: ESC_R_HP}
_HP_BASE_OF: dict[str, str] = {hp: base for base, hp in HANDLE_PROSE_PRESETS.items()}

# THE TWINS ARE CONSTRUCTED FROM THEIR BASE, NOT HAND-COPIED, and that is a correctness decision rather
# than a brevity one. D-HP's gate arms are `deep` vs `deep_hp` at ONE variable; a copied field table makes
# the arm silently TWO-variable the day anyone amends `deep` (the COMPAT-9 duplicate-and-drift class, which
# is the reason this module exists at all). `dataclasses.replace` on the frozen preset gives
# "byte-for-byte its base plus `handle_prose=True`" BY CONSTRUCTION -- there is nothing left to promise,
# and the pins below assert the property rather than re-listing the values.
MODES.update({hp: replace(MODES[base], name=hp, handle_prose=True)
              for base, hp in HANDLE_PROSE_PRESETS.items()})

# Presets that `GRAPHRAG_MODES=on` must NOT sweep into the honored set. A dark preset is still resolvable
# by NAME (GRAPHRAG_MODES=deep_v2 for the eval arm), which is what keeps the flip a one-env-var decision.
# D-MW-30 (F8): esc / esc_r join the dark set IN THE SAME COMMIT that mints them. A forgotten entry here
# would make the escalated bundle WILDCARD-HONORABLE -- i.e. `GRAPHRAG_MODES=on` would serve an UNMETERED
# max-width + opus turn to anyone who typed the name. serving_names() is unchanged by this, and the pin on
# that fact (test_dam_modes:101) is the leak fence.
# D-MW-28 (P6): max_cc1 joins in the SAME commit that mints it, for the same reason -- a forgotten entry
# makes an un-adjudicated arm wildcard-honorable. serving_names() is UNCHANGED by this, and the pin on
# that fact is the leak fence.
# D-HP-8 (R9): ALL FOUR `_hp` twins join in the SAME commit that mints them -- the F8 leak fence, fifth
# application, and here it is the whole control surface. `quick_hp`/`deep_hp` are the flip ladder's own
# rungs (D-HP-26), so a forgotten entry would serve UNGATED handle-only prose -- number-free sentences
# with the figures still unspliced -- to anyone who typed the name before G1 has run. THE ROLLBACK IS THE
# SAME ONE ENV VALUE for all four: drop the name from GRAPHRAG_MODES and the tier falls back to its base
# preset, byte-identical OFF, no rebuild.
DARK_NAMES: frozenset = frozenset({DEEP_V2, MAX, MAX_C0, ESC, ESC_R, MAX_CC1,
                                   QUICK_HP, DEEP_HP, ESC_HP, ESC_R_HP})

# The knob field names, in declaration order (the trace-stamp column order; append, never sort).
KNOB_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(Mode) if f.name != "name")

_WALK_KNOBS = ("node_budget", "depth", "max_seeds", "per_seed_budget", "per_seed_reserve",
               "cascade_contract_slots")
_GROUND_KNOBS = ("k_by_depth", "evidence_cap", "probe_cap", "cap_policy")


def valid_names() -> frozenset:
    """Every name `resolve()` accepts -- dark presets included (they are stamped, and honorable when the
    allowlist names them explicitly)."""
    return frozenset(MODES)


def serving_names() -> frozenset:
    """What the WILDCARD allowlist value ('on') is allowed to mean. A dark preset is deliberately not in
    here: turning modes on estate-wide must never silently honor an un-adjudicated arm."""
    return valid_names() - DARK_NAMES


def resolve(requested: str | None, allowed) -> dict:
    """THE one resolution. Returns the stamp `{requested, honored, invalid}`:

      * `requested` -- the normalized name the caller asked for (None when absent).
      * `invalid`   -- True iff a non-empty request named no known mode (the `mode_invalid` stamp).
      * `honored`   -- the mode whose knobs actually run. `standard` always (it needs no flag and
        changes nothing); any other mode only when it is in `allowed`, else `standard`.

    `allowed` is the caller's already-parsed allowlist (the env read lives at the orchestrator seam;
    this module reads no environment). Never raises, never returns an unknown name."""
    req = (requested or "").strip().lower() or None
    invalid = bool(req) and req not in MODES
    name = req if (req and not invalid) else STANDARD
    honored = name if (name == STANDARD or name in (allowed or ())) else STANDARD
    return {"requested": req, "honored": honored, "invalid": invalid}


def get(name: str | None) -> Mode:
    """The preset, `standard` for None/unknown (fail-open, same as resolve())."""
    return MODES.get((name or "").strip().lower(), MODES[STANDARD])


def knobs(name: str | None) -> dict:
    """The RESOLVED non-None knob values for a mode -- {} for standard/None/unknown.

    This dict is what the orchestrator threads DOWN as one argument and stamps on the trace, so the
    "what depth ran" chip and the eval artifact read exactly the values the engines received. Empty
    => every kwarg builder below is empty => every call site is byte-identical."""
    m = get(name)
    return {k: getattr(m, k) for k in KNOB_FIELDS if getattr(m, k) is not None}


# ── D-HP-8: THE HANDLE-PROSE CONTROL SURFACE (R9) ───────────────────────────────────────────────────────
# The kill switch's accepted OFF spellings. `GRAPHRAG_HANDLE_PROSE` is a ONE-WAY KILL: it can force the
# treatment off from any preset, and it can NEVER turn it on. The env READ stays at the caller (this module
# reads no environment -- the `resolve(allowed=...)` idiom), so the value is threaded in, never fetched.
HANDLE_PROSE_KILL_VALUES: frozenset = frozenset({"off", "0", "false", "kill"})


def _hp_killed(kill_env: str | None) -> bool:
    return str(kill_env or "").strip().lower() in HANDLE_PROSE_KILL_VALUES


# ── D-HP H1 FIX Z9: THE TWO ROLLBACK LANES BELONG TO THE ONE PRODUCER ────────────────────────────────
# Section 2's MUTUAL-EXCLUSION law says handle-prose is IGNORED on a turn whose renderer cannot honour it:
# `GRAPHRAG_VERIFY=off` (every handle pass runs inside `if verifier.get("enabled")`) and
# `GRAPHRAG_MENTOR_VOICE=off` (`answer._system` returns the LEGACY persona, which carries neither the
# menu's vocabulary nor the four spans the contract supersedes). Those two reads used to live ONLY in
# `answer._handle_prose_active`, so `eval._handle_prose_arm` -- the artifact's join key for D-HP-19's
# bridge run and for every arm-vs-control comparison -- stamped "on" for turns on which the treatment
# PROVABLY did not run. An artifact that NAMES AN ARM THAT DID NOT RUN is strictly worse than one that
# names none, so the lanes move HERE, beside the kill switch, and both seams call the same function.
# THE LEAF STILL READS NO ENVIRONMENT (the `resolve(allowed=...)` idiom): the VALUES are threaded in.
# An omitted lane argument means "this lane is not engaged", so every pre-Z9 two-argument caller is
# byte-identical -- the lanes can only ever turn the treatment OFF, never on.
# THE SPELLING IS THE CALLERS' OWN, EXACTLY: `verify.py:890` and `_system` both test `== "off"` against a
# value defaulted to "on", so a lane is engaged iff the string IS "off". No strip, no case-fold -- a
# looser test here would silently widen a documented rollback lane that two other modules read narrowly.
def _hp_lane_off(env_value: str | None) -> bool:
    return env_value is not None and str(env_value) == "off"


def _hp_lanes_open(verify_env: str | None, mentor_env: str | None) -> bool:
    """True when NEITHER rollback lane is engaged -- i.e. the renderer can honour the contract."""
    return not (_hp_lane_off(verify_env) or _hp_lane_off(mentor_env))


def handle_prose_variant(name: str | None) -> str | None:
    """The `_hp` twin of a base preset, or None when there is none (`standard`, `max`, an unknown name,
    or an `_hp` name itself). The escalation seam's target selection is exactly this lookup."""
    return HANDLE_PROSE_PRESETS.get((name or "").strip().lower())


def base_mode(name: str | None) -> str:
    """The BASE preset behind a name: `deep_hp` -> `deep`, and every other name unchanged (including
    unknown ones -- fail-open, same as `resolve`/`get`).

    THE CONSUMERS THAT NEED THIS ARE NOT OPTIONAL, and each is a live defect if it retypes the join
    instead: the escalation gate's tier test (`honored != DEEP` would suppress every `deep_hp` turn with
    reason `tier`, i.e. `esc_hp` would be UNREACHABLE and D-HP-23 rung 2 would measure nothing), the
    composition-census mandate set (an `esc_hp` arm without the mandates its `esc` control ran is a
    two-variable arm), and the credit price (a `deep_hp` turn priced by name alone bills 0)."""
    n = (name or "").strip().lower()
    return _HP_BASE_OF.get(n, n)


def handle_prose_on(kn: dict | None, kill_env: str | None = None) -> bool:
    """THE SEAM BOOLEAN: does handle-prose run on this turn? True iff the RESOLVED knob dict carries
    `handle_prose` True and the kill switch is not set. ONE producer for the prompt contract, the [E]/[N]
    render passes and the digit-lint CHARGE -- the bundle rule (B8) is that they cannot disagree.

    The argument is the KNOB DICT, never a mode name, because the knob dict is what the escalation seam
    swaps WHOLE (orchestrator.py:2138-2139): a seam that re-derived the flag from the honored name would
    keep the prompt contract on through an escalation that reverted the renderer.

    THE ROLLBACK LANES ARE NOT READ HERE, deliberately: this answers "is the treatment SELECTED", which is
    what `answer._handle_prose_on` has always meant. `handle_prose_active` answers "may it RUN"."""
    if _hp_killed(kill_env):
        return False
    return bool((kn or {}).get("handle_prose"))


def handle_prose_active(kn: dict | None, kill_env: str | None = None, *,
                        verify_env: str | None = None, mentor_env: str | None = None) -> bool:
    """`handle_prose_on` AND the two ROLLBACK LANES -- the FULL verdict, and the ONE producer of it.

    `answer._handle_prose_active` is a thin wrapper that supplies the two env values; `eval` reads the
    same function for its arm stamp. A lane added on one side therefore cannot exist on the other, which
    is the H0 defect (`eval` naming an arm that did not run) reopened once already by the second lane."""
    if not handle_prose_on(kn, kill_env):
        return False
    return _hp_lanes_open(verify_env, mentor_env)


def handle_prose_arm(kn: dict | None, kill_env: str | None = None, *,
                     verify_env: str | None = None, mentor_env: str | None = None) -> str | None:
    """THE ARM STAMP for an artifact header: `"on"` | `"off"` | None (the wave's control surface is not
    on this image / no preset declared it). NEVER stamps "on" for an env value: an artifact that NAMES AN
    ARM THAT DID NOT RUN is strictly worse than one that names none, and this is the join key D-HP-19's
    bridge run rides.

    H1 FIX Z9 -- THE STAMP READS THE FULL VERDICT, NOT JUST THE KNOB AND THE KILL. A preset that declares
    the knob on a turn whose `GRAPHRAG_VERIFY`/`GRAPHRAG_MENTOR_VOICE` rollback lane is engaged stamps
    "off": the treatment was selected and did NOT run, which is exactly what a killed run stamps and for
    the same reason. The None case is unchanged and still means "nothing turned it on and nothing killed
    it" -- a control row, and a lane engaged on a control row still stamps None, because no arm was ever
    selected there to be reported off."""
    if _hp_killed(kill_env):
        return "off"
    if not bool((kn or {}).get("handle_prose")):
        return None
    return "on" if _hp_lanes_open(verify_env, mentor_env) else "off"


def walk_kwargs(kn: dict | None) -> dict:
    """`planner.grounded_subgraph` kwargs present in `kn` ({} when standard/absent)."""
    return {k: kn[k] for k in _WALK_KNOBS if kn and kn.get(k) is not None}


def ground_kwargs(kn: dict | None) -> dict:
    """`planner.ground` kwargs present in `kn` ({} when standard/absent)."""
    return {k: kn[k] for k in _GROUND_KNOBS if kn and kn.get(k) is not None}


def scaled_ground_kwargs(kn: dict | None, n_seeds: int) -> dict:
    """`ground_kwargs()` with the D-MW-13 SEED-SCALED caps folded in -- the ONE producer of that
    arithmetic (no call site multiplies or clamps anything itself).

    Identical to `ground_kwargs(kn)` whenever the per-seed fields are absent, which is every pre-D-MW
    preset -- so quick / standard / deep / deep_v2 stay byte-identical here by construction, not by
    promise. When they ARE present the totals are `per_seed_* x n_seeds`, clamped to
    TOTAL_EVIDENCE_CAP / TOTAL_PROBE_CAP; the per-seed value WINS over any flat evidence_cap/probe_cap
    a preset might also carry (the preset that scales must not be half-scaled).

    `n_seeds` is the REALIZED seed count, not the ceiling. It is floored at 1: a walk that somehow
    reports zero seeds must fall back to a one-seed allocation, never to a cap of 0 (that would ground
    the turn with no evidence at all -- fail-open is this module's law)."""
    out = ground_kwargs(kn)
    if not kn:
        return out
    n = max(1, int(n_seeds or 0))
    per_ev = kn.get("per_seed_evidence_cap")
    if per_ev is not None:
        out["evidence_cap"] = min(int(per_ev) * n, TOTAL_EVIDENCE_CAP)
    per_probe = kn.get("per_seed_probe_cap")
    if per_probe is not None:
        out["probe_cap"] = min(int(per_probe) * n, TOTAL_PROBE_CAP)
    return out


def scale_budget(budget: str | None, scale: float | None) -> str | None:
    """Scale a response contract's word-range phrase ('150-220' -> '110-150' at x0.7), rounding each
    end HALF-UP to the nearest 10 (deterministic: Python's round() is banker's rounding, which would
    make 105 -> 100 and the arithmetic un-reproducible across ends).

    Returns None when there is nothing to do (no scale, no budget, or a phrase that is not the
    `lo-hi` shape) -- the caller then leaves the contract's own budget untouched. Fail-open: this
    function never raises and never widens a range to zero (floor 10, and hi >= lo always)."""
    if not budget or not scale:
        return None
    parts = str(budget).split("-")
    if len(parts) != 2:
        return None
    try:
        lo, hi = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None
    def _r(v: float) -> int:
        return max(10, (int(v) + 5) // 10 * 10)
    slo, shi = _r(lo * scale), _r(hi * scale)
    return f"{slo}-{max(slo, shi)}"
