"""D-MW-15 STEP-0 -- THE CALIBRATION CENSUS. $0 LLM, offline, runs BEFORE anything else in P3 is built.

[R7-FINAL, 2026-08-11] THIS TOOL IS A CALIBRATION, NOT A FORK DECISION. It was authored against the
pre-R7 shape (flat node_budget 32 / flat max_seeds 3) and the >=50% headroom-vs-displacement fork,
and RETROFITTED same-day when R7 dissolved that fork mid-build. Under R7 the reservation fires into
its OWN per-seed reserve slots (D-MW-15 (i) DEDICATED-SLOT FIRING), additive by construction, so
"does headroom exist" is no longer a question anything is decided on. What IS decided on is HOW BIG
the two per-seed allocations must be. That is what this census now measures.

THE TWO HEADLINE QUANTITIES, both PER-SEED and both STRATIFIED BY REALIZED SEED COUNT:

  (A) PER-SEED COSINE DEMAND -- tau-surviving candidates admitted per seed under an EFFECTIVELY
      UNCAPPED budget, so tau is the only filter and the number is DEMAND, not supply-under-a-cap.
      This is the distribution `per_seed_budget` (provisional 12) must cover. Measured on the
      `demand` arm (node_budget = --demand-budget, default 999).

  (B) PER-SEED RESERVE DEMAND -- eligible (BACKED and SLICE-DISTINCT) ancestors per seed, with the
      probe's own cap raised out of the way and an explicit `eligible_capped` flag whenever it still
      bound. This is the distribution `per_seed_reserve` (provisional 3) must cover. Measured on the
      `at_knobs` arm, NOT on the uncapped one, and that choice is load-bearing: eligibility is
      SLICE-DISTINCT against the slices the walk already covers (planner.py:260-263), so an uncapped
      walk carries a far larger `covered` set and would systematically UNDERSTATE reserve demand.
      The at-knobs arm reproduces the covered-set context the shipped reservation will actually see.
      The uncapped arm's reserve reading is printed BESIDE it so the two can never diverge silently.

PRE-COMMITTED CALIBRATION RULE (module constants, not flags -- a threshold relaxable from the command
line after the numbers are in was never pre-committed):
      per_seed_budget  = max(12, p75 of the per-seed cosine demand distribution)
      per_seed_reserve = max(3,  p75 of the per-seed reserve demand distribution)
  and if a p75 exceeds 2x its provisional (24 / 6) the run prints a RATIFICATION FLAG -- a cost-surface
  change is the user's call. THE TOOL NEVER AUTO-RAISES A KNOB; it prints the rule's outcome.

THE ARMS (`--arms`, default `demand,at_knobs`; every arm walks the SAME population):
  demand    node_budget = 999           -- (A). Budget cannot bind; tau is the only filter.
  at_knobs  node_budget = 12 x n_seeds  -- (B) + the per-invocation headroom diagnostic in the one
            frame where a budget actually binds. THE HONEST LIMIT, STATED: the shipped planner takes a
            FLAT node_budget, so what is emulated here is the per-seed COSINE allocation. R7's ADDITIVE
            per-seed reserve (12 + 3 per seed, neither able to displace the other) is not constructible
            in the shipped walk; nothing is ever reserved in this census anyway (the hook returns None),
            so what the arm buys is the correct `covered` set, not a correct total node count.
  flat      node_budget = --node-budget (32) -- the PRE-R7 CONTINUITY CONTROL against the prior 288-walk
            census. OFF by default. Every number it produces is a pre-R7-shape diagnostic and is
            labelled as such: the max preset no longer has a flat 32-node budget for it to measure.

RETIRED WITH THE FORK: the >=50%-of-walks-headroom-positive decision line, DECISION_STANDS /
DECISION_DISPLACE, and `decide()`. Per-invocation headroom survives as a RECORDED DIAGNOSTIC (D-MW-15
STEP-0 [R7-FINAL]) and is still computed the round-3 way -- `node_budget - (len(kept) + len(base))` at
each wave boundary where the reservation would be invoked, a walk positive iff ANY invocation was --
never the end-of-walk number, which is reported separately as the saturation/substitution reading.

THE INSTRUMENT DESIGN, AND WHY IT IS THE LEAST INVASIVE ONE (justify-or-do-not-do-it) -- UNCHANGED by
R7 and verified sound by census review round 1.
`_closure_plan` is invoked only when `reserve_left > 0` (planner.py:489), so a walk with the
reservation genuinely OFF never reaches the seam and there is no call-side state to read. Three
designs were considered:
  (a) monkeypatch `_closure_reserve_n` -> 0: kills the invocation entirely; the per-wave numbers
      would have to be RE-DERIVED by replaying the trace, which means re-implementing the wave loop,
      the tau prune and the admission sort outside the planner -- the exact duplicate-and-drift
      defect class this estate has refused before.
  (b) an additive census-only stamp inside planner.py: permitted by the task, but it puts census
      code in the serving walk for a one-shot decision instrument.
  (c) ADOPTED -- pass `closure_reserve=N` so the gate OPENS, and replace `_closure_plan` with a
      recording wrapper that reads the exact call-side state the real mechanism would see and
      RETURNS None. `None` is the planner's own documented contract for "nothing was reserved", and
      the caller then runs "the SHIPPED admission verbatim ... the whole of the byte-identity
      guarantee for the OFF arm" (planner.py:203-206). So the walk under measurement IS the OFF
      walk: zero planner.py change, no re-derivation, and the claim is PROVEN per run by paired
      control walks (`--parity-sample`) that re-run with the hook removed and `closure_reserve=0`
      and compare kept / pruned / seeds / visited exactly.
Two fences make (c) non-fragile: a SIGNATURE-PARITY refusal (the wrapper's parameter list is pinned
against `inspect.signature(planner._closure_plan)`; drift refuses the run rather than measuring
something else -- the D-DR stub-lied-signature lesson), and an INSTRUMENT-DEAD refusal (zero
invocations across a whole arm is an abort, never a 0.0% finding).

ELIGIBILITY IS MEASURED BY THE REAL FUNCTION, ON A PROBE CALL. The wrapper calls the UNPATCHED
`_closure_plan` with `scored = base` and an INFLATED `node_budget` (len(kept)+len(base)+slack).
That is not a different measurement: with `scored` already truncated to `base`, step (1) rebuilds
the identical `base`/`base_keys`, `covered` is identical, and the anchor loop walks the identical
rank order -- but headroom is now large, so `need == 0`, nothing is displaced and the plan can
never be TRIMMED to empty. Trimming is why the natural read (`plan is not None`) is not a valid
eligibility test: a wave with zero headroom and no displaceable driver returns None even when
eligible ancestors existed (planner.py:324-328), conflating scarcity with saturation. The probe's
`relevance`/`tau_exempt` fields are DISCARDED (with `scored = base`, a budget-dropped tau survivor is
rebuilt off the tau tombstone, so those two fields would be mislabeled); the census records only ids,
anchors, contracts and chain depths, which the truncation cannot move.

SEED ATTRIBUTION. Both headline quantities are PER SEED, and a walk's kept set contains nodes owned by
non-seed contracts (a tracked hop's own drivers). Every kept node is therefore rolled up to the SEED
whose expansion reached it, through the hop chain the walk itself recorded (`via_edge['_from']`,
planner.py:520-524). Exact at depth 2 by construction. The plan's literal per-CONTRACT grouping is
published beside it, unrolled, so the two groupings are both readable and the calibration says which
one the rule read (the per-seed one -- `per_seed_budget` is multiplied by the REALIZED SEED COUNT to
form the walk's cosine budget, so the demand it must cover is a seed's whole subtree).

THE EMBEDDER IS THE WHOLE REASON THIS CENSUS EXISTS. The D-GD R1 sweep ran a deterministic HASH
embedder, which centres mechanism cosines on 0.0, put 100% of candidates below tau, and reported
"0 of 198 walks ever FILLED node_budget" -- a property of the fake embedder, not of the walk
(GUIDED_DEPTH_V2_PLAN.md:141-170). So: the real bge-m3 through the walk's own `ev.embed` path, and
a NON-OVERRIDABLE preflight probe that refuses any embedder whose geometry is degenerate
(cos(near-synonyms) must clear a floor, vectors must be non-trivial dimension). There is no flag
that turns that fence off.

POPULATION -- mirrors the prior 288-walk routed-deck census (GUIDED_DEPTH_V2_PLAN.md:100-108): the
unique questions across `configs/graphrag/eval_queries*.yaml`, routed with TIER-1 LEXICAL
`answer.route` (deterministic, offline, $0), keeping those that route to >= 1 contract. At HEAD that
is 327 unique / 288 routed. THE ROUTER CAP IS NOW THE R7 CEILING, --max-seeds 6 (was 3): multi-market
deck rows must express full cardinality or the per-seed distributions are measured on a truncated seed
set. `--router semantic` adds the tier-2 bge fallback at k = max_seeds (still $0 LLM); tier-3
`route_llm` is NEVER called -- it costs money and it is not deterministic, and a census whose
population moves between runs is not a census.

BINDING INSTRUMENT REQUIREMENTS (census review round 1, findings 2-6; plan D-MW-15 STEP-0 [R7-FINAL]):
  2. per-seed aggregates are PUBLISHED on every walk row, computed BEFORE the underscore-pop, so a
     completed run's JSON answers the calibration question by RE-READ, never by a second full pass.
  3. every summary block is emitted POOLED and STRATIFIED by n_seeds (the deck is 117/48/123 at
     ceiling 3 -- pooling three structurally different populations makes a seed-mix statistic).
  4. --hop-fence defaults ON (D-MW-13 ships the fence with the preset on BOTH P3-A arms); `off` is
     the sensitivity arm.
  5. base-arithmetic health is PRINTED (N/M boundaries exact) and carries a pre-committed exactness
     floor -- the mirror's invariant is one-sided and passes exactly the drift direction that
     manufactures headroom.
  6. NO calibration line on a truncated run: `--limit`, or fewer than MIN_POPULATION routed walks,
     prints an explicit NO VERDICT line instead (the P3-A instrument-dead-gate precedent).

Exit codes: 0 = census ran; 1 = a usage/config refusal; 2 = INSTRUMENT ABORT (signature drift, a
parity mismatch, a failed eligibility probe, zero invocations, or unexplained base-arithmetic drift)
-- a mixture is never reported as a measurement; 3 = --self-test failed.
ASCII-only stdout (cp1252 console).

Usage:
    python scripts/graphrag/headroom_census.py --self-test
    python scripts/graphrag/headroom_census.py --limit 20 --json .tmp/headroom_dev.json
    python scripts/graphrag/headroom_census.py --json out/headroom_census.json
    python scripts/graphrag/headroom_census.py --arms demand,at_knobs,flat --json out/full.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import inspect
import json
import math
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CFG = _REPO_ROOT / "configs" / "graphrag"

# ---- PRE-COMMITTED (module constants, not flags) ------------------------------------------------
# R7's provisional per-seed allocations (D-MW-13 R7-AMENDED). The census CALIBRATES these; it never
# rewrites them.
PROVISIONAL_PER_SEED_BUDGET = 12
PROVISIONAL_PER_SEED_RESERVE = 3
CALIBRATION_PCT = 0.75           # "set to cover >= p75 of the demand distribution"
RATIFICATION_MULTIPLE = 2.0      # p75 above this x provisional -> RATIFICATION FLAG, never an auto-raise
MIN_POPULATION = 100             # finding 6: below this the run prints NO VERDICT, not a calibration
BASE_ARITH_EXACT_FLOOR = 0.90    # finding 5: below this, every inexact boundary must be EXPLAINED

# R7 walk knobs. seed_ceiling replaces the retired flat max_seeds; the flat node_budget survives only
# as the `flat` continuity-control arm's knob.
DEFAULT_SEED_CEILING = 6         # the `max` tier ceiling (quick 2 / deep 4 / max 6)
DEFAULT_DEMAND_BUDGET = 999      # "effectively uncapped": tau is the only filter
DEFAULT_FLAT_BUDGET = 32         # PRE-R7 SHAPE -- continuity control only
DEFAULT_DEPTH = 2
DEFAULT_RESERVE_N = 3            # closure_reserve: opens the invocation gate (nothing is ever reserved)
DEFAULT_PROBE_N = 128            # eligibility probe cap, raised out of the way; `eligible_capped` flags it
DEFAULT_PARITY_SAMPLE = 12
_PROBE_SLACK = 8                 # probe headroom = probe_n + this, so `need` is always 0

ARMS = ("demand", "at_knobs", "flat")
DEFAULT_ARMS = ("demand", "at_knobs")
_ARM_NOTE = {
    "demand": "node_budget=%d (effectively uncapped; tau is the only filter) -- SIZES per_seed_budget",
    "at_knobs": "node_budget=%d x realized seeds (per-seed cosine alloc) -- SIZES per_seed_reserve",
    "flat": "node_budget=%d flat -- PRE-R7 SHAPE, continuity control against the prior census only",
}

# The call-side signature the wrapper stands in for. Drift = refuse (never measure something else).
#
# RE-PINNED 2026-08-16 (suite-debt sweep) to the 13-parameter v2 signature. THE FENCE WORKED: it
# refused rather than crashed. The four trailing names -- slots_by_origin / origin_of_contract /
# score_of / n_charged -- are ADMISSION V2, added by commit d952c09f ("feat(dmw): P3 -- seed-scaled
# max preset (63+4, DARK) + router de-cap + named-anchor law + graph admission v2 + gate
# instruments") on 2026-08-11 at 23:07. This census script was created by b24187c3 the SAME DAY at
# 15:36 and pinned the then-current 9; the planner widened 7.5 hours later and the script was never
# re-pinned. It has had exactly one commit in its life, so this is its first update.
#
# Re-pinning alone is NOT sufficient and must not be done alone: planner.py:924-932 passes all four
# unconditionally, so a re-pinned fence with the OLD wrapper turns SystemExit into
# `TypeError: _wrapper() got an unexpected keyword argument 'slots_by_origin'`. The wrapper below is
# widened in the same change, which is the whole point of the fence -- it predicted exactly that crash.
_CLOSURE_PLAN_PARAMS = ("scored", "kept", "graph", "node_budget", "reserve_n", "backed",
                        "slice_of_driver", "wave_pruned", "protect_ids",
                        "slots_by_origin", "origin_of_contract", "score_of", "n_charged")

# Embedder preflight: near-synonym pairs that a real semantic embedder must place close together and
# a hash embedder cannot. Floors are deliberately loose -- this is a DEGENERACY fence, not a quality
# gate; bge-m3 scores these ~0.75-0.90.
_EMBED_PROBE_PAIRS = (("corn", "maize"), ("drought", "dry weather"))
_EMBED_COS_FLOOR = 0.45
_EMBED_MIN_DIM = 64


# ==========================================================================================
# PURE ARITHMETIC -- no leviathan imports, exercised by --self-test and the unit test.
# ==========================================================================================
def base_admissions(scored, n_kept: int, node_budget: int) -> list:
    """What the SHIPPED admission rule admits from this wave, in rank order.

    EXACT MIRROR of planner._closure_plan step (1) (planner.py:375-383) and, by construction, of the
    walk's own admission loop (planner.py:556-565): a d==0 seed is admitted by fiat, a d>0 candidate
    only while the running node count is under budget. `scored` entries are the planner's 8-tuples
    (is_hop, rel, id, kind, contract, depth, via, key); only [5] (depth) is read here.

    Kept as a mirror rather than a call into the planner because the planner has no seam that
    returns `base` alone -- and the mirror is cross-checked at runtime against the walk itself:
    kept_before(i+1) >= kept_before(i) + len(base(i)) must hold for every consecutive pair of
    invocations, with equality whenever no un-instrumented wave sat between them."""
    base, n = [], n_kept
    for e in scored:
        if e[5] > 0 and n >= node_budget:
            continue
        base.append(e)
        n += 1
    return base


def headroom(n_kept: int, n_base: int, node_budget: int) -> int:
    """The per-invocation headroom DIAGNOSTIC, planner.py:309 verbatim: the slots this wave leaves
    unspent. Under R7 this no longer selects a payment mode (the reservation has dedicated slots); it
    is recorded because a wave that leaves the cosine allocation unspent is still a real fact about
    the walk. Clamped at 0 exactly as the planner clamps it."""
    return max(0, node_budget - (n_kept + n_base))


def _pct(vals: list, q: float) -> float:
    """Nearest-rank percentile on an already-sorted list (no numpy: this file is a leaf)."""
    if not vals:
        return 0.0
    k = max(0, min(len(vals) - 1, int(math.ceil(q * len(vals))) - 1))
    return vals[k]


def distribution(vals: list) -> dict:
    """min/p25/median/p75/p90/max + mean + a full integer histogram. Histogram not buckets: a
    calibration that reads p75 must let the reader see the tail it is truncating."""
    s = sorted(vals)
    hist: dict = {}
    for v in s:
        hist[str(v)] = hist.get(str(v), 0) + 1
    n = len(s)
    return {"n": n,
            "min": s[0] if n else None, "p25": _pct(s, 0.25) if n else None,
            "median": _pct(s, 0.50) if n else None, "p75": _pct(s, 0.75) if n else None,
            "p90": _pct(s, 0.90) if n else None,
            "max": s[-1] if n else None,
            "mean": round(sum(s) / n, 3) if n else None,
            "positive": sum(1 for v in s if v > 0),
            "positive_frac": round(sum(1 for v in s if v > 0) / n, 4) if n else None,
            "histogram": hist}


def coverage_pct(vals: list, knob: int) -> int:
    """"per_seed_budget=12 covers pNN of demand": the percentile of the demand distribution the
    provisional knob sits at, i.e. the share of demand units it fully serves."""
    if not vals:
        return 0
    return int(round(100.0 * sum(1 for v in vals if v <= knob) / len(vals)))


def calibrate_knob(vals: list, provisional: int) -> dict:
    """THE PRE-COMMITTED RULE, for ONE knob: cover >= p75 of demand, FLOORED at the provisional; a p75
    above RATIFICATION_MULTIPLE x provisional is a user decision (cost surface), never an auto-raise."""
    p75 = int(_pct(sorted(vals), CALIBRATION_PCT)) if vals else 0
    return {"n_demand_units": len(vals),
            "provisional": provisional,
            "p75_demand": p75,
            "coverage_pct_at_provisional": coverage_pct(vals, provisional),
            "calibrated": max(provisional, p75),
            "ratification_threshold": int(RATIFICATION_MULTIPLE * provisional),
            "ratification_flag": bool(p75 > RATIFICATION_MULTIPLE * provisional)}


def calibrate(cosine_demand: list, reserve_demand: list) -> dict:
    """The census's headline output. Two knobs, one rule, both read off PER-SEED demand."""
    return {
        "rule": ("per_seed_* = max(provisional, p%d of the per-seed demand distribution); "
                 "p%d above %.0fx the provisional is a RATIFICATION FLAG, never an auto-raise"
                 % (int(CALIBRATION_PCT * 100), int(CALIBRATION_PCT * 100), RATIFICATION_MULTIPLE)),
        "per_seed_budget": calibrate_knob(cosine_demand, PROVISIONAL_PER_SEED_BUDGET),
        "per_seed_reserve": calibrate_knob(reserve_demand, PROVISIONAL_PER_SEED_RESERVE),
        "sources": {"per_seed_budget": "demand arm (uncapped): per-seed cosine demand",
                    "per_seed_reserve": "at_knobs arm: per-seed eligible-ancestor demand, probe uncapped"},
    }


def cross_tab(rows: list) -> dict:
    """Walk-level 2x2: per-invocation headroom (the diagnostic axis) x eligible ancestors (the scarcity
    axis). A never-firing mechanism has a DIFFERENT fix in each cell, which is the whole point of
    reporting them jointly instead of as two marginals."""
    out = {"headroom_pos__ancestors_pos": 0, "headroom_pos__ancestors_zero": 0,
           "headroom_zero__ancestors_pos": 0, "headroom_zero__ancestors_zero": 0}
    for r in rows:
        h = "headroom_pos" if r["headroom_positive"] else "headroom_zero"
        a = "ancestors_pos" if r["eligible_any"] else "ancestors_zero"
        out["%s__%s" % (h, a)] += 1
    return out


def cross_tab_3way(rows: list) -> dict:
    """The same two axes crossed with END-OF-WALK headroom, so the substitution question
    ("did the walk saturate anyway?") is readable per cell without re-deriving it."""
    out: dict = {}
    for r in rows:
        k = "%s|%s|%s" % ("headroom_pos" if r["headroom_positive"] else "headroom_zero",
                          "ancestors_pos" if r["eligible_any"] else "ancestors_zero",
                          "eow_pos" if r["end_of_walk_headroom"] > 0 else "eow_zero")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def demand_values(rows: list, field: str) -> list:
    """Flatten a per-walk {group: count} map into ONE demand unit per (walk, group). Groups with zero
    demand are present in the maps by construction (every seed is seeded at 0), so an instrument-dead
    seed is a 0 in the distribution -- 'declared not lost', never dropped (D-MW-15 (i))."""
    return [v for r in rows for v in (r.get(field) or {}).values()]


def summary_block(rows: list) -> dict:
    """Every published aggregate for ONE population (pooled, or one n_seeds stratum)."""
    n = len(rows)
    inv_headroom = [h for r in rows for h in r["headroom_by_invocation"]]
    eow = [r["end_of_walk_headroom"] for r in rows]
    hp = sum(1 for r in rows if r["headroom_positive"])
    el = sum(1 for r in rows if r["eligible_any"])
    fire = sum(1 for r in rows if r["can_fire"])
    filled = sum(1 for r in rows if r["kept"] >= r["node_budget"])
    sat = sum(1 for r in rows if r["seed_scaled_saturated"])
    cap = sum(1 for r in rows if r["eligible_capped"])
    return {
        "n_walks": n,
        # ---- (A) + (B): THE CALIBRATION INPUTS ----
        "per_seed_cosine_demand": distribution(demand_values(rows, "per_seed_kept")),
        "per_contract_cosine_demand": distribution(demand_values(rows, "per_contract_kept")),
        "per_seed_reserve_demand": distribution(demand_values(rows, "per_seed_eligible")),
        "per_contract_reserve_demand": distribution(demand_values(rows, "per_contract_eligible")),
        "eligible_capped_walks": cap,
        "eligible_capped_frac": round(cap / n, 4) if n else 0.0,
        # ---- walk shape ----
        "kept_distribution": distribution([r["kept"] for r in rows]),
        "unattributed_kept": sum(r["unattributed_kept"] for r in rows),
        # Retrofit-review finding 3: attribution loss silently DEFLATES the per-seed p75 the
        # rule reads (a node dropped from the rollup vanishes from the calibration input while
        # the per-contract grouping still counts it) -- so it is an instrument-health number,
        # aggregated here and PRINTED on the arm's instrument line.
        "unattributed_eligible": sum(r.get("unattributed_eligible", 0) for r in rows),
        "total_kept": sum(r["kept"] for r in rows),
        "total_eligible": sum(r.get("n_eligible", 0) for r in rows),
        "seed_scaled_saturated_walks": sat,      # kept >= 12 x n_seeds: would the provisional bind?
        "seed_scaled_saturated_frac": round(sat / n, 4) if n else 0.0,
        # ---- recorded diagnostics (the retired fork's quantities) ----
        "per_wave_headroom_distribution": distribution(inv_headroom),
        "headroom_positive_walks": hp,
        "headroom_positive_frac": round(hp / n, 4) if n else 0.0,
        "end_of_walk_distribution": distribution(eow),
        "end_of_walk_positive_walks": sum(1 for v in eow if v > 0),
        "end_of_walk_positive_frac": round(sum(1 for v in eow if v > 0) / n, 4) if n else 0.0,
        "filled_budget_walks": filled,
        "filled_budget_frac": round(filled / n, 4) if n else 0.0,
        "eligible_ancestor_walks": el,
        "eligible_ancestor_frac": round(el / n, 4) if n else 0.0,
        "can_fire_walks": fire,                  # headroom>0 AND >=1 eligible, SAME invocation
        "can_fire_frac": round(fire / n, 4) if n else 0.0,
        "cross_tab": cross_tab(rows),
        "cross_tab_3way": cross_tab_3way(rows),
    }


def summarize(rows: list) -> dict:
    """POOLED **and** STRATIFIED BY REALIZED SEED COUNT (finding 3). Wave-1 candidate supply scales
    with the seed count while free slots shrink with it, so a pooled fraction is a seed-mix statistic;
    and `per_seed_budget` is a PER-SEED quantity, which is the presentation the calibration needs."""
    strata: dict = {}
    for r in rows:
        strata.setdefault(r["n_seeds"], []).append(r)
    return {"n_walks": len(rows),
            "n_seeds_histogram": {str(k): len(v) for k, v in sorted(strata.items())},
            "pooled": summary_block(rows),
            "by_n_seeds": {str(k): summary_block(v) for k, v in sorted(strata.items())}}


# ==========================================================================================
# SEED ATTRIBUTION -- every per-seed number in this file is produced here.
# ==========================================================================================
def seed_root_map(nodes, seeds) -> dict:
    """contract -> the SEED whose expansion reached it (None when unattributable).

    Built from the walk's OWN record: a tracked hop's contract node carries
    `via_edge['_from'] = the contract that enqueued it` (planner.py:520-524). At depth 2 the chain is
    at most seed -> hop, and with --hop-fence on it is exactly that; the loop is written for the
    general case with a cycle guard so an unfenced depth-2 run (second-order hops) resolves too."""
    seedset = set(seeds)
    parent: dict = {}
    for nd in nodes:
        if nd.kind == "contract" and nd.depth > 0 and nd.via_edge:
            src = nd.via_edge.get("_from")
            if src and nd.contract not in parent:
                parent[nd.contract] = src
    out: dict = {}
    for cid in {nd.contract for nd in nodes}:
        cur, seen = cid, set()
        while cur is not None and cur not in seedset:
            if cur in seen or cur not in parent:
                cur = None
                break
            seen.add(cur)
            cur = parent[cur]
        out[cid] = cur
    return out


def aggregate_kept(nodes, seeds) -> tuple:
    """(A)'s raw material: {contract: n_admitted}, {seed: n_admitted}, unattributed, {depth: n}.

    Counts EVERY admitted node, contract nodes included: a seed's own contract node occupies a budget
    slot in the shipped walk, so a budget calibrated on drivers alone would under-size by one per
    contract. The driver-only count rides beside it."""
    roots = seed_root_map(nodes, seeds)
    per_contract: dict = {}
    per_seed: dict = {s: 0 for s in seeds}
    by_depth: dict = {}
    unattributed = 0
    for nd in nodes:
        per_contract[nd.contract] = per_contract.get(nd.contract, 0) + 1
        by_depth[str(nd.depth)] = by_depth.get(str(nd.depth), 0) + 1
        r = roots.get(nd.contract)
        if r is None:
            unattributed += 1
        else:
            per_seed[r] = per_seed.get(r, 0) + 1
    return per_contract, per_seed, unattributed, by_depth


def aggregate_eligible(invocations, nodes, seeds) -> tuple:
    """(B)'s raw material: {contract: n}, {seed: n}, deduped by (contract, driver) ACROSS the walk's
    invocations -- the same ancestor can be eligible in two waves and it is one reserve slot, not two."""
    roots = seed_root_map(nodes, seeds)
    uniq = {(e["contract"], e["id"]) for i in invocations for e in i["eligible"]}
    per_contract: dict = {}
    per_seed: dict = {s: 0 for s in seeds}
    unattributed = 0
    for cid, _id in sorted(uniq):
        per_contract[cid] = per_contract.get(cid, 0) + 1
        r = roots.get(cid)
        if r is None:
            unattributed += 1
        else:
            per_seed[r] = per_seed.get(r, 0) + 1
    return per_contract, per_seed, unattributed


# ==========================================================================================
# THE HOOK -- call-side recording, byte-identical OFF walk.
# ==========================================================================================
class Recorder:
    """One flat invocation log + a per-walk cursor. Serial by design: attribution of an invocation to
    a walk is the instrument's whole content, and a shared threadpool would make it a guess."""

    def __init__(self):
        self.invocations: list = []
        self.probe_errors: list = []
        self._cur: list = []
        self._qid = None

    def begin(self, qid: str) -> None:
        self._qid, self._cur = qid, []

    def end(self) -> list:
        out, self._cur, self._qid = self._cur, [], None
        return out

    def record(self, rec: dict) -> None:
        rec["qid"] = self._qid
        rec["invocation"] = len(self._cur)
        self._cur.append(rec)
        self.invocations.append(rec)


def assert_signature(plan_fn) -> None:
    """SIGNATURE-PARITY LAW. The wrapper stands in for a private planner function; if its parameter
    list drifts the census would either crash mid-run or -- far worse -- silently bind a value to the
    wrong name and publish a number nobody can attribute. Refuse instead."""
    got = tuple(inspect.signature(plan_fn).parameters)
    if got != _CLOSURE_PLAN_PARAMS:
        raise SystemExit(
            "REFUSED: planner._closure_plan signature drifted.\n"
            "  expected %s\n  found    %s\n"
            "The census wraps this seam; a drifted signature means it would measure something other\n"
            "than the shipped mechanism. Re-read planner.py:281 and re-pin _CLOSURE_PLAN_PARAMS."
            % (list(_CLOSURE_PLAN_PARAMS), list(got)))


@contextmanager
def census_hook(pl, rec: Recorder, *, probe_n: int):
    """Install the recording wrapper for the duration of ONE walk, then restore the real function.

    The wrapper returns None ALWAYS -- that is the planner's documented "nothing reserved" contract,
    under which the caller runs the shipped admission verbatim. So the walk measured is the OFF walk;
    `--parity-sample` proves it per run rather than asserting it.

    The FULL eligible list is retained on the invocation record (finding 2): it is the raw material of
    (B) and it carries `contract`, the grouping key. It is bounded by reserve SUPPLY, not by anything
    a query can inflate, and it never reaches the artifact unaggregated."""
    real = pl._closure_plan
    assert_signature(real)

    def _wrapper(scored, kept, graph, *, node_budget, reserve_n, backed, slice_of_driver,
                 wave_pruned, protect_ids=frozenset(), slots_by_origin=None,
                 origin_of_contract=None, score_of=None, n_charged=None):
        base = base_admissions(scored, len(kept), node_budget)
        hr = headroom(len(kept), len(base), node_budget)
        eligible, probe_err = [], None
        try:
            # THE PROBE INFLATES EVERY CAP, and `slots_by_origin` is a cap like the other two.
            # The probe exists to size the FULL eligible ancestor population, which is why it already
            # lifts node_budget and sets reserve_n=probe_n. On an ADMISSION V2 walk the per-origin
            # slot ledger is a THIRD bound (_closure_plan:418 `slots = dict(slots_by_origin or {})`),
            # so forwarding the real caps verbatim would silently report a number bounded by supply
            # rather than by demand -- the exact class of error this script's refusal fence exists to
            # prevent. Inflate each origin to probe_n instead, which keeps `dedicated` TRUE
            # (_closure_plan:373 tests `is not None`, so the v2 ordering/scoring path is still the
            # thing being measured) while removing the bound. The other three v2 arguments are
            # forwarded UNCHANGED: they select the mechanism, they do not cap it.
            #
            # The no-op guarantee is unaffected: _closure_plan COPIES the dict, so neither the real
            # ledger nor the walk can observe the probe -- and the wrapper still returns None always.
            probe_slots = ({o: probe_n for o in slots_by_origin}
                           if slots_by_origin is not None else None)
            probe = real(list(base), kept, graph,
                         node_budget=len(kept) + len(base) + probe_n + _PROBE_SLACK,
                         reserve_n=probe_n, backed=backed, slice_of_driver=slice_of_driver,
                         wave_pruned=wave_pruned, protect_ids=protect_ids,
                         slots_by_origin=probe_slots, origin_of_contract=origin_of_contract,
                         score_of=score_of, n_charged=n_charged)
            if probe is not None:
                eligible = [{"id": r["key"][2], "contract": r["contract"],
                             "ancestor_of": r["ancestor_of"], "chain_depth": r["chain_depth"]}
                            for r in probe["reserved"]]
        except Exception as exc:                              # noqa: BLE001 -- recorded, never swallowed
            probe_err = "%s: %s" % (type(exc).__name__, exc)
            rec.probe_errors.append(probe_err)
        rec.record({
            "kept_before": len(kept), "base_n": len(base), "node_budget": node_budget,
            # Retrofit-review finding 2: the base-arith escape hatch must be checkable PER
            # BOUNDARY, so each invocation stamps how many d>0 CONTRACT nodes (tracked hops)
            # are in `kept` at this moment -- an inexact boundary is explained only when its
            # excess is covered by hops admitted BETWEEN the two stamps. `kept` is the walk's
            # dict keyed (kind, contract, id) -> GroundedNode (planner.py:852, signature-pinned
            # by the wrapper's refusal fence, so this shape cannot silently drift).
            "hops_before": sum(1 for k, nd in kept.items() if k[0] == "contract" and nd.depth > 0),
            "headroom": hr,
            "headroom_raw": node_budget - (len(kept) + len(base)),
            "reserve_n_gate": reserve_n,
            "n_candidates": len(scored),
            "n_driver_candidates": sum(1 for e in scored if e[3] == "driver" and e[5] > 0),
            "n_eligible": len(eligible),
            "n_eligible_at_reserve_n": min(len(eligible), reserve_n),
            "eligible_capped": len(eligible) >= probe_n,       # the probe cap BOUND -- flagged, never silent
            "eligible": eligible,
            "probe_error": probe_err,
        })
        return None

    pl._closure_plan = _wrapper
    try:
        yield
    finally:
        pl._closure_plan = real


class _HopFencedGraph:
    """D-MW-13's second-order-hop fence ("skip the cross_links enqueue when the child would land at
    d >= 2"), applied from OUTSIDE the planner because the fence is not built yet. ON BY DEFAULT
    (finding 4): the fence rides BOTH P3-A arms as preset base, so the unfenced walk is the one P3
    will never run. VALID ONLY AT depth == 2, where the fence is exactly "only a SEED contract expands
    hops" -- contract nodes reach the walk only as seeds (d==0) or as hop children (d>=1). The census
    refuses the flag at any other depth rather than shipping an approximation."""

    def __init__(self, graph, seeds):
        self._g = graph
        self._seeds = frozenset(seeds)

    def cross_links(self, contract: str) -> list:
        return self._g.cross_links(contract) if contract in self._seeds else []

    def __getattr__(self, name):
        return getattr(self._g, name)


# ==========================================================================================
# POPULATION
# ==========================================================================================
def resolve_decks(spec: str | None) -> list:
    """`--decks` -> deck paths. Default = the glob the prior census used, so the populations are
    comparable row for row; a csv accepts bare stems, stems with .yaml, or paths."""
    if not spec or spec.strip().lower() == "all":
        return sorted(_CFG.glob("eval_queries*.yaml"))
    out = []
    for raw in spec.split(","):
        name = raw.strip()
        if not name:
            continue
        p = Path(name)
        if not p.is_absolute():
            cand = _REPO_ROOT / name
            p = cand if cand.exists() else _CFG / name
        if p.suffix != ".yaml":
            p = p.with_suffix(".yaml")
        if not p.exists():
            raise SystemExit("REFUSED: deck not found: %s" % p)
        out.append(p)
    return out


def load_population(decks: list) -> list:
    """Unique questions across the decks, first occurrence wins (deck order = the glob's sort), so a
    question shared by two decks is ONE walk and the denominator is honest."""
    import yaml
    seen: dict = {}
    rows = []
    for p in decks:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for i, q in enumerate(doc.get("queries") or []):
            if not isinstance(q, dict):
                continue
            text = (q.get("question") or "").strip()
            if not text or text in seen:
                continue
            seen[text] = True
            rows.append({"qid": "%s:%s" % (p.stem, q.get("id") or i), "deck": p.stem, "question": text,
                         "_pop_i": len(rows)})
    return rows


def resolve_arms(spec: str | None) -> list:
    """`--arms` -> the ordered arm list. `at-knobs` and `at_knobs` both accept."""
    if not spec:
        return list(DEFAULT_ARMS)
    out = []
    for raw in spec.split(","):
        a = raw.strip().lower().replace("-", "_")
        if not a:
            continue
        if a not in ARMS:
            raise SystemExit("REFUSED: unknown arm %r (choose from %s)" % (raw.strip(), ", ".join(ARMS)))
        if a not in out:
            out.append(a)
    if not out:
        raise SystemExit("REFUSED: --arms resolved to nothing.")
    return out


# ==========================================================================================
# PREFLIGHT
# ==========================================================================================
def _lev():
    """Import the shipped leaves. src/ joins sys.path only if the package is not installed."""
    try:
        from leviathan.graphrag import answer, evidence, graph, planner
    except ImportError:
        sys.path.insert(0, str(_REPO_ROOT / "src"))
        from leviathan.graphrag import answer, evidence, graph, planner
    return answer, evidence, graph, planner


def preflight_store(args) -> None:
    """The evidence-store env is REQUIRED by the STEP-0 brief. Honest statement of what it does and
    does not buy: the WALK reads no evidence rows (that is `ground()`), so this env is a proxy for
    "a serving-shaped environment", not a correctness dependency -- hence the explicit, recorded
    override. The fence that actually matters is `preflight_embedder`, and THAT one has no flag."""
    if os.environ.get("EVIDENCE_S3") or os.environ.get("EVIDENCE_BACKEND") == "pg":
        return
    if args.allow_no_evidence_store:
        print("NOTE: no EVIDENCE_S3 / EVIDENCE_BACKEND=pg; running under --allow-no-evidence-store.")
        print("      The walk reads no evidence rows, so the census is unaffected -- but this is")
        print("      RECORDED in the report header so the run is never mistaken for a serving-env one.")
        return
    raise SystemExit(
        "REFUSED: no evidence store configured (EVIDENCE_S3 unset and EVIDENCE_BACKEND != 'pg').\n"
        "  STEP-0 is specified to run in a real environment. The walk itself reads no evidence rows,\n"
        "  so if you know that and want the offline run anyway, pass --allow-no-evidence-store; it is\n"
        "  stamped into the report. The embedder fence below is NOT overridable.")


def preflight_embedder(ev) -> dict:
    """NON-OVERRIDABLE. A hash/degenerate embedder is the exact artifact that produced the D-GD R1
    finding this census is re-measuring; running one here would reproduce the error, not correct it.

    The probe is geometric, not a name check: a real semantic embedder puts near-synonyms close
    together, a hash embedder centres every pair on ~0.0."""
    backend = ev.DEFAULT_BACKEND
    try:
        vecs = {t: ev.embed([t])[0] for pair in _EMBED_PROBE_PAIRS for t in pair}
    except Exception as exc:  # noqa: BLE001
        raise SystemExit("REFUSED: the embedder did not load (%s: %s).\n"
                         "  backend=%r. STEP-0 must run the REAL bge-m3 -- a hash embedder is what\n"
                         "  produced the number this census exists to correct."
                         % (type(exc).__name__, exc, backend))
    dim = len(next(iter(vecs.values())))
    if dim < _EMBED_MIN_DIM:
        raise SystemExit("REFUSED: embedding dimension %d < %d -- not a real bge-m3 vector (backend=%r)."
                         % (dim, _EMBED_MIN_DIM, backend))
    cos = {"%s~%s" % p: round(ev._cosine(vecs[p[0]], vecs[p[1]]), 4) for p in _EMBED_PROBE_PAIRS}
    worst = min(cos.values())
    if worst < _EMBED_COS_FLOOR:
        raise SystemExit(
            "REFUSED: embedder geometry is degenerate -- near-synonym cosine %.4f < %.2f (%s, backend=%r).\n"
            "  This is the hash-embedder signature (cosines centred on 0.0, everything below tau, the\n"
            "  budget never binds). GUIDED_DEPTH_V2_PLAN.md:141-170. There is no override for this."
            % (worst, _EMBED_COS_FLOOR, cos, backend))
    return {"backend": backend, "dim": dim, "probe_cosines": cos}


def _preset_drift(args) -> dict | None:
    """If reasoning_modes ever gains the R7 `max` preset, print the diff instead of letting the census
    calibrate knobs the preset no longer carries (the stale-instrument class)."""
    try:
        from leviathan.graphrag import reasoning_modes as rm
    except Exception:  # noqa: BLE001
        return None
    m = getattr(rm, "MODES", {}).get("max")
    if m is None:
        return None
    got = {k: getattr(m, k, None) for k in ("seed_ceiling", "per_seed_budget", "per_seed_reserve", "depth")}
    mine = {"seed_ceiling": args.max_seeds, "per_seed_budget": PROVISIONAL_PER_SEED_BUDGET,
            "per_seed_reserve": PROVISIONAL_PER_SEED_RESERVE, "depth": args.depth}
    return None if got == mine else {"preset": got, "census": mine}


# ==========================================================================================
# THE RUN
# ==========================================================================================
def make_route_fn(an, mode: str, max_seeds: int):
    """`lexical` = tier-1 `answer.route` (the prior census's router, deterministic and offline).
    `semantic` = tier-1 then tier-2 at k = max_seeds (bge only). Tier 3 (route_llm) is NEVER wired:
    it spends money and it is not reproducible."""
    if mode == "lexical":
        return lambda q, g: an.route(q, g)
    return lambda q, g: (an.route(q, g) or an.route_semantic(q, g, k=max_seeds))


def arm_budget(arm: str, n_seeds: int, args) -> int:
    """THE ARM'S node_budget FOR THIS WALK -- seed-scaled where R7 says it is (finding 1).

    `demand`   : effectively uncapped, so the admitted count is DEMAND and tau is the only filter.
    `at_knobs` : the per-seed COSINE allocation x the REALIZED seed count. This is the one number the
                 shipped flat-budget planner can express faithfully; R7's additive reserve cannot be
                 expressed, and does not need to be -- this census never reserves anything.
    `flat`     : the retired pre-R7 constant, kept only so the prior 288-walk census stays comparable."""
    if arm == "demand":
        return args.demand_budget
    if arm == "at_knobs":
        return PROVISIONAL_PER_SEED_BUDGET * max(1, n_seeds)
    return args.node_budget


def walk_row(pl, graph, q: dict, *, args, rec: Recorder, route_fn, arm: str) -> dict | None:
    """One census walk. Returns None when the question routes to no contract (excluded from the
    denominator, exactly as the prior census excluded its 39).

    FINDING 2: every per-seed aggregate is computed HERE, from `sg.nodes` and the walk's own
    invocation records, and PUBLISHED on the row. Nothing the calibration reads lives in an
    underscore key, so a completed run answers the question by re-reading its JSON."""
    seeds = pl._seed_contracts(q["question"], graph, route_fn, args.max_seeds)
    if not seeds:
        return None
    budget = arm_budget(arm, len(seeds), args)
    g_used = _HopFencedGraph(graph, seeds) if args.hop_fence == "on" else graph
    rec.begin(q["qid"])
    sg = pl.grounded_subgraph(q["question"], g_used, depth=args.depth, node_budget=budget,
                              max_seeds=args.max_seeds, tau=args.tau, route_fn=route_fn,
                              closure_reserve=args.reserve_n)
    invs = rec.end()
    kept = len(sg.nodes)
    per_contract, per_seed, unattr, by_depth = aggregate_kept(sg.nodes, seeds)
    el_contract, el_seed, el_unattr = aggregate_eligible(invs, sg.nodes, seeds)
    return {
        "qid": q["qid"], "deck": q["deck"], "question": q["question"][:160],
        "arm": arm, "node_budget": budget,
        "seeds": seeds, "n_seeds": len(seeds),
        "kept": kept,
        # ---- (A) PER-SEED COSINE DEMAND (published, finding 2) ----
        "per_seed_kept": per_seed,
        "per_contract_kept": per_contract,
        "unattributed_kept": unattr,
        "kept_by_depth": by_depth,
        "n_hop_contracts": sum(1 for nd in sg.nodes if nd.kind == "contract" and nd.depth > 0),
        # ---- (B) PER-SEED RESERVE DEMAND (published, finding 2) ----
        "per_seed_eligible": el_seed,
        "per_contract_eligible": el_contract,
        "unattributed_eligible": el_unattr,
        "eligible_capped": any(i["eligible_capped"] for i in invs),
        # ---- recorded diagnostics ----
        "end_of_walk_headroom": budget - kept,
        "seed_scaled_saturated": kept >= PROVISIONAL_PER_SEED_BUDGET * len(seeds),
        "n_invocations": len(invs),
        "headroom_by_invocation": [i["headroom"] for i in invs],
        "eligible_by_invocation": [i["n_eligible"] for i in invs],
        "kept_before_by_invocation": [i["kept_before"] for i in invs],
        "base_n_by_invocation": [i["base_n"] for i in invs],
        "hops_before_by_invocation": [i.get("hops_before", 0) for i in invs],
        "headroom_positive": any(i["headroom"] > 0 for i in invs),
        "max_headroom": max([i["headroom"] for i in invs] or [0]),
        "eligible_any": any(i["n_eligible"] > 0 for i in invs),
        "max_eligible": max([i["n_eligible"] for i in invs] or [0]),
        "can_fire": any(i["headroom"] > 0 and i["n_eligible"] > 0 for i in invs),
        "eligible_sample": [e for i in invs for e in i["eligible"]][:6],
        # kept out of the published row (popped before the report is written); these are what the
        # paired control walk is compared against. `_pop_i` addresses the question by POSITION --
        # deck ids are not guaranteed unique, and a parity control run against the wrong question
        # would "prove" a mismatch that is really a lookup bug.
        "_pop_i": q["_pop_i"],
        "_kept_keys": sg.trace["kept"], "_pruned": sg.trace["pruned"], "_visited": sg.trace["visited"],
    }


def parity_check(pl, graph, q: dict, row: dict, *, args, route_fn) -> dict | None:
    """PROVE the instrument is a no-op: re-run the SAME walk with the hook removed and
    closure_reserve=0 (the shipped OFF arm) and compare the walk's own trace. Cheap because
    ev._Q_CACHE memoizes every single-text embed across walks in this process."""
    # A control run against the WRONG question would report a mismatch that is really a lookup bug,
    # and the run would abort claiming the instrument perturbed the walk. Fail on the lookup instead.
    if q["qid"] != row["qid"]:
        raise SystemExit("REFUSED: parity lookup mismatch %r vs %r" % (q["qid"], row["qid"]))
    seeds = pl._seed_contracts(q["question"], graph, route_fn, args.max_seeds)
    g_used = _HopFencedGraph(graph, seeds) if args.hop_fence == "on" else graph
    ctl = pl.grounded_subgraph(q["question"], g_used, depth=args.depth, node_budget=row["node_budget"],
                               max_seeds=args.max_seeds, tau=args.tau, route_fn=route_fn,
                               closure_reserve=0)
    diffs = {}
    if ctl.trace["kept"] != row["_kept_keys"]:
        diffs["kept"] = {"control": len(ctl.trace["kept"]), "census": len(row["_kept_keys"])}
    if ctl.trace["pruned"] != row["_pruned"]:
        diffs["pruned"] = {"control": len(ctl.trace["pruned"]), "census": len(row["_pruned"])}
    if ctl.trace["seeds"] != row["seeds"] or ctl.trace["visited"] != row["_visited"]:
        diffs["seeds_or_visited"] = True
    return {"qid": q["qid"], "diffs": diffs} if diffs else None


def base_arith_health(rows: list) -> dict:
    """Cross-check the `base_admissions` mirror against the walk that actually ran, IN BOTH DIRECTIONS
    (finding 5).

    Between two consecutive invocations the walk admits AT LEAST the base it was measured with, so
    kept_before(i+1) >= kept_before(i) + base_n(i) is an invariant -- but it is ONE-SIDED: a mirror
    that UNDER-counted base_n sails through it while inflating headroom, which is exactly the drift
    direction that manufactures a headroom-positive walk. So the census also holds a PRE-COMMITTED
    EXACTNESS FLOOR, and below it every inexact boundary must be EXPLAINED.

    THE EXPLANATION IS CHECKABLE. An inexact boundary is legitimate only if a wave ran between the two
    invocations without invoking the seam. The gate is `reserve_left > 0 and >=1 d>0 driver candidate`
    (planner.py:488-489) and reserve_left never decreases here (nothing is ever reserved), so a
    non-invoking wave is exactly a wave with NO d>0 driver candidate -- and such a wave can only have
    grown `kept` by admitting CONTRACT nodes at d>0, i.e. tracked hops. A walk with an inexact boundary
    and ZERO admitted hop contracts therefore has no legitimate explanation, and the run aborts."""
    viol, exact, pairs = [], 0, 0
    inexact: dict = {}

    # Retrofit-review finding 2: the escape hatch is PER BOUNDARY, not per walk. The old
    # predicate ("did this walk admit any hop contract anywhere") excused every boundary on
    # ~every walk (94% of contracts carry a tracked cross_link and hops sort first), making the
    # 90% floor vacuous. Now each invocation stamps its hop-contract count, and an inexact
    # boundary is explained ONLY when its excess is covered by hops admitted BETWEEN the two
    # stamps -- the exact population a non-invoking wave can admit.
    def _inexact(r, i, excess, hops_between):
        inexact.setdefault(r["qid"], []).append(
            {"i": i, "excess": excess, "hops_between": hops_between,
             "explained": excess <= hops_between})

    for r in rows:
        kb, bn = r["kept_before_by_invocation"], r["base_n_by_invocation"]
        hb = r.get("hops_before_by_invocation") or [0] * len(kb)
        final_hops = r.get("n_hop_contracts", 0)
        for i in range(len(kb) - 1):
            pairs += 1
            got, want = kb[i + 1], kb[i] + bn[i]
            if got < want:
                viol.append({"qid": r["qid"], "i": i, "kept_before": kb, "base_n": bn})
            elif got == want:
                exact += 1
            else:
                _inexact(r, i, got - want, max(0, hb[i + 1] - hb[i]))
        if kb:
            pairs += 1
            got, want = r["kept"], kb[-1] + bn[-1]
            if got < want:
                viol.append({"qid": r["qid"], "i": "final", "kept": r["kept"], "kept_before": kb,
                             "base_n": bn})
            elif got == want:
                exact += 1
            else:
                _inexact(r, "final", got - want, max(0, final_hops - hb[-1]))
    frac = round(exact / pairs, 4) if pairs else 0.0
    unexplained = sorted(qid for qid, items in inexact.items()
                         if any(not it["explained"] for it in items))
    ok = (not viol) and (frac >= BASE_ARITH_EXACT_FLOOR or not unexplained)
    return {"pairs_checked": pairs, "exact_matches": exact, "exact_frac": frac,
            "exact_floor": BASE_ARITH_EXACT_FLOOR,
            "inexact_walks": len(inexact),
            "unexplained_inexact_walks": len(unexplained), "unexplained_qids": unexplained[:5],
            "violations": viol[:5], "n_violations": len(viol), "ok": ok}


def verdict_gate(n_walks: int, limit: int, n_unique_total: int) -> dict | None:
    """FINDING 6: a truncated population may not carry a quotable calibration. Mirrors P3-A's
    'pre-committed MINIMUM ... fewer -> INSTRUMENT-DEAD GATE, recorded, no verdict'."""
    if limit:
        return {"no_verdict": True,
                "line": "NO VERDICT: truncated population (--limit %d of %d unique questions)"
                        % (limit, n_unique_total),
                "reason": "--limit set"}
    if n_walks < MIN_POPULATION:
        return {"no_verdict": True,
                "line": "NO VERDICT: truncated population (%d routed walk(s) of a %d minimum)"
                        % (n_walks, MIN_POPULATION),
                "reason": "n_walks < MIN_POPULATION"}
    return None


def run_arm(arm: str, *, pl, graph, pop: list, args, route_fn) -> dict:
    """Walk the whole population once at ONE arm's budget rule. Returns {"abort": msg} instead of a
    result whenever the instrument is unsound: a mixture is never reported as a measurement."""
    started = time.time()
    rec = Recorder()
    rows, unrouted = [], []
    print("")
    print("ARM %s: %s" % (arm.upper(), _ARM_NOTE[arm] % (args.demand_budget if arm == "demand"
                                                         else PROVISIONAL_PER_SEED_BUDGET if arm == "at_knobs"
                                                         else args.node_budget)))
    for i, q in enumerate(pop, 1):
        with census_hook(pl, rec, probe_n=args.eligible_probe_n):
            row = walk_row(pl, graph, q, args=args, rec=rec, route_fn=route_fn, arm=arm)
        if row is None:
            unrouted.append(q["qid"])
        else:
            rows.append(row)
        if i % 25 == 0 or i == len(pop):
            print("  [%4d/%4d] walks=%d unrouted=%d invocations=%d  %.0fs"
                  % (i, len(pop), len(rows), len(unrouted), len(rec.invocations), time.time() - started))

    if not rec.invocations:
        return {"abort": "ZERO invocations across %d walk(s) on arm %s. The seam was never reached, so "
                         "0%% headroom would be an artifact of the instrument, not a finding." % (len(rows), arm)}
    if rec.probe_errors:
        return {"abort": "%d eligibility probe(s) raised on arm %s; first: %s. A partially-failed "
                         "eligibility scan is a mixture." % (len(rec.probe_errors), arm, rec.probe_errors[0])}

    parity_rows, mismatches = [], []
    if args.parity_sample:
        step = max(1, len(rows) // args.parity_sample) if args.parity_sample > 0 else 1
        sample = rows if args.parity_sample < 0 else rows[::step][:args.parity_sample]
        for row in sample:
            bad = parity_check(pl, graph, pop[row["_pop_i"]], row, args=args, route_fn=route_fn)
            parity_rows.append(row["qid"])
            if bad:
                mismatches.append(bad)
    if mismatches:
        return {"abort": "the census hook PERTURBED the walk on %d/%d parity sample(s) of arm %s: %s. The "
                         "measured walk must be the shipped OFF walk byte for byte."
                         % (len(mismatches), len(parity_rows), arm, json.dumps(mismatches[:2]))}

    health = base_arith_health(rows)
    if not health["ok"]:
        if health["n_violations"]:
            return {"abort": "the base_admissions mirror disagrees with the walk on %d boundary(ies) of arm "
                             "%s: %s. planner.py's admission loop has drifted from this file's mirror."
                             % (health["n_violations"], arm, json.dumps(health["violations"][:2]))}
        return {"abort": "base-arithmetic exactness %.1f%% is below the pre-committed %.0f%% floor on arm %s "
                         "and %d walk(s) have an inexact boundary with NO un-instrumented wave to explain it "
                         "(zero admitted hop contracts): %s"
                         % (100.0 * health["exact_frac"], 100.0 * BASE_ARITH_EXACT_FLOOR, arm,
                            health["unexplained_inexact_walks"], json.dumps(health["unexplained_qids"]))}

    summary = summarize(rows)
    for r in rows:                                            # AFTER every aggregate is published
        for key in [k for k in r if k.startswith("_")]:       # machinery never reaches the artifact
            r.pop(key)
    return {
        "arm": arm,
        "budget_rule": _ARM_NOTE[arm] % (args.demand_budget if arm == "demand"
                                         else PROVISIONAL_PER_SEED_BUDGET if arm == "at_knobs"
                                         else args.node_budget),
        "wall_clock_s": round(time.time() - started, 1),
        "population": {"n_routed": len(rows), "n_unrouted": len(unrouted), "unrouted_qids": unrouted[:40]},
        "instrument": {
            "design": "planner._closure_plan wrapped; wrapper returns None (the planner's own "
                      "nothing-reserved contract) so the walk is the shipped OFF walk; eligibility "
                      "read from the UNPATCHED function on an inflated-budget probe call",
            "planner_changed": False,
            "invocation_gate": "reserve_left > 0 and >=1 driver candidate at depth > 0 (planner.py:489)",
            "n_invocations": len(rec.invocations),
            "walks_with_zero_invocations": sum(1 for r in rows if r["n_invocations"] == 0),
            "parity_checked": len(parity_rows), "parity_mismatches": len(mismatches),
            "parity_qids": parity_rows,
            "base_arith": health,
            "probe_errors": len(rec.probe_errors),
        },
        "summary": summary,
        "walks": rows,
    }


def _fmt_dist(d: dict) -> str:
    return "%s/%s/%s/%s/%s/%s  mean %s" % (d["min"], d["p25"], d["median"], d["p75"], d["p90"],
                                           d["max"], d["mean"])


def _wrap_json(label: str, obj, width: int = 96, indent: int = 6) -> list:
    """A histogram WRAPS, it never truncates. The whole point of publishing the histogram rather than
    buckets is that a p75 calibration must let the reader see the tail it is cutting off."""
    head = "%s%-32s: " % (" " * indent, label)
    room = max(30, width - len(head))
    parts, cur = [], ""
    for tok in json.dumps(obj).split(", "):
        cand = tok if not cur else cur + ", " + tok
        if len(cand) > room and cur:
            parts.append(cur)
            cur = tok
        else:
            cur = cand
    if cur:
        parts.append(cur)
    if not parts:
        return [head + "{}"]
    return [(head if i == 0 else " " * len(head)) + p + ("," if i < len(parts) - 1 else "")
            for i, p in enumerate(parts)]


def render(report: dict) -> list:
    """ASCII summary table (cp1252 console). Every published number appears here."""
    p, k = report["population"], report["knobs"]
    L = []
    L.append("")
    L.append("=" * 100)
    L.append("D-MW-15 STEP-0 CALIBRATION CENSUS [R7-FINAL] -- per-seed cosine demand + per-seed reserve demand")
    L.append("=" * 100)
    L.append("population : %d deck(s) / %d unique questions%s   router=%s"
             % (len(p["decks"]), p["n_questions"],
                (" (--limit of %d)" % p["n_unique_total"]) if p.get("limit") else "", p["router"]))
    _dk = ", ".join(p["decks"])
    L.append("             %s" % (_dk[:48] + (" ...(%d decks, all listed in the JSON)" % len(p["decks"]))
                                  if len(_dk) > 48 else _dk))
    L.append("knobs      : seed_ceiling=%d depth=%d tau=%.2f reserve_n=%d hop_fence=%s probe_n=%d"
             % (k["max_seeds"], k["depth"], k["tau"], k["reserve_n"], k["hop_fence"], k["eligible_probe_n"]))
    L.append("provisional: per_seed_budget=%d per_seed_reserve=%d (R7 D-MW-13); arms=%s"
             % (PROVISIONAL_PER_SEED_BUDGET, PROVISIONAL_PER_SEED_RESERVE, ",".join(k["arms"])))
    L.append("embedder   : %s dim=%d probe=%s" % (k["embedder"]["backend"], k["embedder"]["dim"],
                                                  k["embedder"]["probe_cosines"]))
    # Retrofit-review finding 4: the override must be visible in the artifact a human READS,
    # not only inferable from a null and argv -- a no-store run must never be mistaken for a
    # serving-env one.
    if not k.get("evidence_store"):
        L.append("environment: evidence store ABSENT (--allow-no-evidence-store; the walk reads "
                 "no evidence rows)")
    if k.get("preset_drift"):
        L.append("WARNING    : the `max` preset now exists and DISAGREES with these knobs: %s"
                 % json.dumps(k["preset_drift"]))
        L.append("             re-run with the preset's values before the calibration is quoted.")

    for arm in k["arms"]:
        a = report["arms"][arm]
        s, ins = a["summary"], a["instrument"]
        ba = ins["base_arith"]
        L.append("")
        L.append("-" * 100)
        L.append("ARM %-9s %s" % (arm.upper(), a["budget_rule"]))
        if arm == "flat":
            L.append("             PRE-R7 SHAPE: the max preset has no flat node budget. Continuity control only.")
        L.append("-" * 100)
        L.append("population : %d routed / %d unrouted"
                 % (a["population"]["n_routed"], a["population"]["n_unrouted"]))
        L.append("seeds      : realized-seed-count histogram %s" % json.dumps(s["n_seeds_histogram"]))
        L.append("instrument : %d invocations; %d walk(s) never reached the seam; parity %d/%d clean"
                 % (ins["n_invocations"], ins["walks_with_zero_invocations"],
                    ins["parity_checked"] - ins["parity_mismatches"], ins["parity_checked"]))
        L.append("             base_arith: %d/%d boundaries exact (%.1f%%, floor %.0f%%); inexact walks %d, "
                 "unexplained %d"
                 % (ba["exact_matches"], ba["pairs_checked"], 100.0 * ba["exact_frac"],
                    100.0 * ba["exact_floor"], ba["inexact_walks"], ba["unexplained_inexact_walks"]))
        # Retrofit-review finding 3: attribution loss deflates the per-seed calibration input
        # while the per-contract grouping still counts the node -- printed so a non-zero value
        # is never silent. Provably 0 at depth 2 with the fence on; the exposure is the
        # sensitivity arm and any future depth change, exactly where a reader needs the number.
        L.append("             attribution: %d kept / %d eligible node(s) unattributed to a seed "
                 "(non-zero deflates the per-seed distributions the rule reads)"
                 % (s["pooled"].get("unattributed_kept", 0),
                    s["pooled"].get("unattributed_eligible", 0)))
        pool = s["pooled"]
        # THE LABELS ARE PER ARM ON PURPOSE. Only the uncapped arm's (A) is DEMAND -- on a capped arm
        # the same aggregate is supply-under-a-cap. Only the at-knobs arm's (B) is measured against
        # the covered set the shipped reservation will see. Anything else is a sensitivity reading and
        # says so, so no number can be quoted for a question it does not answer.
        lab_a = ("PER-SEED COSINE DEMAND -- CALIBRATION SOURCE for per_seed_budget"
                 if arm == "demand" else
                 "PER-SEED ADMITTED UNDER THIS ARM'S CAP -- NOT demand (the budget bound it)")
        lab_b = ("PER-SEED RESERVE DEMAND -- CALIBRATION SOURCE for per_seed_reserve"
                 if arm == "at_knobs" else
                 "PER-SEED RESERVE DEMAND -- SENSITIVITY READING ONLY")
        sub_b = ("(backed + slice-distinct ancestors of admitted drivers, probe cap %d)"
                 % k["eligible_probe_n"]) if arm == "at_knobs" else \
                ("(this arm's larger covered set suppresses slice-distinct eligibility; probe cap %d)"
                 % k["eligible_probe_n"])
        L.append("")
        L.append("  (A) %s" % lab_a)
        L.append("      (admitted nodes rolled up to the seed whose expansion reached them)")
        L.append("      pooled  min/p25/p50/p75/p90/max : %s   n=%d demand units"
                 % (_fmt_dist(pool["per_seed_cosine_demand"]), pool["per_seed_cosine_demand"]["n"]))
        L.extend(_wrap_json("histogram", pool["per_seed_cosine_demand"]["histogram"]))
        L.append("      per-CONTRACT grouping (plan's literal wording, unrolled)")
        L.append("      pooled  min/p25/p50/p75/p90/max : %s" % _fmt_dist(pool["per_contract_cosine_demand"]))
        L.append("")
        L.append("  (B) %s" % lab_b)
        L.append("      %s" % sub_b)
        L.append("      pooled  min/p25/p50/p75/p90/max : %s   n=%d demand units"
                 % (_fmt_dist(pool["per_seed_reserve_demand"]), pool["per_seed_reserve_demand"]["n"]))
        L.extend(_wrap_json("histogram", pool["per_seed_reserve_demand"]["histogram"]))
        L.append("      walks where the probe cap BOUND : %d/%d = %.1f%%"
                 % (pool["eligible_capped_walks"], pool["n_walks"], 100.0 * pool["eligible_capped_frac"]))
        L.append("")
        L.append("  STRATIFIED BY REALIZED SEED COUNT (finding 3: pooling a 1/2/3/..-seed mix is a seed-mix stat)")
        L.append("  n_seeds  walks   cosine/seed p50 p75 max   reserve/seed p50 p75 max   kept p50   sat%  elig%")
        for key in sorted(s["by_n_seeds"], key=lambda x: int(x)):
            b = s["by_n_seeds"][key]
            c, rs, kd = b["per_seed_cosine_demand"], b["per_seed_reserve_demand"], b["kept_distribution"]
            L.append("  %-8s %-7d %11s %3s %3s %19s %3s %3s %9s %6.0f%% %5.0f%%"
                     % (key, b["n_walks"], c["median"], c["p75"], c["max"],
                        rs["median"], rs["p75"], rs["max"], kd["median"],
                        100.0 * b["seed_scaled_saturated_frac"], 100.0 * b["eligible_ancestor_frac"]))
        L.append("  %-8s %-7d %11s %3s %3s %19s %3s %3s %9s %6.0f%% %5.0f%%"
                 % ("POOLED", pool["n_walks"], pool["per_seed_cosine_demand"]["median"],
                    pool["per_seed_cosine_demand"]["p75"], pool["per_seed_cosine_demand"]["max"],
                    pool["per_seed_reserve_demand"]["median"], pool["per_seed_reserve_demand"]["p75"],
                    pool["per_seed_reserve_demand"]["max"], pool["kept_distribution"]["median"],
                    100.0 * pool["seed_scaled_saturated_frac"], 100.0 * pool["eligible_ancestor_frac"]))
        L.append("  (sat%% = walks whose kept reaches %d x n_seeds, i.e. the provisional cosine allocation "
                 "would BIND)" % PROVISIONAL_PER_SEED_BUDGET)
        L.append("")
        L.append("  RECORDED DIAGNOSTICS (the retired fork's quantities -- no decision reads these)")
        hd = pool["per_wave_headroom_distribution"]
        L.append("      per-invocation headroom : n=%d  positive %d (%.1f%%)"
                 % (hd["n"], hd["positive"], 100.0 * (hd["positive_frac"] or 0)))
        L.append("        min/p25/p50/p75/p90/max %s" % _fmt_dist(hd))
        L.append("      walks headroom-positive : %d/%d = %.1f%%"
                 % (pool["headroom_positive_walks"], pool["n_walks"], 100.0 * pool["headroom_positive_frac"]))
        L.append("      walks filling the budget: %d/%d = %.1f%%"
                 % (pool["filled_budget_walks"], pool["n_walks"], 100.0 * pool["filled_budget_frac"]))
        L.append("      walks with >=1 eligible : %d/%d = %.1f%%"
                 % (pool["eligible_ancestor_walks"], pool["n_walks"], 100.0 * pool["eligible_ancestor_frac"]))
        L.append("      could fire additively   : %d/%d = %.1f%%"
                 % (pool["can_fire_walks"], pool["n_walks"], 100.0 * pool["can_fire_frac"]))
        ct = pool["cross_tab"]
        L.append("      cross-tab (walks)         ancestors>=1     ancestors=0")
        L.append("        headroom > 0      %12d %15d" % (ct["headroom_pos__ancestors_pos"],
                                                          ct["headroom_pos__ancestors_zero"]))
        L.append("        headroom = 0      %12d %15d" % (ct["headroom_zero__ancestors_pos"],
                                                          ct["headroom_zero__ancestors_zero"]))

    L.append("")
    L.append("=" * 100)
    cal = report.get("calibration") or {}
    if cal.get("no_verdict"):
        L.append(cal["line"])
        L.append("  A truncated population may not carry a quotable pre-committed calibration (finding 6;")
        L.append("  the P3-A instrument-dead-gate precedent, MOAT_WIDTH_WAVE_PLAN.md:595-597). The arm")
        L.append("  tables above are dev diagnostics. Re-run the FULL population for the calibration.")
        L.append("=" * 100)
        return L
    b, r = cal["per_seed_budget"], cal["per_seed_reserve"]
    L.append("CALIBRATION (pre-committed rule, fixed before the run)")
    L.append("  %s" % cal["rule"])
    L.append("")
    L.append("  per_seed_budget=%d covers p%d of per-seed cosine demand    (p75 demand = %d, n=%d)"
             % (b["provisional"], b["coverage_pct_at_provisional"], b["p75_demand"], b["n_demand_units"]))
    L.append("  per_seed_reserve=%d covers p%d of per-seed reserve demand  (p75 demand = %d, n=%d)"
             % (r["provisional"], r["coverage_pct_at_provisional"], r["p75_demand"], r["n_demand_units"]))
    L.append("")
    L.append("  RULE OUTCOME  per_seed_budget  = max(%d, p75 %d) = %d"
             % (b["provisional"], b["p75_demand"], b["calibrated"]))
    L.append("  RULE OUTCOME  per_seed_reserve = max(%d, p75 %d) = %d"
             % (r["provisional"], r["p75_demand"], r["calibrated"]))
    alt = cal.get("per_seed_reserve_uncapped_arm_reading")
    if alt:
        L.append("  [the uncapped arm's reserve reading, NOT the rule: p75 %d -> %d. It is LOWER by "
                 "construction --" % (alt["p75_demand"], alt["calibrated"]))
        L.append("   an uncapped walk covers more slices, and eligibility is slice-distinct. Printed so "
                 "the two readings can never diverge silently.]")
    for name, c in (("per_seed_budget", b), ("per_seed_reserve", r)):
        if c["ratification_flag"]:
            L.append("")
            L.append("  RATIFICATION FLAG: demand p75 exceeds 2x provisional for %s (p75 %d > %d)."
                     % (name, c["p75_demand"], c["ratification_threshold"]))
            L.append("    This is a COST-SURFACE change and it is the user's call. The census does not")
            L.append("    auto-raise the knob; it reports the rule's outcome and stops here.")
    L.append("")
    L.append("  sources: %s" % json.dumps(cal["sources"]))
    L.append("=" * 100)
    return L


def run(args) -> int:
    an, ev, gph, pl = _lev()
    preflight_store(args)
    emb = preflight_embedder(ev)
    assert_signature(pl._closure_plan)
    if args.hop_fence == "on" and args.depth != 2:
        raise SystemExit("REFUSED: --hop-fence on is only exact at --depth 2 (see _HopFencedGraph).")
    arms = resolve_arms(args.arms)

    decks = resolve_decks(args.decks)
    pop = load_population(decks)
    n_unique_total = len(pop)                                 # stated even when --limit truncates it
    if args.limit:
        pop = pop[:args.limit]
    if not pop:
        raise SystemExit("REFUSED: the deck selection yielded 0 questions.")

    graph = gph.CausalGraph.load()
    backed = ev.backed_dag_ids()
    if not backed:
        raise SystemExit(
            "REFUSED: ev.backed_dag_ids() is EMPTY -- driver_slices.yaml is absent or unreadable.\n"
            "  Every ancestor would be 'unbacked', eligibility would measure 0 by construction, and\n"
            "  the census would blame ancestor scarcity for a missing config.")
    route_fn = make_route_fn(an, args.router, args.max_seeds)

    started = time.time()
    print("running %d question(s) x %d arm(s) at seed_ceiling=%d depth=%d (real %s)..."
          % (len(pop), len(arms), args.max_seeds, args.depth, emb["backend"]))
    results: dict = {}
    for arm in arms:
        out = run_arm(arm, pl=pl, graph=graph, pop=pop, args=args, route_fn=route_fn)
        if "abort" in out:
            print("")
            print("ABORT: %s" % out["abort"])
            print("       Nothing is reported.")
            return 2
        results[arm] = out

    # ---- THE CALIBRATION. Sources are pinned per quantity, and the pin is a FENCE, not a
    # default (retrofit-review major: `cal_arm = "demand" if present else arms[0]` silently
    # substituted the OTHER arm as the calibration source on any single-arm run and printed an
    # unqualified RULE OUTCOME -- demonstrated to INVERT the ratification flag: demand-arm
    # cosine p75 54 -> flag, at_knobs-arm 12 -> no flag. Quantity (A) is only a demand number
    # on the UNCAPPED arm; quantity (B) is only honest on the AT-KNOBS arm (the uncapped arm's
    # covered-set inflation suppresses eligibility 0/255 vs p75=2, measured). A calibration
    # from any other source is NOT a calibration and must render as NO VERDICT. ----
    n_routed = results[arms[0]]["population"]["n_routed"]
    gate = verdict_gate(n_routed, args.limit, n_unique_total)
    if gate:
        calibration = gate
    elif "demand" not in results or "at_knobs" not in results:
        calibration = {"no_verdict": True,
                       "line": "NO VERDICT: calibration requires the demand AND at_knobs arms "
                               "(ran: %s). Quantity (A) is only measurable uncapped; quantity "
                               "(B) only at knobs." % ",".join(arms)}
    else:
        calibration = calibrate(
            demand_values(results["demand"]["walks"], "per_seed_kept"),
            demand_values(results["at_knobs"]["walks"], "per_seed_eligible"))
        calibration["sources"] = {
            "per_seed_budget": "demand arm: per-seed cosine demand",
            "per_seed_reserve": "at_knobs arm: per-seed eligible-ancestor demand (probe cap %d)"
                                % args.eligible_probe_n}
        # the two readings, never silently divergent
        other = calibrate_knob(demand_values(results["demand"]["walks"], "per_seed_eligible"),
                               PROVISIONAL_PER_SEED_RESERVE)
        calibration["per_seed_reserve_uncapped_arm_reading"] = other

    report = {
        "run": {"tool": "scripts/graphrag/headroom_census.py", "step": "D-MW-15 STEP-0 [R7-FINAL]",
                "utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "wall_clock_s": round(time.time() - started, 1),
                "graph_version": getattr(graph, "version", None), "argv": sys.argv[1:]},
        "population": {"decks": [p.stem for p in decks], "n_questions": len(pop),
                       "n_unique_total": n_unique_total,
                       "router": "%s (tier-1 answer.route%s; route_llm never called)"
                                 % (args.router, " + tier-2 route_semantic" if args.router == "semantic" else ""),
                       "limit": args.limit},
        "knobs": {"arms": arms, "max_seeds": args.max_seeds, "depth": args.depth,
                  "tau": args.tau, "reserve_n": args.reserve_n,
                  "demand_budget": args.demand_budget, "flat_node_budget": args.node_budget,
                  "provisional_per_seed_budget": PROVISIONAL_PER_SEED_BUDGET,
                  "provisional_per_seed_reserve": PROVISIONAL_PER_SEED_RESERVE,
                  "eligible_probe_n": args.eligible_probe_n, "hop_fence": args.hop_fence,
                  "embedder": emb,
                  "closure_reserve_kwarg": args.reserve_n,
                  "env_GRAPHRAG_CLOSURE_RESERVE": os.environ.get("GRAPHRAG_CLOSURE_RESERVE"),
                  "evidence_store": os.environ.get("EVIDENCE_S3") or os.environ.get("EVIDENCE_BACKEND"),
                  "allow_no_evidence_store": bool(args.allow_no_evidence_store),  # explicit, never inferred
                  "preset_drift": _preset_drift(args)},
        "calibration": calibration,
        "arms": results,
    }
    for line in render(report):
        print(line)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=False), encoding="utf-8")
        print("")
        print("report: %s" % out)
    return 0


# ==========================================================================================
# SELF-TEST -- synthetic graph, exact-cosine embedder, no S3, no network, no model load.
# ==========================================================================================
def _self_test_graph():
    """Reuses the D-GD test fixture's shape: a driver's mechanism string IS its relevance key, so the
    admission sort is fully controlled and the arithmetic is predictable by hand.

    `build` optionally attaches a TRACKED hop, because a wave-2 driver population is otherwise
    UNREACHABLE: a driver's parents are same-contract by schema and the walk enqueues every driver
    of a contract into wave 1, so a single-contract DAG has an empty depth-2 driver set (measured 0
    new keys in 33 of 33 DAGs -- planner.py:53-60). Wave 2 exists only behind a cross-commodity hop,
    which is exactly why depth=2 is part of the `max` bundle."""
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g

    rel: dict = {}

    def drv(id_, r, **kw):
        mech = "m::%s" % id_
        rel[mech] = r
        return cs.Driver(id=id_, type=kw.pop("type", "hazard"), sign=kw.pop("sign", "+"), mechanism=mech, **kw)

    def embed(texts):
        out = []
        for t in texts:
            r = 1.0 if t == "QQ" else float(rel.get(t, 0.0))
            r = max(-1.0, min(1.0, r))
            out.append([r, math.sqrt(max(0.0, 1.0 - r * r))])
        return out

    def build(drivers, hop=None, hop_rel=0.95):
        """`hop` = {contract_id: [drivers]}; the edge is TRACKED because the target is loaded."""
        hop = hop or {}
        edges = []
        for hid in hop:
            rel["x::%s" % hid] = hop_rel
            edges.append(cs.InterCommodityEdge(driver_commodity=hid, relation="substitutes_for",
                                               sign="-", mechanism="x::%s" % hid))
        out = {"corn": cs.CausalContract(contract="corn", aliases=["corn"], drivers=drivers,
                                         inter_commodity=edges)}
        for hid, hds in hop.items():
            out[hid] = cs.CausalContract(contract=hid, aliases=[hid], drivers=hds)
        return g.CausalGraph(out, silver=set())

    return drv, embed, build


def self_test() -> int:
    """Exercises: the base/headroom arithmetic; the CALIBRATION rule at its floor and its ratification
    boundary; the no-verdict gate; stratification; base-arithmetic exactness + its explanation check;
    the hook on a synthetic walk in BOTH postures; per-seed attribution across a tracked hop; and the
    byte-identity of the hooked walk against the control."""
    fails = []

    def chk(name, cond, extra=""):
        print("  %-62s %s%s" % (name, "PASS" if cond else "FAIL", (" " + str(extra)) if not cond else ""))
        if not cond:
            fails.append(name)

    print("SELF-TEST -- arithmetic")
    e = lambda d: (0, 0.5, "x", "driver", "corn", d, None, ("driver", "corn", "x"))   # noqa: E731
    chk("base: seeds (d==0) admit past a full budget",
        len(base_admissions([e(0), e(0), e(1)], 10, 10)) == 2)
    chk("base: d>0 stops exactly at the budget",
        len(base_admissions([e(1)] * 8, 6, 10)) == 4)
    chk("base: empty wave -> empty base", base_admissions([], 3, 10) == [])
    chk("base: an uncapped budget admits the whole wave (the demand arm)",
        len(base_admissions([e(1)] * 40, 0, 999)) == 40)
    chk("headroom: 32 - (20 + 6) == 6", headroom(20, 6, 32) == 6)
    chk("headroom: clamped at 0, never negative", headroom(30, 6, 32) == 0)
    chk("distribution: histogram is exact",
        distribution([0, 0, 3])["histogram"] == {"0": 2, "3": 1})
    chk("distribution: p50/p75/max on [0,0,3]",
        (distribution([0, 0, 3])["median"], distribution([0, 0, 3])["p75"],
         distribution([0, 0, 3])["max"]) == (0, 3, 3))

    print("SELF-TEST -- the pre-committed calibration rule")
    chk("coverage: knob 12 covers p50 of [1,12,13,14]", coverage_pct([1, 12, 13, 14], 12) == 50)
    chk("coverage: an empty demand list is p0, not a crash", coverage_pct([], 12) == 0)
    low = calibrate_knob([1, 2, 3, 4], PROVISIONAL_PER_SEED_BUDGET)
    chk("rule: demand below the provisional FLOORS at the provisional",
        low["calibrated"] == PROVISIONAL_PER_SEED_BUDGET and low["p75_demand"] == 3)
    chk("rule: a floored knob raises no ratification flag", low["ratification_flag"] is False)
    mid = calibrate_knob([20] * 10, PROVISIONAL_PER_SEED_BUDGET)
    chk("rule: p75 above the provisional RAISES the calibrated value",
        mid["calibrated"] == 20 and mid["ratification_flag"] is False)
    hot = calibrate_knob([25] * 10, PROVISIONAL_PER_SEED_BUDGET)
    chk("rule: p75 > 2x provisional sets the RATIFICATION FLAG (never an auto-raise)",
        hot["ratification_flag"] is True and hot["calibrated"] == 25)
    edge = calibrate_knob([24] * 10, PROVISIONAL_PER_SEED_BUDGET)
    chk("rule: exactly 2x provisional is INSIDE (flag is strictly greater-than)",
        edge["ratification_flag"] is False)
    res = calibrate_knob([7] * 10, PROVISIONAL_PER_SEED_RESERVE)
    chk("rule: the reserve knob flags at its own 2x (6), not the budget's",
        res["ratification_flag"] is True and res["calibrated"] == 7)
    cal = calibrate([12] * 4, [3] * 4)
    chk("calibrate: both knobs present, both at their provisional",
        cal["per_seed_budget"]["calibrated"] == 12 and cal["per_seed_reserve"]["calibrated"] == 3)

    print("SELF-TEST -- the no-verdict gate (finding 6)")
    chk("gate: --limit suppresses the calibration", (verdict_gate(20, 20, 327) or {}).get("no_verdict") is True)
    chk("gate: below MIN_POPULATION suppresses the calibration",
        (verdict_gate(MIN_POPULATION - 1, 0, 327) or {}).get("no_verdict") is True)
    chk("gate: a full population passes", verdict_gate(288, 0, 327) is None)

    print("SELF-TEST -- stratification (finding 3) + published per-seed aggregates (finding 2)")
    mk = lambda ns, cos, res: {                                                   # noqa: E731
        "n_seeds": ns, "node_budget": 12 * ns, "kept": sum(cos.values()),
        "per_seed_kept": cos, "per_contract_kept": cos, "unattributed_kept": 0,
        "per_seed_eligible": res, "per_contract_eligible": res, "eligible_capped": False,
        "end_of_walk_headroom": 0, "seed_scaled_saturated": True,
        "headroom_by_invocation": [0], "headroom_positive": False,
        "eligible_any": any(v > 0 for v in res.values()), "can_fire": False}
    rows = [mk(1, {"corn": 9}, {"corn": 1}), mk(1, {"corn": 11}, {"corn": 0}),
            mk(3, {"a": 20, "b": 21, "c": 22}, {"a": 4, "b": 5, "c": 6})]
    s = summarize(rows)
    chk("summarize: n_seeds histogram", s["n_seeds_histogram"] == {"1": 2, "3": 1})
    chk("summarize: pooled + per-stratum blocks both present",
        set(s["by_n_seeds"]) == {"1", "3"} and s["pooled"]["n_walks"] == 3)
    chk("summarize: a demand unit is (walk, seed), not a walk",
        s["pooled"]["per_seed_cosine_demand"]["n"] == 5)
    chk("summarize: the 1-seed stratum is NOT contaminated by the 3-seed rows",
        s["by_n_seeds"]["1"]["per_seed_cosine_demand"]["max"] == 11
        and s["by_n_seeds"]["3"]["per_seed_cosine_demand"]["min"] == 20)
    chk("summarize: a zero-demand seed stays IN the reserve distribution (instrument-dead, not lost)",
        s["pooled"]["per_seed_reserve_demand"]["n"] == 5
        and s["pooled"]["per_seed_reserve_demand"]["min"] == 0)
    chk("summarize: the pooled calibration would read p75 of the POOLED demand",
        calibrate_knob(demand_values(rows, "per_seed_kept"),
                       PROVISIONAL_PER_SEED_BUDGET)["p75_demand"] == 21)

    print("SELF-TEST -- base-arithmetic health, both directions (finding 5; per-boundary "
          "explanation per retrofit-review finding 2)")
    # hops_before_by_invocation stamps the hop-contract count AT each invocation; an inexact
    # boundary is explained only when its excess <= hops admitted BETWEEN the two stamps.
    good = [{"qid": "a", "kept_before_by_invocation": [1, 5], "base_n_by_invocation": [4, 1],
             "hops_before_by_invocation": [0, 0], "kept": 6, "n_hop_contracts": 1}]
    under = [{"qid": "b", "kept_before_by_invocation": [1, 5], "base_n_by_invocation": [9, 1],
              "hops_before_by_invocation": [0, 0], "kept": 6, "n_hop_contracts": 1}]
    # boundary 0->1 has excess 4 and 4 hops admitted between the stamps: EXPLAINED.
    over_ok = [{"qid": "c", "kept_before_by_invocation": [1, 9], "base_n_by_invocation": [4, 1],
                "hops_before_by_invocation": [0, 4], "kept": 10, "n_hop_contracts": 4}]
    # same excess, but the walk admitted hops ELSEWHERE (before invocation 0) -- the per-WALK
    # predicate would have excused this; the per-BOUNDARY one must not.
    over_bad = [{"qid": "d", "kept_before_by_invocation": [1, 9], "base_n_by_invocation": [4, 1],
                 "hops_before_by_invocation": [3, 3], "kept": 10, "n_hop_contracts": 3}]
    chk("base_arith: an exact population is ok", base_arith_health(good)["ok"] is True
        and base_arith_health(good)["exact_matches"] == 2)
    chk("base_arith: an UNDER-counting mirror is a violation", base_arith_health(under)["ok"] is False)
    chk("base_arith: an OVER-counting boundary is inexact, not a violation",
        base_arith_health(over_ok)["n_violations"] == 0
        and base_arith_health(over_ok)["inexact_walks"] == 1)
    chk("base_arith: inexact + admitted hops -> EXPLAINED, run proceeds",
        base_arith_health(over_ok)["ok"] is True
        and base_arith_health(over_ok)["unexplained_inexact_walks"] == 0)
    chk("base_arith: inexact + ZERO hops -> UNEXPLAINED below the floor, run aborts",
        base_arith_health(over_bad)["ok"] is False
        and base_arith_health(over_bad)["unexplained_inexact_walks"] == 1)
    chk("base_arith: exact_frac is published for the instrument line",
        base_arith_health(good)["exact_frac"] == 1.0)

    print("SELF-TEST -- the hook on a synthetic walk (no embedder, no S3)")
    try:
        _an, _ev, _gph, pl = _lev()
        drv, embed, build = _self_test_graph()
        # The at-knobs posture at budget 6: wave 1 leaves headroom, wave 2 then fills to exactly 6, so
        # PER-INVOCATION says "positive" and END-OF-WALK says "saturated". Kept as the diagnostic's
        # pin (round-3's worked case); no decision reads it any more.
        #   wave 0: the corn seed              -> kept 1
        #   wave 1: hop(wheat) + a,b,c         -> base 4, headroom 6-(1+4) = 1  (pa is tau-pruned)
        #   wave 2: wheat's w1                 -> base 1 (budget), headroom 6-(5+1) = 0; kept 6
        ds = [drv("a", 0.90, parents=["pa"]), drv("b", 0.80), drv("c", 0.70),
              drv("pa", 0.10)]                       # below tau -> only a reservation could reach it
        hop = {"wheat": [drv("w1", 0.90), drv("w2", 0.85), drv("w3", 0.80)]}
        graph = build(ds, hop)
        slices = ["a", "b", "c", "pa", "w1", "w2", "w3"]
        rec = Recorder()
        route = lambda q, g: ["corn"]                                          # noqa: E731
        rec.begin("worked_case")
        with census_hook(pl, rec, probe_n=128):
            sg = pl.grounded_subgraph("QQ", graph, depth=2, node_budget=6, max_seeds=1, tau=0.35,
                                      embed=embed, route_fn=route, closure_reserve=3,
                                      driver_slices=slices)
        invs = rec.end()
        chk("hook: two invocations (wave 0 has no d>0 driver)", len(invs) == 2, [i["headroom"] for i in invs])
        chk("hook: wave-1 per-invocation headroom == 1", invs and invs[0]["headroom"] == 1,
            invs[0] if invs else None)
        chk("hook: wave-2 per-invocation headroom == 0", len(invs) > 1 and invs[1]["headroom"] == 0,
            invs[1] if len(invs) > 1 else None)
        chk("hook: kept == budget -> END-OF-WALK headroom 0", len(sg.nodes) == 6, len(sg.nodes))
        chk("hook: the two diagnostics DISAGREE on this walk (the round-3 case)",
            any(i["headroom"] > 0 for i in invs) and (6 - len(sg.nodes)) == 0)
        chk("hook: eligibility found the tau-pruned backed ancestor",
            invs and invs[0]["n_eligible"] == 1 and invs[0]["eligible"][0]["id"] == "pa",
            invs[0]["eligible"] if invs else None)
        chk("hook: the probe cap did NOT bind at probe_n=128",
            all(i["eligible_capped"] is False for i in invs))
        chk("hook: nothing was reserved (the walk stays the OFF arm)",
            sg.trace["cascade_closure"]["reserved"] == []
            and sg.trace["cascade_closure"]["headroom_used"] == 0)
        chk("hook: base mirror agrees with the walk",
            invs[1]["kept_before"] == invs[0]["kept_before"] + invs[0]["base_n"]
            and len(sg.nodes) == invs[1]["kept_before"] + invs[1]["base_n"])

        # SEED ATTRIBUTION across a tracked hop: corn is the only seed, so wheat's nodes roll up to it.
        pc, ps, un, bd = aggregate_kept(sg.nodes, ["corn"])
        chk("attribution: per-CONTRACT grouping splits the hop out", pc == {"corn": 4, "wheat": 2}, pc)
        chk("attribution: per-SEED grouping rolls the hop UP to its seed", ps == {"corn": 6}, ps)
        chk("attribution: nothing unattributed at depth 2", un == 0)
        chk("attribution: kept_by_depth is published", bd == {"0": 1, "1": 4, "2": 1}, bd)
        ec, es, eu = aggregate_eligible(invs, sg.nodes, ["corn"])
        chk("attribution: eligible ancestors group per contract AND per seed",
            ec == {"corn": 1} and es == {"corn": 1} and eu == 0, (ec, es))

        # THE DEMAND ARM, on the same graph: uncapped, so tau is the only filter.
        rec_d = Recorder()
        rec_d.begin("demand")
        with census_hook(pl, rec_d, probe_n=128):
            sgd = pl.grounded_subgraph("QQ", graph, depth=2, node_budget=999, max_seeds=1, tau=0.35,
                                       embed=embed, route_fn=route, closure_reserve=3,
                                       driver_slices=slices)
        invs_d = rec_d.end()
        pcd, psd, _u, _b = aggregate_kept(sgd.nodes, ["corn"])
        chk("demand arm: the uncapped walk admits every tau survivor (8, not 6)", len(sgd.nodes) == 8,
            len(sgd.nodes))
        chk("demand arm: per-seed cosine DEMAND exceeds the at-knobs kept count",
            psd == {"corn": 8} and pcd == {"corn": 4, "wheat": 4}, (psd, pcd))
        chk("demand arm: headroom is positive by construction (a meaningless diagnostic here)",
            all(i["headroom"] > 0 for i in invs_d))
        chk("demand arm: tau still prunes -- pa never enters the kept set",
            all(k[2] != "pa" for k in sgd.trace["kept"]))

        # BYTE-IDENTITY vs the shipped OFF arm.
        ctl = pl.grounded_subgraph("QQ", graph, depth=2, node_budget=6, max_seeds=1, tau=0.35,
                                   embed=embed, route_fn=route, closure_reserve=0,
                                   driver_slices=slices)
        chk("hook: kept/pruned identical to closure_reserve=0",
            ctl.trace["kept"] == sg.trace["kept"] and ctl.trace["pruned"] == sg.trace["pruned"])
        chk("hook: _closure_plan restored after the context exits",
            tuple(inspect.signature(pl._closure_plan).parameters) == _CLOSURE_PLAN_PARAMS)

        # SATURATED: a wide wave-1 with no parents -- headroom 0 at every invocation, and NO
        # eligible ancestor (nothing has parents), i.e. the (headroom=0, ancestors=0) cell.
        ds2 = [drv("f%d" % i, 0.9 - i * 0.01) for i in range(12)]
        rec2 = Recorder()
        rec2.begin("saturated")
        with census_hook(pl, rec2, probe_n=128):
            sg2 = pl.grounded_subgraph("QQ", build(ds2), depth=2, node_budget=6, max_seeds=1, tau=0.35,
                                       embed=embed, route_fn=route, closure_reserve=3,
                                       driver_slices=["f%d" % i for i in range(12)])
        i2 = rec2.end()
        chk("hook: saturated wave -> headroom 0", i2 and all(x["headroom"] == 0 for x in i2),
            [x["headroom"] for x in i2])
        chk("hook: no parents -> eligible 0 (scarcity, separable from saturation)",
            i2 and all(x["n_eligible"] == 0 for x in i2))
        chk("hook: saturated walk filled the budget", len(sg2.nodes) == 6)

        # ELIGIBILITY vs BACKEDNESS: the worked-case graph with `pa` NOT backed. Same headroom, zero
        # eligibility -- the (headroom>0, ancestors=0) cell, whose fix is curation, not a budget.
        rec3 = Recorder()
        rec3.begin("unbacked")
        with census_hook(pl, rec3, probe_n=128):
            pl.grounded_subgraph("QQ", graph, depth=2, node_budget=6, max_seeds=1, tau=0.35,
                                 embed=embed, route_fn=route, closure_reserve=3,
                                 driver_slices=["a", "b", "c", "w1", "w2", "w3"])
        i3 = rec3.end()
        chk("hook: unbacked ancestor -> eligible 0 while headroom stays 1",
            i3 and i3[0]["n_eligible"] == 0 and i3[0]["headroom"] == 1,
            [(x["headroom"], x["n_eligible"]) for x in i3])
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        chk("hook: synthetic walk ran", False, exc)

    print("")
    print("SELF-TEST: %s (%d check(s) failed)" % ("PASS" if not fails else "FAIL", len(fails)))
    return 0 if not fails else 3


def build_parser() -> argparse.ArgumentParser:
    """Split out of main() so the DEFAULTS are unit-testable. Two of them are load-bearing corrections
    (findings 1 and 4): --max-seeds is the R7 ceiling 6, and --hop-fence is ON."""
    ap = argparse.ArgumentParser(
        description="D-MW-15 STEP-0 [R7-FINAL] calibration census: per-seed cosine demand (sizes "
                    "per_seed_budget) and per-seed eligible-ancestor demand (sizes per_seed_reserve), "
                    "stratified by realized seed count over the routed deck.")
    ap.add_argument("--decks", default=None,
                    help="csv of deck stems/paths, or 'all' (default: every configs/graphrag/eval_queries*.yaml "
                         "-- the population the prior 288-walk census used)")
    ap.add_argument("--arms", default=",".join(DEFAULT_ARMS),
                    help="csv of %s (default %s; `flat` is the retired pre-R7 continuity control)"
                         % (",".join(ARMS), ",".join(DEFAULT_ARMS)))
    ap.add_argument("--demand-budget", type=int, default=DEFAULT_DEMAND_BUDGET,
                    help="the `demand` arm's node_budget: high enough that tau is the only filter")
    ap.add_argument("--node-budget", type=int, default=DEFAULT_FLAT_BUDGET,
                    help="the `flat` continuity-control arm's node_budget (PRE-R7 SHAPE)")
    ap.add_argument("--max-seeds", type=int, default=DEFAULT_SEED_CEILING,
                    help="the R7 TIER CEILING (max=6). Multi-market deck rows must express full "
                         "cardinality or the per-seed distributions are measured on a truncated seed set.")
    ap.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    ap.add_argument("--tau", type=float, default=None, help="walk tau (default: planner's serving value)")
    ap.add_argument("--reserve-n", type=int, default=DEFAULT_RESERVE_N,
                    help="closure_reserve: opens the invocation gate (nothing is ever actually reserved)")
    ap.add_argument("--eligible-probe-n", type=int, default=DEFAULT_PROBE_N,
                    help="cap on ancestors counted per invocation by the eligibility probe; a bound cap "
                         "is flagged per walk as eligible_capped")
    ap.add_argument("--router", choices=("lexical", "semantic"), default="lexical")
    ap.add_argument("--hop-fence", choices=("on", "off"), default="on",
                    help="on (default) = D-MW-13's second-order-hop fence, which ships with the preset on "
                         "BOTH P3-A arms; off = the unfenced walk, as the sensitivity arm")
    ap.add_argument("--limit", type=int, default=0,
                    help="dev: first N questions only. SUPPRESSES the calibration line (finding 6).")
    ap.add_argument("--parity-sample", type=int, default=DEFAULT_PARITY_SAMPLE,
                    help="paired control walks proving the hook is a no-op (0=off, -1=all)")
    ap.add_argument("--allow-no-evidence-store", action="store_true",
                    help="run without EVIDENCE_S3/pg (recorded in the report; the embedder fence stays)")
    ap.add_argument("--json", dest="json_out", default=None, help="write the JSON report here")
    ap.add_argument("--self-test", action="store_true", help="arithmetic + hook on a synthetic graph; no network")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.self_test:
        return self_test()
    if args.tau is None:
        _an, _ev, _gph, pl = _lev()
        args.tau = pl._TAU
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
