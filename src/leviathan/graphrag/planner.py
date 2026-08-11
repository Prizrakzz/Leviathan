"""L2 structured multi-hop — a deterministic grounded-subgraph walk over the curated causal DAG (GraphRAG v2).

Replaces answer()'s one-hop "route -> dump text -> one LLM call" with a query-conditioned frontier walk: seed on
the routed contract(s), expand across driver fan-in (`Driver.parents`) and TRACKED inter-commodity edges to
`depth`, and keep a node only if cos(query, its mechanism) >= `tau` (seeds always kept) within `node_budget`.

The WALK is deterministic (WHICH nodes/hops the answer covers) — it follows the curated edges instead of letting
the LLM improvise the causal path, so the answer's causal skeleton is guaranteed to match the vetted graph.
Retrieval (WHAT evidence) and the reasoner (HOW it reads) stay generative — see `ground()` (evidence + silver +
convergence) and answer(planner="l2"). This module is the pure core: only `embed` is external, and it's injectable,
so the traversal / prune / budget logic is unit-testable with no S3, no Athena, no LLM.

WS-1 here = the walk + prior leg + mermaid + trace. The I/O legs (evidence, silver, convergence firing) land in
`ground()` (WS-2/4/5)."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as gph
from leviathan.graphrag import params as _pr

# Serving knobs read from params.yaml (section 9.1: no knob hardcoded); the literals here are the
# authoritative fallbacks for a public clone without the private config.
_TAU = float(_pr.get("serving.walk.tau", 0.35))
_NODE_BUDGET = int(_pr.get("serving.walk.node_budget", 10))
_DEPTH = int(_pr.get("serving.walk.depth", 2))
_MAX_SEEDS = int(_pr.get("serving.walk.max_seeds", 2))
_RECENCY_DAYS = int(_pr.get("serving.ground.recency_days", 548))
# The walk's per-node retrieves run concurrently to overlap the managed-rerank round-trips (env override wins).
_WALK_WORKERS = int(os.environ.get("GRAPHRAG_WALK_WORKERS") or _pr.get("serving.walk.workers", 8))
_PROBE_CAP = int(_pr.get("serving.ground.probe_cap", 24))
# D-MW-14: THE CEILING ON _parallel_fill's HINT-SATISFIABILITY WIDENING. That widening exists so the rerank
# coalescer's promised batch can physically arrive (a worker frees only when its rerank resolves), and it
# was measured when the widest preset was deep at node_budget 16 -- a ~24-thread ceiling. The seed-scaled
# budget moved the same expression to ~252 threads at 4 realized seeds and ~378 at the 6-seed ceiling, on a
# 4-vCPU serving task whose SQL still queues on EVIDENCE_PG_POOL: a fan-out never measured and 16x anything
# the mechanism has run at. 64 is a hard cap on the WIDENED pool only -- every shipped width (<= ~48 nodes)
# is unchanged by construction, so P3-B still measures the widening's real wall clock.
MAX_FILL_POOL = 64
# Convergence probes (F3) run concurrently at this width. They were the whole of the walk's `rest` stage:
# 24 STRICTLY SERIAL pg round-trips at 596-682 ms each, serial-sum == wall to within 0.3% on 4/4 measured
# turns. They are independent existence checks, so overlapping them is pure win. Default matches the walk's
# own width; effective concurrency is min(this, EVIDENCE_PG_POOL) because the probes draw from that pool, so
# raising it past the pool size only queues on checkout. <=1 forces the old sequential path (kill-switch).
_PROBE_WORKERS = int(os.environ.get("GRAPHRAG_PROBE_WORKERS") or _pr.get("serving.ground.probe_workers",
                                                                        _WALK_WORKERS))
_EVIDENCE_CAP = int(_pr.get("serving.ground.evidence_cap", 24))
_K_BY_DEPTH = tuple(_pr.get("serving.ground.k_by_depth", (5, 3, 2)))

# ── D-GD-1 (2026-08-08) CASCADE-CLOSURE RESERVATION ──────────────────────────────────────────────────────────
# N slots of the walk's EXISTING budget are reserved, inside the wave that admits them, for the BACKED
# ANCESTORS of the top-ranked admitted drivers — admitted at the anchor's own depth, decided OUTSIDE the
# hop-first comparator (line 160) so a tracked hop can never eat the reservation, and PAID FOR by displacing
# the lowest-ranked admitted drivers of that same wave. Same node count, same k, same evidence_cap: the
# reservation REPLACES cosine admissions, it never adds one.
#
# WHY THIS SHAPE AND NOT A DEPTH KNOB (docs/private/recon/dgd-walk-admission.md V1/V3, dgd-graph-depth-
# structure.md S1.2, dgd-chain-instruments.md V1): a driver's depth-2 route is its `.parents`, the schema
# forces every parent to be a driver id of the SAME contract, and the walk enqueues EVERY driver of a
# contract into wave 1 — so 1026/1026 parent edges point at a node that is ALREADY a wave-1 candidate and
# already `visited`-stamped. Measured new depth-2 driver nodes from the seed fan-in: 0 in 33 of 33 DAGs at
# any budget. The hierarchy is real (1,026 parent edges, 573/1,112 drivers parented, chains 3-8 deep) and it
# is invisible to a flat cos(query, mechanism) sort over 24-45 siblings. This is therefore an ADMISSION-SORT
# change, not a depth change, and `reasoning_modes` keeping deep pinned at depth=1 is CORRECT under it.
#
# PRECEDENT: answer._answer_l2's `focus_driver` force-inject (answer.py:1876-1884) is the same move done
# post-walk with no budget accounted for; this one is done inside the walk and pays for its slots.
_CLOSURE_RESERVE = int(_pr.get("serving.walk.closure_reserve", 3))

# ── D-MW-15 (2026-08-11) ADMISSION-REASON VOCABULARY — ONE PRODUCER ──────────────────────────────────────────
# The reason strings were literals in five places (the admissions stamp, the 1-row score floor, the cap-order
# anchor-adjacency move, the census exclusion, and the eval join). A second STRUCTURAL reason
# (`cascade_downstream`) would have silently bypassed all three guards and landed a node with ZERO evidence
# rows — the exact admitted-but-not-cited defect class P3-A exists to prove fixed — so the guards are now
# MEMBERSHIP TESTS on `_STRUCTURAL_REASONS` and every literal is minted from these constants.
REASON_COSINE = "cosine"
REASON_CLOSURE = "closure_reservation"          # upstream: an ancestor of an admitted driver
REASON_DOWNSTREAM = "cascade_downstream"        # downstream: a descendant, i.e. structural RE-admission
# Admitted for STRUCTURE, not for cosine: tau-exempt, relevance-floor-protected, cap-order-protected, and
# EXCLUDED from the closure census population (recorded decision, D-MW-15: downstream children are not
# ancestors; counting them would redefine the open/closed denominator mid-instrument).
_STRUCTURAL_REASONS: frozenset = frozenset({REASON_CLOSURE, REASON_DOWNSTREAM})
# The admission record every kept node carries (GroundedNode.admission + trace.cascade_closure.admissions).
# A d==0 SEED carries this too: the walk admits seeds by fiat at relevance 1.0, and the node's own `depth`
# already says so — the enum stays the values the D-GD-3 counter is written against, plus the D-MW-15 pair.
_ADMIT_COSINE = {"reason": REASON_COSINE, "ancestor_of": None, "chain_depth": 0}


def _closure_group_key(chain_depth, id_) -> tuple:
    """THE ONE ordering of a reserved group hanging off a single anchor: |chain_depth| (nearest LINK first,
    in EITHER cascade direction), then id.

    ONE PRODUCER, TWO CONSUMERS -- `_closure_plan`'s seq insertion (walk emission order) and
    `_closure_cap_order` (evidence-cap order). They must agree: a group is emitted next to its anchor so it
    draws cap budget as that driver's peer, and if the two orders disagreed the cap's tail-trim would fall
    on a different member of the group than the walk's own order implies. They DID disagree after admission
    v2 (P3 round-1): cap order sorted by abs(), seq by the RAW depth, so a downstream node at -1 sorted
    ahead of an upstream node at +2 in one place and behind it in the other. Upstream-only groups are
    unaffected either way (every chain_depth is positive, abs() is the identity), which is why the shipped
    D-GD pins stay green byte for byte."""
    return (abs(int(chain_depth or 0)), str(id_))


# ── edge-category map (code-level; NO YAML re-curation) ──────────────────────────────────────────────────────
# Classifies the EXISTING relation/edge_type vocabulary so grounding expectations differ by kind:
#   transformation  = accounting identities (a crush margin exists by construction) -> true WITHOUT dated
#                     evidence; never counts against leg-grounding.
#   market_structure= substitution/competition links -> probabilistic but market-level.
#   causal          = physical/economic cause-effect (weather->yield) -> the kind that NEEDS dated evidence.
_EDGE_CATEGORY = {
    "crushed_into": "transformation", "feedstock_for": "transformation", "processed_into": "transformation",
    "produces": "transformation", "byproduct_of": "transformation", "co_product_of": "transformation",
    "substitutes_for": "market_structure", "competes_with": "market_structure",
    "leads_lags": "market_structure", "hedged_with": "market_structure",
}


def edge_category(relation: str) -> str:
    return _EDGE_CATEGORY.get(relation or "", "causal")


@dataclass
class GroundedNode:
    kind: str                                   # "contract" | "driver"
    id: str                                     # contract id (contract node) or driver id (driver node)
    contract: str                               # owning contract (== id for a contract node)
    depth: int
    relevance: float                            # cos(query, mechanism); 1.0 for a seed
    prior: dict = field(default_factory=dict)   # sign/lag/mechanism/confidence (driver) or target/edge (contract)
    evidence: list = field(default_factory=list)     # dated props (filled by ground())
    silver: Optional[dict] = None               # {ref,value,unit,knowledge_date,live} or {ref,live:False}
    active: bool = False                        # driver "active" = evidence leg non-empty near the episode
    via_edge: Optional[dict] = None             # the inter-commodity edge that reached this contract node
    episodes: list = field(default_factory=list)     # PIT-filtered dated episodes (timeline layer)
    # D-GD-1: WHY this node was admitted — {reason: cosine|closure_reservation|focus_driver,
    # ancestor_of: <the driver whose chain earned the slot, or None>, chain_depth: <int, 0 when N/A>}.
    # Observational only: nothing in the render, the prompt, the verifier or the footer reads it. It is
    # what makes an admission decision AUDITABLE from an artifact (it rides trace.cascade_closure.admissions
    # -> tracekeys -> every eval per-answer record).
    admission: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple:
        return (self.kind, self.contract, self.id)


@dataclass
class Subgraph:
    seeds: list[str]
    nodes: list[GroundedNode]
    fired_regimes: list[dict] = field(default_factory=list)
    mermaid: str = ""
    trace: dict = field(default_factory=dict)

    def by_contract(self, cid: str) -> list[GroundedNode]:
        return [n for n in self.nodes if n.contract == cid]


def _relevance(qv, text: str, embed, cache: dict) -> float:
    if not text:
        return 0.0
    if text not in cache:
        cache[text] = embed([text])[0]
    return ev._cosine(qv, cache[text])


def _seed_contracts(query, graph, route_fn, max_seeds: int) -> list[str]:
    """Route, then keep distinct commodity NODES (siblings share an evidence slice) — mirrors answer()."""
    seeds, seen = [], set()
    for c in route_fn(query, graph):
        if c not in graph.contracts:
            continue
        nd = ev.node_for(c)
        if nd in seen:
            continue
        seen.add(nd)
        seeds.append(c)
        if len(seeds) >= max_seeds:
            break
    return seeds


def _closure_reserve_n(explicit: int | None = None) -> int:
    """D-GD-1: the reservation SIZE for this walk. DEFAULT OFF (0) — the D-GD-3 A/B is what flips it.

    `explicit` (the kwarg) wins outright and reads no environment: the test + eval-arm seam.
    Otherwise `GRAPHRAG_CLOSURE_RESERVE`:
      absent / '' / off / false / no / 0  -> 0, i.e. the shipped walk byte for byte
      on / true / yes                     -> params `serving.walk.closure_reserve` (3)
      an INTEGER                          -> that size, so N is sweepable with no code change

    '1' therefore means RESERVE ONE, not "on". This knob carries a MAGNITUDE, so the house
    ("on","1","true") boolean idiom would make the only interesting small value unreachable; the
    boolean words are still accepted so the flip stays a one-word env change. Anything unparseable
    resolves to 0 — fail-CLOSED, because a typo must never silently change which nodes a desk turn saw."""
    if explicit is not None:
        return max(0, int(explicit))
    v = (os.environ.get("GRAPHRAG_CLOSURE_RESERVE") or "").strip().lower()
    if v in ("", "off", "false", "no"):
        return 0
    if v in ("on", "true", "yes"):
        return max(0, _CLOSURE_RESERVE)
    try:
        return max(0, int(v))
    except ValueError:
        return 0


def _driver_slice_resolvers(driver_slices=None):
    """(backed_ids, slice_path_fn) for the WALK — the same two-mode seam `ground()` already carries, so a
    hermetic test injects one set and gets identical semantics on both sides of the walk/ground line.

    `driver_slices` given -> the id IS its own slice path (tests). None -> the curated alias map.
    A broken/absent alias config degrades to "nothing is backed", which makes the reservation a strict
    no-op rather than a walk that fails: an observational fence can never be allowed to kill a turn."""
    if driver_slices is not None:
        backed = set(driver_slices)
        return backed, (lambda did: f"drivers/{did}")
    try:
        backed = ev.backed_dag_ids()
    except Exception:  # noqa: BLE001 — config gone -> no reservation, never a dead walk
        return set(), (lambda did: None)

    def _sp(did):
        s = ev.slice_for_driver(did)
        return f"drivers/{s}" if s else None
    return backed, _sp


def _closure_plan(scored: list, kept: dict, graph: gph.CausalGraph, *, node_budget: int, reserve_n: int,
                  backed: set, slice_of_driver, wave_pruned: dict, protect_ids: frozenset = frozenset(),
                  slots_by_origin: dict | None = None, origin_of_contract: dict | None = None,
                  score_of=None, n_charged: int | None = None) -> Optional[dict]:
    """Decide ONE wave's cascade-closure reservation. PURE (no I/O): it reads only the wave's already-scored
    candidates, the kept set, the curated DAG — and, in ADMISSION V2, an injected `score_of` that resolves
    cos(query, mechanism) off the walk's OWN `_relevance` cache (no second embedder, no second cache).

    Returns None when nothing is reserved — and the caller then runs the SHIPPED admission verbatim, which
    is the whole of the byte-identity guarantee for the OFF arm and for the flag-on-but-nothing-eligible
    case. Otherwise: {seq, final, displaced, displaced_rec, reserved, skipped, admissions, tau_release}.

    THE FOUR RULES, each with the measurement that forced it:
      1. ELIGIBILITY = BACKED **and** SLICE-DISTINCT. 23.1% of the estate's 1,026 parent edges reach a DARK
         parent (no slice -> a prior-only node that can never be cited) and 4.2% reach a parent resolving to
         the SAME slice as a node already in the walk, where `_dedup_and_cap` collapses it to zero rows
         (recon V6). Without both filters ~1 slot in 4 buys a node that cannot be cited.
      2. NEAREST-PARENT-FIRST, anchored on the RANK-ORDERED admitted drivers. N=3 then closes the median
         chain (closure median 2, mean 3.58) whole before spilling to the second-best driver's chain.
      3. TAU-EXEMPT, and the ledger stays a PARTITION. An ancestor admitted for structural reasons may score
         below the relevance floor on its own mechanism — exempting it is the point of the fix. The wave's
         own `tau` entry for that key is RELEASED (returned in `tau_release`) rather than left beside the
         admission, so every key still carries exactly ONE decision and `visited` still stamps it exactly
         once. This is why the reservation is WAVE-LOCAL: it never reaches back into an earlier wave's
         tombstones, so the visited-before-tau aggravator the recon flagged stays untouched.
      4. HEADROOM FIRST, DISPLACE ONLY FOR THE REMAINDER; the CEILING is the invariant, not the count.
         REVIEW FIX (D-GD-1 R1 #1, 2026-08-08): v1 displaced UNCONDITIONALLY, so it paid for every slot
         whether or not the wave had a spare one to give. Headroom-first remains the right shape — the
         CEILING is the invariant, and spending an unspent slot is strictly cheaper than deleting a
         cosine-admitted driver — but THE NUMBERS THAT MOTIVATED IT WERE A SIM ARTIFACT, corrected here
         (D-MW-11; measurement in GUIDED_DEPTH_V2_PLAN.md:141-170). The R1 sweep ran a DETERMINISTIC HASH
         embedder, which centres mechanism cosines on 0.0, so 100% of candidates fell below tau=0.35, tau
         ate every wave and the budget never bound: "0 of 198 walks ever FILLED node_budget" was a property
         of the fake embedder, not of the walk. Re-measured with the REAL bge-m3 on the same population,
         same code, same knobs, it is the OPPOSITE: real mechanism cosines sit in a narrow band above the
         floor (pruned-candidate relevance p10 0.314 / median 0.370 / p90 0.443, only 32.4% below tau), so
         the BUDGET is what ends the walk — 288 of 288 routed-deck walks FILL node_budget at the deep knobs
         (192 of 198 on the 6-queries-per-contract population), 0.0% of reserved slots are paid by headroom,
         and the reservation is ~100% SUBSTITUTION in practice. Tau-survivors per deep walk are min 8 /
         p25 25 / median 31 / p75 36 / max 49, so headroom on the median walk needs node_budget >= 32: a
         WIDTH decision (D-MW P3), not a knob away.
         So: `headroom = node_budget - (len(kept) + len(base))` is spent FIRST and additively; only the
         remainder displaces the lowest-ranked admitted drivers (never a seed, never a tracked hop — the
         hop-first comparator is deliberately untouched; never an ANCHOR of this same reservation nor ANY
         driver on an anchor's ancestor chain, which would orphan the chain it earned, R1 #4; never the
         turn's `focus_driver`, whose post-walk re-inject would otherwise re-add it on the ON arm only,
         R1 #5). If the wave cannot pay for the remainder, the reservation is TRIMMED. The invariant that
         actually matters is `len(kept) <= node_budget` — the WALK's own law — and headroom-first satisfies
         it BY CONSTRUCTION. (It used to be justified as "the 17-node `_COALESCE_MAX_DOCS` rerank cliff".
         That cliff is the BEDROCK lane's: 17 x pool-60 = 1,020 docs = a second draw on a 3/min
         non-adjustable bucket. On the native cohere lane, 1,000 req/min, chunk count is a request-shape
         detail — D-MW-11 — so the budget is defended AS A BUDGET, not as a quota.) `count_delta =
         reserved - displaced - headroom_used` stays assertable at 0 as the accounting proof.

         NOTE, CORRECTED (D-MW-11): the R1 record's "with headroom-first the ON arm is genuinely ADDITIVE
         on most walks" describes the hash-embedder SIM, not the product. On the real embedder 0 of 288
         routed-deck walks take ANY additive admission, so the ON arm is what v1 claimed to be — the same
         slots, differently chosen — and the D-GD-3 adjudication reads it that way.

    ── ADMISSION V2 (D-MW-15, 2026-08-11) — the DEDICATED-SLOT mode, on this same chassis ──────────────────
    `slots_by_origin` (a per-SEED slot ledger, from `per_seed_reserve x realized seeds`) switches four
    things and NOTHING else; when it is None every line below is the v1 shipped path byte for byte.
      (i)   DEDICATED SLOTS, ADDITIVE BY CONSTRUCTION. Rule 4's headroom/displacement negotiation is not
            reached: cosine admission fills the per-seed COSINE allocation, graph admission fills the
            per-seed RESERVE, and neither can displace the other. This is the doctrine's "node budget must
            never bind" implemented directly instead of negotiated per walk. The STEP-0 census (plan 12a)
            calibrated the sizes: per-seed cosine demand p75 = 63, eligible-ancestor supply p75 = 4.
      (ii)  PER-SEED OWNERSHIP. A candidate's origin is its contract's SEED LINEAGE, so seed A's ancestors
            can only ever consume seed A's slots. Unfillable slots stay EMPTY — instrument-dead, declared
            in `reserve_slots`, NEVER backfilled with cosine (backfilling would re-create the very
            substitution the dedicated slots exist to remove).
      (iii) QUERY-SCORED SELECTION. Eligible candidates are ordered by cos(query, mechanism) — v1 ordered
            by chain position within a rank-ordered anchor list, which mis-targeted the slot at whatever
            the nearest parent happened to be. UPSTREAM is still taken before DOWNSTREAM (the gate headline
            reads the upstream counter; a flood of re-admitted siblings may not starve it), and within
            each direction the query decides. Ties break on |chain_depth| then id — deterministic.
      (iv)  DOWNSTREAM ADMISSION (reason `cascade_downstream`, negative chain_depth). Honest framing per
            the plan: within-contract children are ALREADY wave-1 candidates, so this is structural
            RE-ADMISSION of siblings tau or the budget dropped — visible as such in the audit trail.
      (v)   CONVERGENCE TAGGING. A candidate reachable from >= 2 distinct admitted anchors' chains carries
            {convergence: True, anchors: [...]} in its admission record and is counted in
            `trace.cascade_closure.n_convergence`. Prose surfacing stays with D-HP; here it feeds the audit
            trail, the census and the eval join.
    Rules 1-3 (eligibility, tau-exemption + the tombstone release, the ledger-is-a-partition law) and the
    chain-root protection fence are UNCHANGED — v2 is a payment + ordering change, not a new mechanism."""
    dedicated = slots_by_origin is not None
    _origin_of = origin_of_contract or {}
    # (1) what the SHIPPED rule would admit, in rank order — the baseline this plan may not out-count.
    # `n_charged` is the count of kept nodes that are CHARGED to the cosine budget; it differs from
    # len(kept) only in v2, where dedicated-slot admissions are additive and therefore charged to nothing.
    base, n = [], (len(kept) if n_charged is None else n_charged)
    for e in scored:
        if e[5] > 0 and n >= node_budget:
            continue
        base.append(e)
        n += 1
    base_keys = {e[7] for e in base}
    # (2) slices the walk already covers: a reserved ancestor resolving to one of them retrieves the same
    #     rows under a different name and the cross-node dedup zeroes it. Read PRE-displacement, so a slice
    #     held only by a node this plan is about to displace still blocks -- deliberately CONSERVATIVE: the
    #     displaced set is not decided until step (4), and erring toward "skip" can only ever leave a slot
    #     with the shipped cosine admission, never spend one on a node that cannot be cited.
    covered = {sp for nd in kept.values() if nd.kind == "driver"
               for sp in (slice_of_driver(nd.id),) if sp}
    covered |= {sp for e in base if e[3] == "driver"
                for sp in (slice_of_driver(e[2]),) if sp}
    reserved: list[dict] = []
    skipped: list[dict] = []
    chains: dict = {}                                       # (contract, anchor) -> its FULL ancestor chain
    res_keys_seen: set = set()

    def _eligible(a: str, cid: str, anchor: str):
        """RULE 1, one producer for both selection modes: a slot may only ever buy a node that can actually
        be CITED. Returns (key, slice_path) or (None, None) after recording WHY it was skipped."""
        key = ("driver", cid, a)
        if key in base_keys or key in kept or key in res_keys_seen:
            skipped.append({"id": a, "of": anchor, "reason": "already_admitted"})
            return None, None
        if a not in backed:
            skipped.append({"id": a, "of": anchor, "reason": "unbacked"})
            return None, None
        sp = slice_of_driver(a)
        if not sp:
            skipped.append({"id": a, "of": anchor, "reason": "no_slice"})
            return None, None
        if sp in covered:
            skipped.append({"id": a, "of": anchor, "reason": "same_slice"})
            return None, None
        return key, sp

    slots: dict = dict(slots_by_origin or {})
    slots_used: dict = {}
    if not dedicated:
        for e in base:                                      # rank order: strongest admitted driver first
            if len(reserved) >= reserve_n:
                break
            if e[3] != "driver" or e[5] <= 0:
                continue
            cid, anchor = e[4], e[2]
            try:
                chain = graph.ancestors_by_depth(cid, anchor)
            except Exception:  # noqa: BLE001 — an unindexed driver must not fail the walk
                continue
            for a, cdepth in sorted(chain.items(), key=lambda kv: (kv[1], kv[0])):
                if len(reserved) >= reserve_n:
                    break
                key, sp = _eligible(a, cid, anchor)
                if key is None:
                    continue
                covered.add(sp)
                chains[(cid, anchor)] = chain
                res_keys_seen.add(key)
                reserved.append({"key": list(key), "contract": cid, "ancestor_of": anchor,
                                 "chain_depth": int(cdepth), "slice": sp, "depth": e[5],
                                 "reason": REASON_CLOSURE})
    else:
        # ── V2 (i)-(v): one candidate pool per wave, query-scored, spent out of PER-SEED dedicated slots ──
        cands: dict = {}
        for e in base:                                      # anchors in rank order (it decides ancestor_of)
            if e[3] != "driver" or e[5] <= 0:
                continue
            cid, anchor = e[4], e[2]
            try:
                chain = graph.ancestors_by_depth(cid, anchor)
            except Exception:  # noqa: BLE001 — an unindexed driver must not fail the walk
                chain = {}
            try:
                kids = graph.descendants_by_depth(cid, anchor)
            except Exception:  # noqa: BLE001 — ditto, and downstream is the additive leg: never fail on it
                kids = {}
            chains[(cid, anchor)] = chain
            for a, cdepth in list(chain.items()) + list(kids.items()):
                r = cands.get((cid, a))
                if r is None:
                    r = cands[(cid, a)] = {"id": a, "contract": cid, "anchor": anchor, "anchors": [],
                                           "up": None, "down": None, "depth": e[5]}
                if anchor not in r["anchors"]:
                    r["anchors"].append(anchor)             # (v) convergence evidence, in anchor-rank order
                side = "up" if int(cdepth) > 0 else "down"
                if r[side] is None or abs(int(cdepth)) < abs(r[side]):
                    r[side] = int(cdepth)

        def _score(r) -> float:
            if score_of is None:
                return 0.0
            try:
                return float(score_of(r["contract"], r["id"]))
            except Exception:  # noqa: BLE001 — a scoring miss orders it last, it never kills the walk
                return 0.0
        # (iii) UPSTREAM block before DOWNSTREAM block; the QUERY decides inside each.
        ordered = sorted(cands.values(),
                         key=lambda r: (0 if r["up"] is not None else 1, -round(_score(r), 6),
                                        abs(r["up"] if r["up"] is not None else r["down"]), r["id"]))
        for r in ordered:
            cid, a, anchor = r["contract"], r["id"], r["anchor"]
            origin = _origin_of.get(cid, cid)               # (ii) the seed lineage that OWNS the slot
            if len(reserved) >= reserve_n:
                break
            key, sp = _eligible(a, cid, anchor)
            if key is None:
                continue
            if slots.get(origin, 0) <= 0:                   # ELIGIBLE but this seed's slots are spent --
                skipped.append({"id": a, "of": anchor,      # recorded as its own reason: a supply-vs-slot
                                "reason": "no_slot", "origin": origin})   # read the census needs separable
                continue
            covered.add(sp)
            res_keys_seen.add(key)
            slots[origin] -= 1
            slots_used[origin] = slots_used.get(origin, 0) + 1
            cdepth = r["up"] if r["up"] is not None else r["down"]
            rec = {"key": list(key), "contract": cid, "ancestor_of": anchor, "chain_depth": int(cdepth),
                   "slice": sp, "depth": r["depth"], "origin": origin,
                   "reason": REASON_CLOSURE if r["up"] is not None else REASON_DOWNSTREAM,
                   "relevance_q": round(_score(r), 4)}
            if len(r["anchors"]) >= 2:                      # (v) reachable from >= 2 admitted anchors' chains
                rec["convergence"], rec["anchors"] = True, list(r["anchors"])
            reserved.append(rec)
    if not reserved:
        return None
    # (4) PAY FOR IT — HEADROOM FIRST (R1 #1), then the lowest-ranked admitted drivers.
    # `base` is what the shipped rule would admit this wave, so `n` (charged-before + len(base), by the
    # loop above) is the OFF arm's node count at the end of it; anything left under node_budget is a slot
    # NOBODY was going to use.
    # V2: NOT REACHED. Dedicated slots are additive by construction — `need` is 0, nothing is displaced,
    # and the accounting identity below becomes `reserved == dedicated_used` instead of
    # `reserved == displaced + headroom_used`. Both are the same law: no slot ever comes from nowhere.
    headroom = 0 if dedicated else max(0, node_budget - n)      # n == charged + len(base), by the loop above
    headroom_used = min(len(reserved), headroom)
    need = 0 if dedicated else (len(reserved) - headroom_used)
    # PROTECTED from displacement: every anchor, every driver on an anchor's FULL ancestor chain (R1 #4 —
    # an interior parent that was already cosine-admitted is skipped `already_admitted` above and would
    # otherwise become the lowest-ranked displaceable driver, deleting the very link that earned the
    # grandparent), and the turn's focus_driver (R1 #5 — answer.py re-injects it post-walk with no budget
    # accounting, which would push the ON arm past the ceiling on the ON arm only).
    anchors = {(r["contract"], r["ancestor_of"]) for r in reserved}
    protected = set(anchors) | {(cid, a) for (cid, anchor) in anchors
                                for a in chains.get((cid, anchor)) or ()}
    displaceable = [e for e in reversed(base)
                    if e[3] == "driver" and e[5] > 0 and (e[4], e[2]) not in protected
                    and e[2] not in protect_ids]
    displaced = displaceable[:need]
    if len(displaced) < need:                                # trimmed, never overdrawn
        reserved = reserved[:headroom_used + len(displaced)]
        headroom_used = min(headroom_used, len(reserved))
    if not reserved:
        return None
    disp_keys = {e[7] for e in displaced}
    # (3) build each reserved node's scored entry: a tau SURVIVOR reuses its own (the budget dropped it),
    #     a tau-PRUNED sibling is rebuilt at the anchor's depth with the relevance the wave already scored.
    by_key = {e[7]: e for e in scored}
    tau_release: list[dict] = []
    for r in reserved:
        key = tuple(r["key"])
        e = by_key.get(key)
        if e is not None:
            r["_entry"], r["relevance"], r["tau_exempt"] = e, e[1], False
            continue
        rec = wave_pruned.get(key)
        rel = rec[0] if rec else 0.0
        r["relevance"], r["tau_exempt"] = rel, True
        r["_entry"] = (0, rel, key[2], "driver", key[1], r["depth"], None, key)
        if rec:
            tau_release.append(rec[1])
    res_keys = {tuple(r["key"]) for r in reserved}
    ins: dict = {}
    for r in reserved:                                       # each chain hangs off the driver that earned it
        ins.setdefault((r["contract"], r["ancestor_of"]), []).append(r)
    seq: list = []
    for e in scored:
        if e[7] in res_keys:
            continue                                         # re-emitted beside its anchor below
        seq.append(e)
        grp = ins.pop((e[4], e[2]), None)
        if grp:
            seq.extend(r["_entry"] for r in                      # ONE ordering, shared with the cap order
                       sorted(grp, key=lambda r: _closure_group_key(r["chain_depth"], r["key"][2])))
    for grp in ins.values():                                 # defensive: anchor absent -> keep at the tail
        seq.extend(r["_entry"] for r in grp)
    final = (base_keys - disp_keys) | res_keys
    # The admission record: the shipped THREE fields always, plus the OPTIONAL convergence pair (D-MW-15 v)
    # ONLY on a candidate >= 2 admitted anchors reached. The shape is a required-SUPERSET now, not an exact
    # set — test_dgd_closure_reservation's exact-shape pin re-scoped in the same commit.
    _adm: dict = {}
    for r in reserved:
        rec = {"reason": r.get("reason", REASON_CLOSURE), "ancestor_of": r["ancestor_of"],
               "chain_depth": r["chain_depth"]}
        if r.get("convergence"):
            rec["convergence"], rec["anchors"] = True, list(r.get("anchors") or [])
        _adm[tuple(r["key"])] = rec
    return {"seq": seq, "final": final, "displaced": disp_keys, "headroom_used": headroom_used,
            "displaced_rec": [{"key": list(e[7]), "relevance": e[1], "depth": e[5]} for e in displaced],
            "reserved": reserved, "skipped": skipped, "tau_release": tau_release,
            "dedicated_used": len(reserved) if dedicated else 0, "slots_used": slots_used,
            "admissions": _adm}


def _closure_census(nodes: list, graph: gph.CausalGraph, backed: set, slice_of_driver,
                    displaced: list | tuple = ()) -> dict:
    """The embedding-free statement of the defect the reservation exists to fix, computed on EVERY walk so
    both arms of the A/B carry it: over a FIXED population of drivers, how many of their BACKED,
    SLICE-DISTINCT parent edges were CLOSED (both ends admitted) and how many were left OPEN.

    `open` is the deterministic counter the D-GD-3 read moves (ON arm < OFF arm) and it needs no judge, no
    retrieval and no model. Dark parents and same-slice parents are counted on NEITHER side: they are
    ineligible for the reservation, so charging the walk for them would be a metric the fix cannot move.

    THE POPULATION IS FIXED — R1 #3 (2026-08-08). v1 counted over `kept`, the very set the reservation
    changes, so DISPLACING a driver silently DELETED all of that driver's open parent edges from the count
    with nothing closed — and displacement systematically targets the LOWEST-ranked admitted drivers,
    precisely the ones whose parents were never admitted, i.e. the ones carrying the most open edges. The
    bias had a direction (measured on the real graph over the 57 firing single-contract rows: open fell 86
    while 36 of those edges vanished with a displaced node; the synthetic worst case was a 6x
    overstatement). The population is therefore the OFF ARM'S kept driver set, reconstructed on both arms
    as `cosine/focus-admitted kept drivers + the drivers this walk displaced`:
      - a DISPLACED driver stays in the census, so its open edges are still charged;
      - a CLOSURE-RESERVED driver is NOT a census child, so the treatment cannot add its own parent edges
        to either side of the ledger.
    Under it `open` can only fall because an ANCESTOR WAS ADMITTED — the mechanism — and
    `open_edges_lost_with_displaced` publishes the decomposition instead of leaving it to be re-derived."""
    admitted = {(n.contract, n.id) for n in nodes if n.kind == "driver"}
    disp = {(k[1], k[2]) for k in (tuple(d["key"]) for d in (displaced or [])) if k and k[0] == "driver"}
    # D-MW-15: the exclusion is a MEMBERSHIP TEST on `_STRUCTURAL_REASONS`, not a literal comparison —
    # `cascade_downstream` is excluded for the SAME reason `closure_reservation` is, and the decision is
    # RECORDED: downstream children are not ancestors, so counting them would redefine the open/closed
    # denominator mid-instrument (an A/B whose denominator moves with the treatment measures nothing).
    population = sorted({(n.contract, n.id) for n in nodes if n.kind == "driver"
                         and ((getattr(n, "admission", None) or {}).get("reason")
                              not in _STRUCTURAL_REASONS)} | disp)
    closed, open_edges, lost = 0, [], 0
    for cid, did in population:
        try:
            parents = list(graph.driver(cid, did).parents)
        except Exception:  # noqa: BLE001 — a synthetic/injected node need not be in the graph
            continue
        sp_child = slice_of_driver(did)
        for p in parents:
            if p not in backed:
                continue
            sp = slice_of_driver(p)
            if not sp or sp == sp_child:
                continue
            if (cid, did) in admitted and (cid, p) in admitted:
                closed += 1                                  # both ends retrievable in THIS walk
            else:
                open_edges.append([cid, did, p])
                if (cid, did) in disp:
                    lost += 1                                # what the v1 kept-set population deleted
    return {"closed": closed, "open": len(open_edges), "open_edges": sorted(open_edges),
            "census_population": len(population), "open_edges_lost_with_displaced": lost}


def grounded_subgraph(query: str, graph: gph.CausalGraph, *, depth: int = _DEPTH, node_budget: int = _NODE_BUDGET,
                      tau: float = _TAU, max_seeds: int = _MAX_SEEDS, embed=None, route_fn=None,
                      closure_reserve: int | None = None, driver_slices=None,
                      focus_driver: str | None = None,
                      per_seed_budget: int | None = None, per_seed_reserve: int | None = None) -> Subgraph:
    """Query-conditioned frontier walk. Returns the kept subgraph with the PRIOR leg + mermaid + trace filled;
    evidence/silver/convergence are added by ground(). Deterministic given `embed` (inject a fake in tests).

    ── D-MW-13/15 (2026-08-11) SEED-SCALED WIDTH. `max_seeds` is now the tier seed CEILING; the dispatch
    planner decides the REALIZED cardinality under it, and the two per-seed kwargs scale this walk from
    that realized count (`n = len(seeds)` AFTER seed selection, never the ceiling):
      * `per_seed_budget`  -> the effective COSINE node budget is `per_seed_budget * n`, and the
        `node_budget` kwarg/default is IGNORED for that walk (one producer of the number: this line).
      * `per_seed_reserve` -> `per_seed_reserve * n` DEDICATED, ADDITIVE graph-admission slots ON TOP of
        the cosine budget, OWNED PER SEED: seed s's slots fill only from s's own eligible candidates, and
        unfillable slots stay EMPTY (declared in `cascade_closure.reserve_slots`, never backfilled with
        cosine). `0` is a VALUE, not None: it forces the reservation OFF outright, beating
        GRAPHRAG_CLOSURE_RESERVE — the kwarg-wins precedence is a shipped pin, and it is what makes the
        P3-A arms (`max` vs `max_c0`) differ by exactly ONE variable at identical width.
    BOTH None => the shipped v1 walk byte for byte, env-driven closure_reserve path untouched.

    THE HOP FENCE (D-MW-13), SCOPED TO THE SEED-SCALED WALK: the cross_links enqueue is SKIPPED whenever
    the child contract would land at depth >= 2, and each skip increments
    `walk_shape.fenced_second_order_hops`. It is ACTIVE iff `per_seed_budget is not None` -- i.e. exactly on
    the walks this wave's presets drive, which is both P3-A arms (`max` and `max_c0` are the same preset
    base and both carry the per-seed budget), so the fence rides the A/B on both sides. It exists because
    depth=2 without it would ship P6's contract-admission path unbudgeted: a d==1 hop contract enqueues its
    OWN tracked cross_links, and second-order hop CONTRACTS sort ahead of every driver (is_hop precedence)
    at ~2.8k prompt tokens each (measured: 19/33 walks reach >= 1 second-order hop at d==2). Depth 2
    therefore buys hop DRIVERS only.

    WHY IT IS GATED AND NOT UNCONDITIONAL (P3 round-1 finding). The SHIPPED DEFAULT depth is 2, not 1
    (configs/graphrag/params.yaml `depth: 2`), and `standard`/unmoded turns carry all-None knobs -- so an
    unconditional fence changed the DEFAULT PRODUCT PATH: measured over the 33 curated DAGs at shipped
    defaults, 7/33 walks fired it and 2/33 moved `visited`/`pruned`, with the kept SET itself moving at
    wider budgets. A wave that declares "quick/standard/deep cannot move by a byte" may not quietly re-cut
    the default walk; `per_seed_budget is not None` is the same seam every other P3 width change rides.

    `focus_driver` (D-GD-1 R1 #5) is OBSERVATIONAL to the walk itself — it changes nothing about scoring,
    admission or budget. It only marks that driver DISPLACEMENT-PROTECTED, because answer._answer_l2
    re-injects it post-walk when it is absent, with no budget accounted for; a reservation that displaced
    it would therefore grow the turn's node count on the ON arm ONLY, past the `len(kept) <= node_budget`
    ceiling the budget invariant exists to hold. (That ceiling used to be argued as the 17-node
    `_COALESCE_MAX_DOCS` rerank cliff; the cliff is the BEDROCK lane's — on native cohere at 1,000 req/min
    chunk count is a request-shape detail, D-MW-11. The fence stands on the budget itself, which is a
    per-turn cost and prompt-window fact, not a vendor quota.) No-op when the reservation is off."""
    embed = embed or ev.embed
    if route_fn is None:
        from leviathan.graphrag import answer as _an  # lazy: answer imports planner for the l2 path
        route_fn = _an.route_smart
    qv = embed([query])[0]
    mech: dict = {}

    seeds = _seed_contracts(query, graph, route_fn, max_seeds)
    # D-MW-13: the REALIZED seed count is what every budget scales from — never `max_seeds`, which is only
    # the tier CEILING. `n_seeds or 1` so a routing miss (zero seeds) can never zero the budget.
    n_seeds = len(seeds)
    if per_seed_budget is not None:
        node_budget = max(1, int(per_seed_budget)) * max(1, n_seeds)
    # D-MW-13 THE HOP FENCE, scoped: active exactly on the seed-scaled walks this wave ships (both P3-A
    # arms), never on the legacy/default walk -- whose shipped depth is 2, so an unconditional fence would
    # have re-cut every standard/unmoded serving turn. See the docstring's fence paragraph.
    _fence_hops = per_seed_budget is not None
    visited: set = set()
    kept: dict[tuple, GroundedNode] = {}
    pruned: list[dict] = []
    # D-GD-1: reserve_left is a PER-WALK budget (not per-wave) — "reserve N of the walk's slots".
    # D-MW-15: `per_seed_reserve` SUPERSEDES it when declared (it is the dedicated-slot mechanism, and 0
    # means OFF outright). Only one of the two ever runs, so the v1 env path stays byte-identical.
    _dedicated = per_seed_reserve is not None and int(per_seed_reserve) > 0
    _slots_by_origin = {c: int(per_seed_reserve) for c in seeds} if _dedicated else None
    reserve_total = sum(_slots_by_origin.values()) if _dedicated else 0
    reserve_left = (reserve_total if _dedicated
                    else (0 if per_seed_reserve is not None else _closure_reserve_n(closure_reserve)))
    _origin_of_contract: dict = {c: c for c in seeds}       # contract -> the SEED whose lineage reached it
    _backed, _slice_of_driver = _driver_slice_resolvers(driver_slices)
    _cl_reserved: list[dict] = []
    _cl_displaced: list[dict] = []
    _cl_skipped: list[dict] = []
    _cl_admissions: dict = {}
    _cl_headroom = 0
    _cl_dedicated = 0
    _fenced_hops = 0                                        # D-MW-13: cross_links enqueues the fence dropped
    _protect_ids = frozenset({focus_driver}) if focus_driver else frozenset()
    # D-MW-15: nodes CHARGED to the cosine budget. Identical to len(kept) on every v1 walk; in the
    # dedicated-slot mode the reserve admissions are ADDITIVE and charged to nothing, which is the whole
    # of "cosine and graph admission can never displace each other".
    charged = 0

    def _score_of(cid: str, did: str) -> float:
        """cos(query, mechanism) for a CANDIDATE, off the walk's own `_relevance` cache — the v2
        query-scored selection (D-MW-15 ii). Same embedder, same cache, no second scale."""
        try:
            return _relevance(qv, graph.driver(cid, did).mechanism, embed, mech)
        except Exception:  # noqa: BLE001 — an unindexed candidate orders last, it never fails the walk
            return 0.0

    # Wave-by-wave BFS: at each depth, SCORE every candidate and admit the most relevant under the budget,
    # instead of FIFO in YAML-curation order (v1.1's walk kept whichever drivers came first, so 70% of
    # regime-required drivers were never visited and the reasoner saw an arbitrary slice). tau stays a floor;
    # tracked cross-commodity hops rank ahead of drivers at the same depth so the cascade can't be starved.
    wave = [(c, 0, None, "contract", c) for c in seeds]     # (id, depth, via_edge, kind, contract)
    while wave and charged < node_budget:
        scored = []
        wave_pruned: dict = {}                              # D-GD-1: this wave's tau tombstones, by key
        for id_, d, via, kind, cid in wave:
            key = (kind, cid, id_)
            if key in visited:
                continue
            visited.add(key)
            if d == 0:                                      # seeds always kept
                rel = 1.0
            elif kind == "contract":                        # a cross-commodity hop: score its edge mechanism
                rel = _relevance(qv, (via or {}).get("mechanism", ""), embed, mech)
            else:                                           # a driver: score its mechanism
                rel = _relevance(qv, graph.driver(cid, id_).mechanism, embed, mech)
            if d > 0 and rel < tau:
                _p = {"key": list(key), "relevance": round(rel, 3), "depth": d, "reason": "tau"}
                pruned.append(_p)
                if reserve_left > 0:                        # only the reservation ever reads this index
                    wave_pruned[key] = (round(rel, 3), _p)
                continue
            is_hop = 1 if (kind == "contract" and d > 0) else 0    # tracked hop priority (L2's headline)
            scored.append((is_hop, round(rel, 3), id_, kind, cid, d, via, key))

        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))     # hop-first, then relevance desc, id asc (deterministic)
        # D-GD-1: the reservation is decided HERE — AFTER the hop-first comparator has run and OUTSIDE it,
        # so a tracked hop can never consume a reserved slot (dgd-graph-depth-structure.md S3/S4.6). `plan`
        # is None whenever nothing was reserved, and the loop below is then the shipped one byte for byte.
        plan = None
        if reserve_left > 0 and any(e[3] == "driver" and e[5] > 0 for e in scored):
            plan = _closure_plan(scored, kept, graph, node_budget=node_budget, reserve_n=reserve_left,
                                 backed=_backed, slice_of_driver=_slice_of_driver, wave_pruned=wave_pruned,
                                 protect_ids=_protect_ids,
                                 # D-MW-15: the four v2 arguments. ALL None/absent on a v1 walk, and
                                 # `_closure_plan` then runs its shipped path byte for byte.
                                 slots_by_origin=_slots_by_origin,
                                 origin_of_contract=(_origin_of_contract if _dedicated else None),
                                 score_of=(_score_of if _dedicated else None),
                                 n_charged=(charged if _dedicated else None))
        if plan is not None:
            _rel = {id(p) for p in plan["tau_release"]}      # a tau-exempt admission RELEASES its tombstone
            if _rel:                                         # so the pruned/kept ledger stays a partition
                pruned[:] = [p for p in pruned if id(p) not in _rel]
            reserve_left -= len(plan["reserved"])
            if _slots_by_origin is not None:                 # per-seed ownership is a PER-WALK ledger
                for _o, _u in (plan["slots_used"] or {}).items():
                    _slots_by_origin[_o] = max(0, _slots_by_origin.get(_o, 0) - _u)
            _cl_reserved.extend(plan["reserved"])
            _cl_displaced.extend(plan["displaced_rec"])
            _cl_skipped.extend(plan["skipped"])
            _cl_admissions.update(plan["admissions"])
            _cl_headroom += plan["headroom_used"]
            _cl_dedicated += plan["dedicated_used"]
        _seq = plan["seq"] if plan is not None else scored
        _final = plan["final"] if plan is not None else None
        nxt = []
        for is_hop, rel, id_, kind, cid, d, via, key in _seq:
            if _final is None:
                _blocked, _reason = (d > 0 and charged >= node_budget), "budget"
            else:                                           # the plan already spent the SAME budget: it
                _blocked = key not in _final                # displaced exactly as many as it reserved
                _reason = "closure_displaced" if key in plan["displaced"] else "budget"
            if _blocked:                                    # budget spent on higher-ranked candidates
                pruned.append({"key": list(key), "relevance": rel, "depth": d, "reason": _reason})
                continue
            node = GroundedNode(kind=kind, id=id_, contract=cid, depth=d, relevance=rel, via_edge=via)
            node.prior = _prior(graph, node)
            node.admission = dict(_cl_admissions.get(key) or _ADMIT_COSINE)
            kept[key] = node
            # A DEDICATED-slot admission is charged to nothing (D-MW-15 i). Every other admission — cosine,
            # and every v1 closure admission, which pays by headroom or displacement — is charged, so
            # `charged == len(kept)` on every v1 walk and the budget check below is byte-identical.
            if not (_dedicated and node.admission.get("reason") in _STRUCTURAL_REASONS):
                charged += 1
            if d >= depth:
                continue
            if kind == "contract":
                for e in graph.cross_links(cid):            # tracked inter-commodity hops -> next wave
                    if e["tracked"]:
                        if _fence_hops and d + 1 >= 2:      # D-MW-13 THE HOP FENCE: a second-order hop
                            _fenced_hops += 1               # CONTRACT is ~2.8k tokens and sorts ahead of
                            continue                        # every driver -- P6's mechanism, not P3's
                        _origin_of_contract.setdefault(e["driver_commodity"],
                                                       _origin_of_contract.get(cid, cid))
                        nxt.append((e["driver_commodity"], d + 1,
                                    {**e, "_from": cid, "category": edge_category(e["relation"])},
                                    "contract", e["driver_commodity"]))
                for drv in graph.contracts[cid].drivers:    # driver fan-in of this contract -> next wave
                    nxt.append((drv.id, d + 1, None, "driver", cid))
            else:
                for p in graph.driver(cid, id_).parents:    # upstream cascade (parents cause this driver)
                    nxt.append((p, d + 1, None, "driver", cid))
        wave = nxt

    nodes = list(kept.values())
    sg = Subgraph(seeds=seeds, nodes=nodes,
                  trace={"seeds": seeds, "kept": [list(n.key) for n in nodes], "pruned": pruned,
                         "visited": len(visited), "budget": node_budget,
                         "params": {"depth": depth, "tau": tau, "node_budget": node_budget, "max_seeds": max_seeds}})
    # D-GD-1 AUDITABILITY. ONE new, purely ADDITIVE trace key; every pre-existing key above is byte-identical
    # on both arms. Stamped on EVERY walk, both polarities, deliberately: `open` is the arms' shared
    # deterministic baseline, and an OFF arm that stamped nothing would leave the ON arm's number
    # uncomparable (the served_rows lesson — an adjudication that needs a re-run is not an adjudication).
    # `_count_delta` is the node-count invariant, carried as evidence rather than as a promise.
    for r in _cl_reserved:
        r.pop("_entry", None)                                # the scored tuple is machinery, not a record
    _n_res = _closure_reserve_n(closure_reserve) if per_seed_reserve is None else reserve_total
    # D-MW-15 (P3 round-1): the skipped column is a SUPPLY-vs-SLOT census read, and a first-32-overall
    # sample destroyed it. At max width `already_admitted` dominates the ordered candidate pool by
    # construction (63 slots/seed against ~48-driver DAGs), so on a real 4-seed walk all 32 sampled entries
    # were that one reason and `no_slot` -- the reason the code records specifically to separate "no supply"
    # from "no slot" -- was never visible in the artifact. Two columns now: FULL per-reason counts (never
    # truncated, the number the census actually reads) beside a sample capped PER REASON, so every reason
    # that fired is present and the sample stays bounded (5 reasons x 8).
    _skipped_counts: dict = {}
    _skipped_sample: list = []
    for _s in _cl_skipped:
        _rsn = str(_s.get("reason") or "")
        _skipped_counts[_rsn] = _skipped_counts.get(_rsn, 0) + 1
        if _skipped_counts[_rsn] <= 8:
            _skipped_sample.append(_s)
    sg.trace["cascade_closure"] = {
        "enabled": bool(_n_res), "reserve_n": _n_res,
        "kept": len(nodes), "budget": node_budget,
        "reserved": _cl_reserved, "displaced": _cl_displaced,
        # R1 #1: the accounting identity, restated for headroom-first. Every reserved slot is paid for by
        # EITHER an unspent budget slot OR a displaced driver OR a DEDICATED per-seed slot (D-MW-15),
        # never by nothing — so this stays 0 in both mechanisms, while the invariant that actually binds
        # (`charged <= budget`; v1: `kept <= budget`) is satisfied by construction.
        "headroom_used": _cl_headroom, "dedicated_used": _cl_dedicated,
        "count_delta": len(_cl_reserved) - len(_cl_displaced) - _cl_headroom - _cl_dedicated,
        # bounded: an audit column may not become a dump -- but the BOUND is per reason, and the counts
        # beside it are over the FULL list (see the derivation above).
        "skipped": _skipped_sample, "skipped_counts": _skipped_counts,
        "admissions": {":".join(str(p) for p in n.key): n.admission for n in nodes},
        # D-MW-15 (i)/(ii): the DEDICATED-SLOT ledger. `empty` is the instrument-dead row made READABLE —
        # a seed with no eligible candidates leaves its slots unfilled, declared here, and they are NEVER
        # backfilled with cosine (backfilling would re-create the substitution the mechanism removed).
        "dedicated": bool(_dedicated), "per_seed_reserve": per_seed_reserve,
        "per_seed_budget": per_seed_budget, "n_seeds": n_seeds,
        "reserve_slots": {"total": reserve_total, "filled": _cl_dedicated,
                          "empty": max(0, reserve_total - _cl_dedicated),
                          "by_seed": {c: {"total": int(per_seed_reserve or 0),
                                          "filled": int(per_seed_reserve or 0) - _slots_by_origin.get(c, 0)}
                                      for c in seeds} if _dedicated else {}},
        # (iv)/(v): the two direction-and-convergence counters the P3-A record reads. Both stamped on
        # BOTH arms (0 on the OFF arm), same reason `open` is: an unstamped arm is an uncomparable arm.
        "n_downstream": sum(1 for r in _cl_reserved if r.get("reason") == REASON_DOWNSTREAM),
        "n_convergence": sum(1 for r in _cl_reserved if r.get("convergence")),
        **_closure_census(nodes, graph, _backed, _slice_of_driver, _cl_displaced)}
    # D-MW-13 THE walk_shape ARTIFACT. Four RECORDED quantities of the P3 gates had no artifact source —
    # seeds and per-node depth never reached the per-answer record, so every "len(seeds) distribution" and
    # "wave-2 hop-driver count" clause was unreadable. Stamped BESIDE cascade_closure, registered in
    # tracekeys, whitelisted into eval._per_answer_record. Depth keys are STRINGS: this column round-trips
    # through JSON into the artifact, and int keys would silently become strings there anyway.
    _kbd: dict = {}
    for _n in nodes:
        _kbd[str(_n.depth)] = _kbd.get(str(_n.depth), 0) + 1
    sg.trace["walk_shape"] = {"n_seeds": n_seeds, "kept_by_depth": _kbd,
                              "hop_contracts": sum(1 for n in nodes if n.kind == "contract" and n.depth > 0),
                              "fenced_second_order_hops": _fenced_hops}
    sg.mermaid = graph_to_mermaid(sg, graph)
    return sg


def _prior(graph: gph.CausalGraph, n: GroundedNode) -> dict:
    if n.kind == "driver":
        d = graph.driver(n.contract, n.id)
        # region rides along (RF-2): cascade._scope resolves country_rule=region legs from it; dropping it
        # here silently resolved every foreign-region driver to the contract's primary country (F1).
        return {"sign": d.sign, "lag": d.lag, "mechanism": d.mechanism, "confidence": d.confidence,
                "target_metric": d.target_metric, "silver_ref": d.silver_ref, "silver_status": d.silver_status,
                "region": d.region}
    c = graph.contracts[n.contract]
    return {"target_metrics": list(c.target_metrics), "via_edge": n.via_edge}


# ── ground(): the I/O legs — evidence (WS-2), silver (WS-5), convergence firing (WS-4) ───────────────────────
def _slice_of(n: GroundedNode, slice_path) -> Optional[str]:
    """Evidence-slice path for a node. Contract -> its commodity slice; driver -> drivers/<slice> resolved
    through the alias map (None when the driver has no text slice)."""
    return ev.node_for(n.contract) if n.kind == "contract" else slice_path(n.id)


def _closure_cap_order(order: list) -> list:
    """D-GD-1 PIN 1 — THE SELF-CANCEL TRAP, CLOSED. `_dedup_and_cap` spends one global budget walking the
    nodes `(depth, -relevance)`-first, so a CLOSURE-RESERVED ancestor — admitted for STRUCTURE, often below
    the relevance floor its siblings cleared — sorts to the tail and is retrieved-and-then-zeroed. That is
    the exact D-DV-1b uncitable-prompt-window defect the plan names as option (b)'s self-cancel, and it
    would have made the reservation buy a node the reader can never cite.

    THE FIX IS AN ORDER CHANGE, NOT A SCORE CHANGE. A reserved node is moved to sit immediately after the
    ANCHOR DRIVER whose chain earned it (its whole chain in nearest-parent-first order), so it draws cap
    budget as that driver's peer instead of as the walk's tail. Relevance is NOT rewritten: the field feeds
    `cap_policy="score"` quotas, `_render_order` and the trace, and a synthetic 1.0 there would be a lie
    that three other readers would repeat. Under the score policy the same move also protects the reserved
    node from the ceil()-overshoot trim, which is likewise paid from the tail.

    NO-OP BY CONSTRUCTION when no node carries a closure admission — it returns the very list it was given,
    so the OFF arm's cap is the shipped FIFO byte for byte.

    D-MW-15: the test is MEMBERSHIP in `_STRUCTURAL_REASONS`, not a literal. A `cascade_downstream` node is
    admitted for structure exactly as an ancestor is, so it needs the same anchor-adjacency move — the
    literal comparison would have sent it to the tail and zeroed it (the admitted-but-not-cited class)."""
    res = [n for n in order
           if ((getattr(n, "admission", None) or {}).get("reason") in _STRUCTURAL_REASONS)]
    if not res:
        return order
    res_ids = {id(n) for n in res}
    by_anchor: dict = {}
    for n in res:
        by_anchor.setdefault((n.contract, (n.admission or {}).get("ancestor_of")), []).append(n)
    out: list = []
    for n in order:
        if id(n) in res_ids:
            continue
        out.append(n)
        grp = by_anchor.pop((n.contract, n.id), None)
        if grp:
            out.extend(sorted(grp, key=lambda x: _closure_group_key(     # ONE ordering, shared with the
                (x.admission or {}).get("chain_depth"), x.id)))          # walk's own seq emission
    for grp in by_anchor.values():                             # anchor absent (defensive): keep, at the tail
        out.extend(grp)
    return out


def _dedup_and_cap(sg: Subgraph, cap: int, *, cap_policy: str | None = None, k_by_depth=None) -> None:
    """A prop retrieved under several nodes is attributed to the SHALLOWEST (most-relevant) node only, and the
    subgraph's total evidence is capped (depth-2 unions explode) — shallow nodes first.

    `cap_policy=None` is the FIFO original, byte for byte: walk the nodes shallowest-first and spend one
    global budget until it runs out, so a wide walk's last nodes get nothing whatever their relevance.
    `cap_policy="score"` (D-DV-2 explore-wide-cite-narrow) keeps the same dedup and the same total but
    SELECTS instead of truncating: every node holding unique rows gets a share of the cap proportional to
    its own walk relevance (ceil(cap * rel_n / sum_rel)), depth-0 seeds are floored at their own k so a
    routed contract can never be starved by its fan-in, and the overshoot ceil() creates is trimmed from
    the tail of the LOWEST-relevance node first. It never rewrites or re-ranks a row (D-DT item-2 law).

    WHY THE QUOTA IS NODE-RELEVANCE-PROPORTIONAL AND NOT ROW-SCORE-THRESHOLDED: verified against
    rankers._fire (grouped PER DISTINCT QUERY, and the walk sends the same query string for every node,
    then packed at caller boundaries into <= _COALESCE_MAX_DOCS requests -- D-MW-9) -- so on the happy
    path all nodes' docs are scored in ONE request and their scores share a normalization. But that is
    NOT guaranteed: past the doc cap the packing splits nodes ACROSS requests (whole nodes, never a node
    in half), _parallel_fill's pool can be narrower than the hinted batch (measured floor
    ceil(n_arrivals/workers) requests per turn), the quiescence closer can split a batch, and the
    per-caller bge fallback scores each node on its own scale. Cross-node raw
    scores are therefore comparable only sometimes, and a policy may not depend on "sometimes". Rows
    keep their retriever order WITHIN a node, where comparability always holds."""
    seen: set = set()
    order = _closure_cap_order(sorted(sg.nodes, key=lambda x: (x.depth, -x.relevance)))
    if cap_policy != "score":
        budget = cap
        for n in order:
            keep = []
            for h in n.evidence:
                sig = (h.get("source_key"), h.get("date"), (h.get("text") or "")[:80])
                if sig in seen or budget <= 0:
                    continue
                seen.add(sig)
                keep.append(h)
                budget -= 1
            n.evidence = keep
        return

    uniq: list[list] = []                                     # dedup FIRST, uncapped: same attribution rule
    for n in order:
        keep = []
        for h in n.evidence:
            sig = (h.get("source_key"), h.get("date"), (h.get("text") or "")[:80])
            if sig in seen:
                continue
            seen.add(sig)
            keep.append(h)
        uniq.append(keep)
    live = [i for i, k in enumerate(uniq) if k]
    tot_rel = sum(max(float(order[i].relevance or 0.0), 0.0) for i in live)
    k0 = int((tuple(k_by_depth or ()) or (0,))[0] or 0)
    for i, keep in enumerate(uniq):
        if not keep:
            continue
        share = ((max(float(order[i].relevance or 0.0), 0.0) / tot_rel) if tot_rel > 0
                 else 1.0 / len(live))                        # all-zero relevance -> equal split, never /0
        q = math.ceil(round(cap * share, 9))
        if order[i].depth == 0:
            q = max(q, k0)                                    # the routed contract's own k is a floor
        if ((getattr(order[i], "admission", None) or {}).get("reason") in _STRUCTURAL_REASONS):
            # D-GD-1 R1 #6 (D-MW-15: now a MEMBERSHIP test, so `cascade_downstream` gets the same floor —
            # a structurally admitted node that ends the turn with ZERO evidence rows is the exact
            # admitted-but-not-cited defect P3-A exists to prove fixed).
            # A STRUCTURALLY admitted node is admitted for structure and is tau-EXEMPT, so its
            # relevance can be exactly 0.0 (no wave tombstone to inherit) -> share 0 -> ceil(0) = 0 rows,
            # which is pin 1's self-cancel reopened through the quota instead of through the order. One
            # row is the floor: the slot was spent, the node must be citable. (Reachable only under
            # cap_policy="score", i.e. deep_v2, which is dark -- fixed anyway, cheaply.)
            q = max(q, 1)
        uniq[i] = keep[:max(q, 0)]
    over = sum(len(k) for k in uniq) - cap                    # ceil() overshoots; pay it lowest-relevance first
    for i in range(len(uniq) - 1, -1, -1):
        if over <= 0:
            break
        cut = min(over, len(uniq[i]))
        if cut:
            uniq[i] = uniq[i][:len(uniq[i]) - cut]
            over -= cut
    for n, keep in zip(order, uniq):
        n.evidence = keep


def _parallel_fill(nodes, fn, query, retrieve, expected: int | None = None) -> None:
    """Run the per-node evidence fetch concurrently (overlaps the slow managed-rerank round-trips). Falls back
    to sequential when workers<=1 or a single node. On the REAL serving retriever we pre-warm the shared query
    embedding once — else N parallel workers each recompute the same embedding (the old 26%-of-wall waste);
    injected test fakes are not ev.retrieve, so the pre-warm (and any bge load) is skipped, keeping tests
    hermetic + deterministic. `expected` = the EXACT count of nodes that will retrieve (skip-predicate applied
    by the caller) — the rerank coalescer fires the single Bedrock request the moment they've all arrived."""
    nodes = list(nodes)
    if _WALK_WORKERS <= 1 or len(nodes) <= 1:
        for n in nodes:
            fn(n)
        return
    hinted = 0
    if getattr(retrieve, "func", retrieve) is ev.retrieve:
        try:
            ev.embed([query])
        except Exception:  # noqa: BLE001 — a warmup miss must never break the walk
            pass
        try:                                       # managed-rerank quota is ~3 req/MIN: hint the coalescer so
            from leviathan.graphrag import (
                rankers as rk,  # the walk's per-node reranks merge into ONE request
            )
            if rk._rerank_backend() in ("bedrock", "cohere"):   # D-MW-5: the native lane still coalesces
                hinted = int(expected if expected is not None else len(nodes))
                rk.rerank_expect(hinted)
        except Exception:  # noqa: BLE001 — a hint miss only costs latency, never correctness
            hinted = 0
    import concurrent.futures as cf
    workers = min(_WALK_WORKERS, len(nodes))
    if hinted > workers:
        # THE HINT MUST BE PHYSICALLY SATISFIABLE. A worker frees only when its _fill returns, and _fill
        # returns only after its rerank resolves — so with a pool NARROWER than the promised batch the last
        # arrivals are blocked behind the very request they were supposed to join. Measured in-VPC (job
        # 44e96fc1): at 8 workers / 10 eligible nodes the floor is ceil(n_arrivals / workers) = 2 requests
        # per turn at EVERY timer setting, and widening the quiescence only makes the leader manufacture its
        # own straggler (final inter-arrival gap grew from 0.09-0.75 s at q=0.3 to 5.7-7.1 s at q=5.0). The
        # one turn that reached 1 request at 8 workers was the one with 7 arrivals. Widening here does NOT
        # widen DB concurrency: pgstore._acquire caps concurrent SQL at EVIDENCE_PG_POOL and releases the
        # connection BEFORE the rerank, so the extra threads queue on that pool exactly as they do today and
        # only the (network-bound, coalesced) rerank leg gains parallelism.
        #
        # ...AND IT IS BOUNDED (D-MW-14, P3 round-1). The measurement above was taken when the widest
        # preset walked 16 nodes; the seed-scaled budget makes `hinted` the eligible-node count of a
        # 63-per-seed walk (measured: 239 kept / 252 derived budget at 4 realized seeds, 378 + 24 at the
        # 6-seed ceiling). MAX_FILL_POOL caps the WIDENED pool only -- `max(workers, ...)` so this can
        # never NARROW the shipped `min(_WALK_WORKERS, len(nodes))`, and every width <= 64 keeps the exact
        # arithmetic it has today.
        workers = max(workers, min(hinted, len(nodes), MAX_FILL_POOL))
    # D-MW-6: THE LANE PROPAGATION. Every rerank in this walk happens inside one of these workers, and the
    # lane collector is a THREAD-LOCAL, so the parent turn's collector object is captured HERE (on the
    # caller's thread) and installed into each worker for the duration of its node. Two round-3 corrections
    # are baked in: (a) contextvars does NOT work for this — a Context copied inside a worker is empty, and
    # one shared Context entered by 4 workers raises; (b) the wrapper is now UNCONDITIONAL. It used to exist
    # only when `hinted` was truthy, i.e. never on the bge lane — which would have left an A/B's bge CONTROL
    # arm with no lane stamp at all and no way to pre-flight itself. The unexpect-on-raise leg stays
    # hint-gated (retracting a promise nobody made is a quota lie), so the hinted path is byte-identical.
    _lane_rk, _parent_lane = None, None
    try:
        from leviathan.graphrag import rankers as _lane_rk
        _parent_lane = _lane_rk.lane_collector()
    except Exception:  # noqa: BLE001 — telemetry must never break a walk
        _lane_rk, _parent_lane = None, None

    def fn_(n):  # noqa: E306
        try:
            if _parent_lane is None:
                fn(n)
            else:
                with _lane_rk.adopt_lane(_parent_lane):     # nested-safe; clears in its own finally
                    fn(n)
        except BaseException:                  # a promised arrival that died must RETRACT its promise,
            if hinted:                         # else the leader waits out the whole window for a caller
                try:                           # that can never arrive
                    from leviathan.graphrag import rankers as rk
                    rk.rerank_unexpect()
                except Exception:  # noqa: BLE001
                    pass
            raise
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fn_, nodes))


def _emit_stage(on_stage, stage: str, **info) -> None:
    """Local copy of answer._emit's contract (avoids an answer<->planner import knot): best-effort progress
    callback; None -> strict no-op; any callback error is swallowed."""
    if on_stage is None:
        return
    try:
        on_stage(stage, info)
    except Exception:  # noqa: BLE001 — progress reporting is cosmetic; it can never fail a walk
        pass


def ground(sg: Subgraph, query: str, graph: gph.CausalGraph, *, retrieve=None, silver_lookup=None,
           asof=None, near=None, k_by_depth=_K_BY_DEPTH, evidence_cap: int = _EVIDENCE_CAP, driver_slices=None,
           probe_cap: int = _PROBE_CAP, recency_days: int = _RECENCY_DAYS, probe_retrieve=None,
           on_stage=None, cap_policy: str | None = None) -> Subgraph:
    """Fill the evidence + silver legs and fire convergence deterministically. `retrieve`/`silver_lookup` are
    injectable (tests pass fakes; serving passes the real hybrid+rerank+mmr retriever + numbers lookup).

    Two things resolve the v1.1 A/B blockers (regimes fired 0.0, leg-grounding 0.2):
      * driver evidence now reads drivers/<SLICE> via the alias map (ev.slice_for_driver) — slice NAMES were
        curated apart from DAG driver ids, so the old drivers/<id> path resolved only the 13 exact-name
        matches; the alias unlocks ~40+ ids (incl. the top regime drivers heat_stress / *_su_ratio / crude /
        USD_index / cot positioning). Tests still inject `driver_slices` (a set) to stay hermetic: then the
        driver id IS treated as its own slice path, as before.
      * regime firing is DECOUPLED from the walk: a regime is evaluated over its FULL required-driver list,
        not just the drivers the budget-limited walk happened to keep (70% of required drivers were never
        even visited). A required driver missing from the walk gets a cheap activity PROBE (k=2, asof-guarded,
        cached per (contract, driver), capped) — active if its slice has dated evidence at the asof, or it is
        named in the contract's own evidence."""
    retrieve = retrieve or ev.retrieve
    if driver_slices is not None:                                  # hermetic tests: the id IS the slice path
        backed = set(driver_slices)
        def slice_path(did):  # noqa: E306
            return f"drivers/{did}"
    else:                                                          # serving: resolve dag id -> curated slice
        backed = ev.backed_dag_ids()
        def slice_path(did):  # noqa: E306
            s = ev.slice_for_driver(did)
            return f"drivers/{s}" if s else None

    from leviathan.graphrag import timeline as tl

    def _fill(n):                                                  # per-node evidence, k decays with depth
        sp = _slice_of(n, slice_path)
        if n.kind == "driver" and (n.id not in backed or sp is None):
            return                                                 # no slice -> prior-only node (no empty fetch)
        k = k_by_depth[min(n.depth, len(k_by_depth) - 1)]
        n.evidence = list(retrieve(query, sp, k=k, asof=asof, near=near))
        # NOTE: episodes are NOT stamped here -- see the episodes_for loop AFTER _dedup_and_cap below.

    # The per-node retrieves are INDEPENDENT — each closure mutates only its own node. On pg the fetch is a fast
    # pooled SQL round-trip, but the rerank is a slow MANAGED call: 10 sequential ~4s Cohere calls were ~40s of
    # the walk. Run them concurrently so the rerank round-trips overlap (coalesced into one request).
    import time as _time
    _t0 = _time.perf_counter()
    eligible = sum(1 for n in sg.nodes
                   if not (n.kind == "driver" and (n.id not in backed or _slice_of(n, slice_path) is None)))
    fill_fn = _fill
    if on_stage is not None:                                       # progress ticks (5.6 W5); the None path runs the
        import threading as _th  # exact same closure as before — byte-identical
        _plock, _pdone = _th.Lock(), [0]

        def fill_fn(n):  # noqa: E306
            _fill(n)
            if n.kind == "driver" and (n.id not in backed or _slice_of(n, slice_path) is None):
                return                                             # ineligible node — no evidence work happened
            with _plock:
                _pdone[0] += 1
                d = _pdone[0]
            _emit_stage(on_stage, "retrieving", done=d, total=eligible)
            # F7 `evidence`: this node's leg is GROUNDED — slug + kept count as it lands, one per node, from
            # inside the fill pool (the `retrieving` tick above already proves concurrent emission is safe
            # here). SLUG ONLY: never the prop text, never a source_key (invariant 4 — walk evidence is
            # document prose). A dark leg returns above, so a 0 here means "asked, kept nothing".
            _emit_stage(on_stage, "evidence", node=":".join(str(p) for p in n.key), kept=len(n.evidence or []))
    _parallel_fill(sg.nodes, fill_fn, query, retrieve, expected=eligible)
    _t_fill = _time.perf_counter()
    # P7-P0.2: per-driver-leg evidence report — the E0/E3 sparsity-attribution instrumentation. Purely
    # additive to the trace (the trace is never persisted to durable turns — PIT firewall intact). A leg is
    # `dark` when it was dropped as prior-only; dark_reason separates the two OR'd sub-conditions at the
    # _fill guard above (unbacked id = alias-map gap vs no slice file) — they have different E1 fixes.
    # n_evidence is captured PRE-dedup deliberately: it answers "did dated props EXIST for this leg"
    # (the attribution question), not "how many survived the cross-node dedup" (a serving artifact).
    sg.trace["driver_legs"] = [
        {"key": list(n.key), "backed": n.id in backed, "slice": _slice_of(n, slice_path),
         "n_evidence": len(n.evidence or []),
         "dark": n.id not in backed or _slice_of(n, slice_path) is None,
         "dark_reason": ("unbacked_id" if n.id not in backed
                         else ("no_slice" if _slice_of(n, slice_path) is None else None))}
        for n in sg.nodes if n.kind == "driver"]
    # P7-P3 W1.4: count-only retrieval telemetry. A cheap in-memory per-slice increment feeding the
    # {unreachable | reachable-never-asked | used} triage — reads ONLY {slice, dark, n_evidence} counts,
    # NEVER evidence text (the PIT firewall) and never mutates the trace. Guarded so a telemetry bug can
    # never break a walk; the durable flush() to S3 is a separate/periodic step (no I/O in this hot path).
    # ground() runs on reasoning/hybrid turns only (numbers-only turns build no legs), so no intent gate.
    try:
        from leviathan.graphrag import retrieval_telemetry as _rt
        _rt.record(sg.trace["driver_legs"])
    except Exception:  # noqa: BLE001 — telemetry is never allowed to perturb the answer
        pass
    _dedup_and_cap(sg, evidence_cap, cap_policy=cap_policy,       # dedup cross-node restatement + cap total
                   k_by_depth=k_by_depth)
    # EPISODES ARE COMPUTED AGAINST POST-CAP EVIDENCE (D-DV-1b). They used to be stamped inside _fill, on
    # the PRE-cap list, and _dedup_and_cap then zeroed the very rows the episode line's receipts quote --
    # so a node whose evidence was capped away still rendered "the record holds N episodes" with receipts
    # absent from the verifier's evidence list (measured under deep: ~38 discarded props/turn of uncitable
    # prompt window, episode_enumeration 2/5 on 11/12 rows). A node with no evidence LEFT now gets no
    # episode line at all: the receipt and the row it quotes ride or fall together, by construction.
    # Same episodes_for signature, same `tl` source, same "only nodes that HAVE dated props" rule -- an
    # episode the reasoner has no text for is what invited confabulation (measured 2026-07-04).
    for n in sg.nodes:
        if not n.evidence:
            continue
        sp = _slice_of(n, slice_path)
        if n.kind == "driver" and (n.id not in backed or sp is None):
            continue
        n.episodes = tl.episodes_for(sp, asof, evidence=n.evidence)

    # ── D-GD-1 AUDIT JOIN: what a closure-admitted node actually contributed ──────────────────────────────
    # Computed AFTER _dedup_and_cap, on the rows that SURVIVED it — a pre-cap count would say the slot paid
    # off when the cap had already zeroed it (pin 1's failure mode, measured as a number rather than
    # asserted). `cited_join` is the ROW identity of those rows; verify's report already projects exactly
    # these three fields per resolved [E] handle, so eval can COUNT the citations that landed on
    # closure-admitted evidence with ZERO change to verify.py (whose rules are settled and stay frozen).
    #
    # THE KEY IS (source_key, date, snippet) AND NOT (source_key, date) — R1 #2 (2026-08-08). `source_key`
    # is a DOCUMENT key, not a row key (evidence.py:314/377 — one document is chunked into MANY
    # propositions), and `_dedup_and_cap`'s dedup signature is (source_key, date, text[:80]), so two
    # DIFFERENT propositions of the SAME document survive on two DIFFERENT nodes. Under the 2-field key any
    # [E] handle resolving to a COSINE node's row from a document a reserved node also holds was counted as
    # a closure citation — and because the OFF arm has no reserved nodes, `cited_join` is empty there and
    # `n_cited` is structurally 0, so the miscount could only ever INFLATE THE TREATMENT. Shared documents
    # across slices are the normal case here (evidence.py:1208). The third field is verify.py's OWN
    # `snippet` projection, byte for byte (verify.py:906: text[:140] + "..." when longer), so the join stays
    # a pure read of what the verifier already publishes.
    _cc = sg.trace.get("cascade_closure")
    if isinstance(_cc, dict):
        _idx = {tuple(r["key"]): r for r in (_cc.get("reserved") or [])}
        _join = []
        for n in sg.nodes:
            r = _idx.get(tuple(n.key))
            if r is None:
                continue
            r["n_evidence"] = len(n.evidence or [])
            r["n_episodes"] = len(n.episodes or [])
            # D-MW-15 THE INSTRUMENT SPLIT: a FOURTH field, the admission REASON. `n_cited` counts handles
            # hitting ANY structurally admitted node, so downstream citations could mask upstream silence —
            # and the split was UNCOMPUTABLE from the artifact as stamped (three fields, no reason, and the
            # reader hard-drops short rows). eval._closure_cited partitions on this field into
            # n_cited_upstream / n_cited_downstream and reads legacy 3-field rows as UPSTREAM, so every
            # pre-P3 artifact stays parseable and `n_cited` stays emitted as the sum.
            _reason = (n.admission or {}).get("reason") or REASON_COSINE
            for h in (n.evidence or []):
                _t = h.get("text") or ""
                _join.append([h.get("source_key"), str(h.get("date") or "")[:10],
                              _t[:140] + ("..." if len(_t) > 140 else ""), _reason])
        _cc["cited_join"] = _join
        _cc["reserved_with_evidence"] = sum(1 for r in _idx.values() if r.get("n_evidence"))

    # ── parallel silver PREFETCH (serving only) ──────────────────────────────────────────────────────────
    # The silver leg + firing both call silver_lookup sequentially; each servable ref is an Athena read
    # (~3.5s) — measured as ~14s of the walk. The lookups are independent and make_silver_lookup is now
    # single-flight thread-safe, so warm the memo in parallel here; the sequential loops below then hit it.
    # Only ~<=5 unique keys exist per turn (su_ratio/fx per contract + oni global), so the cap never binds
    # and parallel order cannot change semantics. Gated to the REAL retriever: hermetic tests keep exact
    # sequential call patterns on their injected fakes.
    if silver_lookup is not None and asof and getattr(retrieve, "func", None) is ev.retrieve:
        pairs = {(n.contract, n.id) for n in sg.nodes if n.kind == "driver" and n.prior.get("silver_ref")}
        for cid in sorted({n.contract for n in sg.nodes}):
            if cid in graph.contracts:
                pairs |= {(cid, d) for s in graph.contracts[cid].convergence for d in s.drivers}
        if len(pairs) > 1:
            import concurrent.futures as cf

            def _pf(p):
                try:
                    silver_lookup(p[0], p[1], asof)
                except Exception:  # noqa: BLE001 — prefetch must never break the answer
                    pass
            with cf.ThreadPoolExecutor(max_workers=min(8, len(pairs))) as _pool:
                list(_pool.map(_pf, sorted(pairs)))

    ctx_text: dict[str, str] = {}                                 # contract -> its own evidence text (for active)
    for n in sg.nodes:
        if n.kind == "contract" and n.evidence:
            ctx_text[n.contract] = " ".join((h.get("text") or "").lower() for h in n.evidence)

    for n in sg.nodes:                                            # silver leg (driver nodes only)
        if n.kind == "driver" and silver_lookup and n.prior.get("silver_ref"):
            try:
                n.silver = silver_lookup(n.contract, n.id, asof)
            except Exception:  # noqa: BLE001 — a silver miss must never break the answer
                n.silver = {"ref": n.prior.get("silver_ref"), "live": False}
        if n.kind == "driver":
            named = n.id.replace("_", " ").lower() in ctx_text.get(n.contract, "")
            n.active = bool(n.evidence) or named              # slice evidence OR named in the contract's evidence

    # ── regime firing DECOUPLED from the walk — but only MEANINGFUL firing ───────────────────────────────
    # The first regime-fix eval taught us the hard way (PIT 4.1->3.7, halluc 61->72): firing off "the driver
    # is mentioned somewhere in history" made the reasoner assert live regime state the evidence never
    # supported. A regime may now count a driver ONLY on dated slice evidence WITHIN `recency_days` BEFORE
    # the as-of (receipt recorded: {date, source}); no as-of -> nothing to anchor "now" -> nothing fires
    # (regime definitions still reach the reasoner as structure); a driver merely NAME-DROPPED in the
    # contract's evidence keeps its display `active` flag but never fires a regime.
    sg.fired_regimes = []
    regime_basis: dict[str, dict] = {}
    vetoed: dict[str, dict] = {}                                   # contract -> {driver: normal silver reading}
    budget = {"left": probe_cap}
    asof_s = str(asof)[:10] if asof else None
    floor = None
    if asof_s:
        import datetime as _dt
        try:
            floor = (_dt.date.fromisoformat(asof_s) - _dt.timedelta(days=recency_days)).isoformat()
        except ValueError:
            asof_s = None                                          # unparseable as-of -> treat as none

    if asof_s and floor:
        def _recent(props):
            """Newest prop dated within [asof - recency_days, asof], as a receipt — or None."""
            best = None
            for h in props or []:
                d = str(h.get("date") or "")[:10]
                if d and floor <= d <= asof_s and (best is None or d > best["date"]):
                    best = {"date": d, "source": h.get("source", "")}
            return best

        probe_cache: dict[tuple, Optional[dict]] = {}
        for n in sg.nodes:                                         # reuse walk evidence when it already qualifies
            if n.kind == "driver":
                b = _recent(n.evidence)
                if b:
                    probe_cache[(n.contract, n.id)] = b

        # Probes are EXISTENCE checks ("any dated prop in the window?"), not quality retrieval — they must
        # never pay the CPU cross-encoder reranker (24 probes x ~2-4s of rerank per answer was the second
        # slowdown of the July-3 evals; a cheap dense/lex fetch is ~10x faster with identical semantics).
        probe = probe_retrieve or retrieve

        # ── F3: probes run CONCURRENTLY, but selection stays deterministic BY CONSTRUCTION ────────────────
        # Three phases, and the split is the whole point. A naive pool.map over the shared budget["left"]
        # counter would make WHICH drivers get probed depend on thread completion order -> different
        # fired_regimes -> different answers. Instead:
        #   (1) _plan walks the SAME sorted(cid) x sorted(d) order with the SAME budget arithmetic and
        #       resolves everything that is not a slice probe — the walk-evidence pre-seed, and the
        #       silver-first observed/normal verdicts (memo-warm from the prefetch above). It appends the
        #       ADMITTED probes to `probe_plan` and never calls `probe`, so the admitted set + n_probes +
        #       the `vetoed` insertion order are identical to the old serial loop.
        #   (2) _run_probes executes that FROZEN list at width _PROBE_WORKERS.
        #   (3) the firing loop below consumes probe_cache in the FROZEN order.
        # Correctness does NOT rest on the cap binding (it saturates 24/24 on hybrid but a reasoning turn
        # logged n_probes=11) — the frozen list is byte-identical to the serial selection either way.
        # Thread-safety comes free: the workers touch nothing shared (probe/`_recent` read-only closures),
        # and probe_cache/vetoed/budget are written ONLY on this thread. silver_lookup's single-flight is
        # therefore not load-bearing here — phase 1 calls it serially, exactly as before.
        probe_plan: list[tuple] = []                               # frozen [((cid, did), slice_path)], in order

        def _plan(cid: str, did: str) -> None:
            key = (cid, did)
            if key in probe_cache:
                return
            # SILVER FIRST (F4): an OBSERVED anomalous value at the as-of vintage is the strongest
            # receipt; a live-and-NORMAL value VETOES the driver — documented chatter cannot fire a
            # regime the observed data contradicts. Inconclusive/miss -> the text semantics decide.
            if silver_lookup is not None:
                sv = silver_lookup(cid, did, asof)
                if sv and sv.get("live"):
                    if sv.get("verdict") == "observed":
                        basis = {"kind": "observed", "date": sv.get("knowledge_date", ""),
                                 "source": sv.get("ref", "silver"), "value": sv.get("value"),
                                 "unit": sv.get("unit", ""), "z": sv.get("z"),
                                 "detail": sv.get("detail", "")}
                        if sv.get("intensity") is not None:    # T1: forward ONLY when present ([SKEPTIC F1])
                            basis["intensity"] = sv["intensity"]
                        probe_cache[key] = basis
                        return
                    if sv.get("verdict") == "normal":
                        vetoed.setdefault(cid, {})[did] = {"value": sv.get("value"), "z": sv.get("z"),
                                                           "unit": sv.get("unit", ""),
                                                           "source": sv.get("ref", "silver"),
                                                           "date": sv.get("knowledge_date", "")}
                        probe_cache[key] = None
                        return
            sp = slice_path(did) if did in backed else None
            if sp and budget["left"] > 0:                          # asof-guarded slice probe, recency-tested
                budget["left"] -= 1
                probe_plan.append((key, sp))
            else:
                probe_cache[key] = None

        def _run_probes(plan: list[tuple]) -> None:
            """Execute the frozen probe list and merge into probe_cache in the FROZEN order. Results are
            collected by INDEX (never as_completed), so completion order cannot reach the caller; and
            .result() surfaces the FIRST failing probe in frozen order — the serial loop's semantics."""
            # D-MW-6: the SECOND rerank seam in this module (the collector-seam inventory names three).
            # A probe reranks whenever `probe_retrieve` is None — the serving default — so a turn whose
            # only reranks are probes must still stamp its lane. `adopt_lane` is nested-safe, which is
            # what makes ONE `_one` correct in BOTH branches below: the sequential branch runs on the
            # caller's own thread, where installing-and-clearing would strip the turn's own collector.
            _lane_rk, _parent_lane = None, None
            try:
                from leviathan.graphrag import rankers as _lane_rk
                _parent_lane = _lane_rk.lane_collector()
            except Exception:  # noqa: BLE001 — telemetry must never break a walk
                _lane_rk, _parent_lane = None, None

            def _one(item):
                if _parent_lane is None:
                    return _recent(list(probe(query, item[1], k=2, asof=asof, near=near)))
                with _lane_rk.adopt_lane(_parent_lane):
                    return _recent(list(probe(query, item[1], k=2, asof=asof, near=near)))
            if _PROBE_WORKERS <= 1 or len(plan) <= 1:              # sequential: exact pre-F3 call pattern
                out = [_one(it) for it in plan]
            else:
                import concurrent.futures as cf
                # NOT a `with` block: ThreadPoolExecutor.__exit__ is shutdown(wait=True), so a raising probe
                # would then BLOCK on every QUEUED probe as well — 3 waves x a 300,000 ms pg statement
                # timeout on a starved DB, i.e. a floor turn 3x SLOWER than the serial loop it replaces (the
                # serial loop aborted on the FIRST failure). cancel_futures drops the not-yet-started ones;
                # the <=_PROBE_WORKERS already running finish in the background and touch nothing we read.
                pool = cf.ThreadPoolExecutor(max_workers=min(_PROBE_WORKERS, len(plan)))
                futs = []
                try:
                    futs = [pool.submit(_one, it) for it in plan]
                    out = [f.result() for f in futs]
                finally:
                    # Diff-review catch (D-MW P1): a still-RUNNING probe holds a direct reference to the
                    # turn's collector and can record a rerank/fallback AFTER the turn snapshots — an
                    # undercount the gate clause `fallbacks == 0` would read as clean. The strand is
                    # COUNTED into the collector before shutdown; D-MW-8's pre-flight requires
                    # `stranded == 0` alongside `fallbacks == 0`, so a stranded turn is never a gate row.
                    try:
                        _n_live = sum(1 for f in futs if not f.done())
                        if _n_live and _parent_lane is not None:
                            _parent_lane.record_stranded(_n_live)
                    except Exception:  # noqa: BLE001 — telemetry must never break a walk
                        pass
                    pool.shutdown(wait=False, cancel_futures=True)
            for (key, _sp), res in zip(plan, out):
                probe_cache[key] = res

        # The firing order, materialised ONCE so phases 1 and 3 provably walk the same sequence.
        firing_order = [(cid, sorted({d for s in graph.contracts[cid].convergence for d in s.drivers}))
                        for cid in sorted({n.contract for n in sg.nodes}) if cid in graph.contracts]
        for cid, required in firing_order:                         # (1) freeze
            for d in required:
                _plan(cid, d)
        _run_probes(probe_plan)                                    # (2) execute concurrently
        for cid, required in firing_order:                         # (3) consume, frozen order
            bases = {}
            for d in required:
                b = probe_cache.get((cid, d))
                if b:
                    bases[d] = b
            regime_basis[cid] = bases
            for fr in graph.regimes(cid, sorted(bases)):
                sg.fired_regimes.append({"contract": cid, "name": fr.name, "direction": fr.direction,
                                         "matched": fr.matched, "threshold": fr.threshold,
                                         "basis": {d: bases[d] for d in fr.matched if d in bases},
                                         "interactions": fr.interactions, "note": fr.note})
                # F7 `regime`: ONE event the instant THIS regime fires, carrying the receipt the firing rule
                # already computed — so the UI can show WHY, not just that. The basis is PROJECTED to
                # {date, source} per the pinned contract: the richer internal basis also holds value/z/detail,
                # which belong to the note, not the feed. Deterministic engine output -> no verifier
                # reconciliation needed (an engine cannot fabricate its own firing). The projection is built
                # INSIDE the None guard so a non-streamed walk does ZERO extra work (invariant 2) — _emit_stage
                # only swallows what happens after it is called, not its argument expressions.
                if on_stage is not None:
                    _emit_stage(on_stage, "regime", contract=cid, regime=fr.name, direction=fr.direction,
                                basis={d: {"date": str((bases[d] or {}).get("date") or ""),
                                           "source": str((bases[d] or {}).get("source") or "")}
                                       for d in fr.matched if d in bases})
    sg.trace["n_evidence"] = sum(len(n.evidence) for n in sg.nodes)
    # D-MW-17 TOKEN-DENOMINATED BUDGET — DESIGN-TIME EVALUATION ONLY, NO BEHAVIOR CHANGE. The walk's budget
    # is denominated in ROWS, but a chain-intermediate node holding 1-2 receipts and a fat evidence node
    # cost the prompt window wildly different amounts. This is the measurement that would decide whether a
    # later wave re-denominates the budget in tokens; the P3 record reports its distribution at 16 vs 32.
    # TALLIED HERE, BESIDE n_evidence, NOT INSIDE _fill (recorded deviation from the plan's one-line
    # sketch): _fill runs in the concurrent pool, so a tally there is either a shared mutable counter under
    # a lock or a pre-cap number. Post-cap is also the DECISION-RELEVANT number — these are exactly the
    # rows that reach the prompt, on the same denominator as n_evidence.
    sg.trace["n_evidence_chars"] = sum(len(h.get("text") or "") for n in sg.nodes for h in (n.evidence or []))
    sg.trace["active"] = [list(n.key) for n in sg.nodes if n.active]
    sg.trace["regime_basis"] = regime_basis
    sg.trace["n_probes"] = probe_cap - budget["left"]
    sg.trace["silver_veto"] = vetoed                               # drivers observed NORMAL (excluded from firing)
    # Phase timings (ms) — ride the `walking` SSE stage + the result trace, so a latency probe can see exactly
    # where the walk's time goes (fill = parallel evidence fetch + coalesced rerank; rest = silver + firing).
    _t_end = _time.perf_counter()
    sg.trace["ground_ms"] = {"fill": int((_t_fill - _t0) * 1000), "rest": int((_t_end - _t_fill) * 1000)}
    return sg


# ── mermaid: the cascade diagram FROM THE GRAPH (not the LLM) ─────────────────────────────────────────────────
def _mid(kind: str, contract: str, id_: str) -> str:
    import re
    return re.sub(r"[^0-9a-zA-Z_]", "_", f"{kind[0]}_{contract}_{id_}")


def graph_to_mermaid(sg: Subgraph, graph: gph.CausalGraph) -> str:
    """Deterministic cascade skeleton over the KEPT nodes: parent-driver -> driver -> contract price, plus
    tracked cross-commodity hops. Signs ride in the labels. Overrides the LLM's diagram at serving time."""
    kept = {n.key for n in sg.nodes}
    lines = ["flowchart LR"]
    price = {}                                             # one price node per contract in the subgraph
    for n in sg.nodes:
        if n.kind == "contract":
            pid = _mid("p", n.contract, "price")
            price[n.contract] = pid
            lines.append(f'{pid}["{n.contract.replace("_", " ")} price"]')
    for n in sg.nodes:
        if n.kind != "driver":
            continue
        did = _mid("driver", n.contract, n.id)
        sign = n.prior.get("sign", "")
        lines.append(f'{did}["{n.id.replace("_", " ")} {sign}"]')
        tgt = price.get(n.contract) or _mid("p", n.contract, "price")
        lines.append(f"{did} --> {tgt}")
        for p in graph.driver(n.contract, n.id).parents:   # upstream cascade edge, if the parent was kept
            if ("driver", n.contract, p) in kept:
                lines.append(f'{_mid("driver", n.contract, p)} --> {did}')
    for n in sg.nodes:                                     # cross-commodity hops between kept contracts
        if n.kind == "contract" and n.via_edge:
            frm = n.via_edge.get("_from")
            if frm and frm in price:
                lines.append(f'{price[frm]} -->|{n.via_edge.get("relation","")} {n.via_edge.get("sign","")}| '
                             f'{price.get(n.contract, _mid("p", n.contract, "price"))}')
    return "\n".join(lines)
