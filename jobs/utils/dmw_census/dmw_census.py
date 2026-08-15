"""D-MW-27 STEP-0 INVERSION CENSUS -- THE PRODUCER, REBUILT FOR T2-1 (2026-08-15).

WHY THIS FILE EXISTS AT ALL. The P6-era `data/dmw_p6_census.json` was authored on 2026-08-12 by an ad-hoc
pass that was never committed (checked: `jobs/utils/`, `scripts/graphrag/`, and the MOAT_WIDTH_WAVE_PLAN
STEP-0 record name no producer, and nothing in the repo writes the path). T2-1
(docs/private/CASCADE_HOME_AND_SMALL_ITEMS_PLAN.md) re-keys `graph.rev_cross_links` by `node_for(seed)` and
RE-DERIVES the census against the re-keyed graph -- which is impossible to do honestly from a artifact whose
derivation nobody can re-run. So the producer is rebuilt here, B0-style: offline, $0, deterministic, and
FAITHFUL TO THE COMMITTED ARTIFACT'S SCHEMA row for row.

THE FAITHFULNESS PROOF IS PART OF THE TOOL, NOT A CLAIM ABOUT IT. `--verify-legacy <path>` re-derives every
block whose content the re-key CANNOT touch (the resolution rule is untouched: same two-step alias
resolution, same lexicographic-first tie-break, same three buckets, same 117 edges, same 94 inverted pairs,
same 87 qualifying, same 63 deck-eligible) and diffs it against the committed P6 artifact. It reproduces
that artifact exactly. Only then are the blocks the re-key DOES move re-derived and written.

AND IT ALSO ASSERTS THE SCHEMA IS A SUPERSET (added 2026-08-15 by review finding). The value diff above
covers only `_INVARIANT_BLOCKS`; the first cut of this rebuild silently DROPPED five `summary` keys --
`deck_shrink_verdict`, `n_deck_eligible_seeds`, `deck_eligible_by_seed`, `n_pairs_failing_backed`,
`n_pairs_failing_slice_distinct` -- and `--verify-legacy` printed "0 block(s) differ" over the loss because
`summary` is not, and cannot be, a re-key-invariant block. A key present in the reference and absent from
the rebuild is now a FAILURE. Added keys are fine and are listed.

WHAT THE RE-KEY MOVES, AND WHAT IT DOES NOT:
  MOVES     which CONTRACTS reach an inverted edge (15 -> 24 of 33; corn_cbot 0 -> 19), the index key
            (contract -> node), `summary.seeds_with_pairs` (now seed NODES), `zero_pair_decomposition`'s
            residue (18 -> 9), `node_keyed_view.STATUS` (RECORDED -> APPLIED).
  DOES NOT   the resolution rule, the recorded tie-breaks, the three buckets (94/23/0), the base-yaml
            fence, the qualification rule, `deck_eligible_pairs` (63 entries, same pairs, same order) or
            `deck_candidates_one_per_seed` (15). The (seed, foreign) contract-keyed join AND the
            (seed_node, foreign_node) node-keyed join both stay READABLE off the same entries -- T2-3.D
            requires both column families to be present and takes ONE of them as the join.

  BUT READABLE IS NOT SOUND, AND THE TWO SPELLINGS ARE NO LONGER EQUIVALENT. Because `deck_eligible_pairs`
  is unchanged, its `seed` column still lists only the 15 tie-break WINNERS, while the walk's `ancestor_of`
  can now be any co-node sibling. The contract-keyed join is therefore BLIND on exactly the seed contracts
  T2-1 enfranchises -- all 9 of them, zero deck rows each. `summary`-adjacent block
  `index_keying.T2_3_join_soundness` measures this per gained contract, and it exists because T2-3.D spends
  a paragraph fencing this hazard on the FOREIGN half and T2-1 re-opened it on the SEED half.

USAGE (from anywhere; paths are absolute off ROOT):
    python jobs/utils/dmw_census/dmw_census.py --verify-legacy data/dmw_p6_census.json
    python jobs/utils/dmw_census/dmw_census.py --out data/dmw_p6_census.json

Pure/offline: reads configs/graphrag/causal/*.yaml, configs/graphrag/commodity_hierarchy.yaml and the
evidence slice listing. No LLM, no AWS, no embedding, no network. ASCII only.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from leviathan.graphrag import evidence as ev  # noqa: E402
from leviathan.graphrag import graph as g  # noqa: E402

# ── the recorded prose, carried verbatim from the P6 artifact where the FACT is unchanged ────────────────
RECORD = "D-MW-27 STEP-0 INVERSION CENSUS (task #51, D-MW P6) -- RE-DERIVED FOR T2-1 (task #55, node-keyed)"
METHOD = ("offline parse of configs/graphrag/causal/*.yaml + the inverted _hier() map "
          "(configs/graphrag/commodity_hierarchy.yaml); no LLM, no AWS, no embedding")
DIRECTION = ("a contract's YAML declares who DRIVES it; the census INVERTS that -> seed = resolve("
             "driver_commodity), foreign = the DECLARING contract (the market the seed cascades into)")
RESOLUTION_RULE_WHY = (
    "the plan's prose ('driver_commodity -> node via the inverted _hier() map') reads literally as a direct "
    "node-key lookup, which strands the 13 edges whose driver_commodity names a CONTRACT ID that is not "
    "itself a node (corn_cbot x4, soft_red_winter_wheat_cbot x3, soybeans_cbot x2, canola_ice, "
    "hard_red_spring_wheat_mgex, south_african_white_maize_jse, soybeans_no_2_dce). The plan's OWN round-3 "
    "enumeration settles it: the unresolvable-by-construction classes are exactly wheat + sunflower_oil/"
    "sorghum/barley/ethanol = 23 edges, which only the two-step reading produces. The literal reading is "
    "recorded below for revisit.")
RESOLUTION_RULE_APPLIED = ("driver_commodity -> node_for() -> the inverted _hier() map -> tracked "
                           "contract-id set -> lexicographic-first")
QUALIFICATION_RULE = {
    "backed": "node_for(foreign) has an evidence/<node>.jsonl slice",
    "slice_distinct": "node_for(foreign) != node_for(seed) (co-node with the seed = degenerate)",
}
DECK_ELIGIBILITY_RULE = {
    "on_top_of": "backed AND slice_distinct",
    "foreign_co_node_dedup": ("one representative per (seed, foreign_node) -- co-node foreigns share ONE "
                              "evidence slice, so a second row measures the same block; representative = "
                              "lexicographic-first hierarchy contract"),
    "base_yaml_fence": ("`corn` and `soybeans` are BASE yamls, not tradeable contracts (absent from "
                        "commodity_hierarchy contracts, no exchange/origin) and byte-duplicate their _cbot "
                        "variants' inter_commodity sets -- excluded as foreign targets; D-MW-28's "
                        "rev_cross_links needs this fence or the paid slot can buy a phantom contract "
                        "block"),
}
NODE_KEYED_WHY = (
    "planner._seed_contracts already de-dupes seeds to distinct commodity NODES (siblings share one "
    "evidence slice), so the runtime seed identity is the NODE. Keying rev_cross_links by node_for(seed) "
    "instead of by the tie-break winner gives every co-node contract the same inverted edges at zero extra "
    "cost and with no change to the resolution rule or the recorded tie-breaks.")
ZERO_PAIR_FINDING = (
    "alias resolution buys EDGES (52 -> 94, +42) but almost no SEEDS (13 -> 15, 20 -> 18 zero-pair "
    "contracts), because the lexicographic-first tie-break funnels every edge of a multi-contract node onto "
    "ONE contract id. corn_cbot -- the US corn benchmark and the most-routed contract in the product -- "
    "ends with ZERO inverted pairs while its node `corn` carries 20 edges (16 'corn' + 4 'corn_cbot'), all "
    "of them funnelled to campinas_corn_reference_bmf.")
ZERO_PAIR_REMEDY = (
    "T2-1 (2026-08-15) APPLIED THE NODE KEY. The funnel is gone: the 20 node-corn edges (19 after the "
    "base-yaml fence drops the one declared by `corn` itself) are reachable from campinas_corn_reference_"
    "bmf, corn_cbot, french_maize_matif AND the base `corn` yaml alike. 15 -> 24 of 33 loaded contracts "
    "reach an inverted edge; the 9 that still do not are the contracts NO ONE declares as a driver, which "
    "is a curation fact (the 10 config-only wheat-edge renames are the recorded follow-on), not a keying "
    "one.")
PLAN_ROUND2_CLAIM = "a naive inversion leaves 20/33 contracts with ZERO inverted pairs"

_INVARIANT_BLOCKS = ("totals", "buckets", "unresolvable_no_node_classes", "tie_breaks_recorded",
                     "alias_classes", "resolution_table", "inverted_pairs_all", "qualifying_pairs",
                     "qualification_rule", "deck_eligible_pairs", "deck_candidates_one_per_seed",
                     "deck_eligibility_rule", "inputs")


def _derive() -> dict:
    """Every derived block, from the shipped graph + the shipped hierarchy + the shipped slice listing.

    NOTE ON INDEPENDENCE: the pair/deck blocks are derived from `rev_cross_link_resolution()` (the
    per-EDGE table, which the re-key does not touch), NEVER from `rev_cross_links()` (the index, which it
    does). That is what lets one producer emit both the legacy contract-keyed view and the node-keyed one
    and lets `--verify-legacy` mean something."""
    G = g.CausalGraph.load()
    hier = {k: (v.get("node") or k) for k, v in (ev._hier().get("contracts") or {}).items()
            if isinstance(v, dict)}
    covered = set(ev.covered_nodes())
    nodes = set(hier.values())
    loaded = set(G.contracts)

    def node_of(x):
        return hier.get(x, x)

    # the base-yaml fence, computed exactly as graph._invert_inter_commodity computes it
    untradeable = {c for c in loaded if c not in hier
                   and any(o != c and o in hier and hier[o] == node_of(c) for o in loaded)}

    # ── the resolution table (one row per inter_commodity edge) ───────────────────────────────────────
    table = []
    for r in G.rev_cross_link_resolution():
        table.append({"declaring_contract": r["declaring_contract"], "declaring_node":
                      node_of(r["declaring_contract"]), "idx": r["idx"],
                      "driver_commodity": r["driver_commodity"], "relation": r["relation"],
                      "sign": r["sign"], "lag": r["lag"], "mechanism": r["mechanism"], "blurb": r["blurb"],
                      "bucket": r["bucket"], "node": r["node"], "candidates": r["candidates"],
                      "tracked_candidates": r["tracked_candidates"], "seed": r["seed"],
                      "tie_break": r["tie_break"],
                      "driver_commodity_is_contract_id": r["driver_commodity"] in loaded,
                      "driver_commodity_is_node": r["driver_commodity"] in nodes,
                      # THE LITERAL READING, recorded for revisit: a DIRECT node-key lookup, which strands
                      # every contract-id-valued driver_commodity that is not itself a node.
                      "literal_prose_bucket": ("resolved" if r["driver_commodity"] in nodes
                                               else "unresolvable-no-node")})

    # ── the inverted pairs ────────────────────────────────────────────────────────────────────────────
    pairs = []
    for r in table:
        if r["bucket"] != "resolved":
            continue
        seed, foreign = r["seed"], r["declaring_contract"]
        pairs.append({"seed": seed, "seed_node": node_of(seed), "seed_backed": node_of(seed) in covered,
                      "foreign": foreign, "foreign_node": node_of(foreign),
                      "foreign_is_hierarchy_contract": foreign in hier,
                      "driver_commodity": r["driver_commodity"], "relation": r["relation"],
                      "sign": r["sign"], "lag": r["lag"], "mechanism": r["mechanism"],
                      "blurb": r["blurb"],
                      "backed": node_of(foreign) in covered,
                      "slice_distinct": node_of(foreign) != node_of(seed)})
    for p in pairs:
        p["qualifies"] = p["backed"] and p["slice_distinct"]
    # STABLE sort on (seed, foreign): the table arrives in (declaring contract, declaration index) order, so
    # two edges of one pair keep their declaration order and `duplicate_edge` always flags the LATER one.
    pairs.sort(key=lambda p: (p["seed"], p["foreign"]))
    seen = set()
    for p in pairs:
        k = (p["seed"], p["foreign"])
        p["duplicate_edge"] = k in seen
        seen.add(k)
    qualifying = [p for p in pairs if p["qualifies"] and not p["duplicate_edge"]]

    # ── deck eligibility: + the base-yaml fence, + one representative per (seed, foreign_node) ─────────
    best = {}
    for p in qualifying:
        if p["foreign"] in untradeable:
            continue
        k = (p["seed"], p["foreign_node"])
        if k not in best or p["foreign"] < best[k]["foreign"]:
            best[k] = p
    deck = sorted(best.values(), key=lambda p: (p["seed"], p["foreign_node"]))
    one_per_seed = {}
    for p in sorted(deck, key=lambda p: (p["seed"], p["foreign"])):
        one_per_seed.setdefault(p["seed"], p)
    per_seed_n = collections.Counter(p["seed"] for p in deck)
    candidates = [one_per_seed[s] for s in sorted(one_per_seed, key=lambda s: (-per_seed_n[s], s))]

    # ── alias classes + tie-breaks ────────────────────────────────────────────────────────────────────
    alias = {}
    for r in table:
        dc = r["driver_commodity"]
        a = alias.setdefault(dc, {"n_edges": 0, "declared_by": [], "bucket": r["bucket"],
                                  "node": r["node"], "candidates": r["candidates"],
                                  "tracked_candidates": r["tracked_candidates"], "seed": r["seed"],
                                  "tie_break": r["tie_break"],
                                  "is_contract_id": r["driver_commodity_is_contract_id"],
                                  "is_node": r["driver_commodity_is_node"],
                                  "literal_prose_bucket": r["literal_prose_bucket"]})
        a["n_edges"] += 1
        # ONE ENTRY PER EDGE, not per contract: a contract declaring the same alias twice is counted twice,
        # which is what makes `n_edges == len(declared_by)` readable. Table order is already (contract, idx).
        a["declared_by"].append(r["declaring_contract"])
    alias = {k: v for k, v in sorted(alias.items())}
    ties = {k: {"node": v["node"], "candidates": v["candidates"], "chosen_seed": v["seed"],
                "rule": v["tie_break"], "n_edges": v["n_edges"]}
            for k, v in alias.items() if v["tie_break"] == "lexicographic-first"}
    no_node_classes = {k: v["n_edges"] for k, v in alias.items() if v["bucket"] == "unresolvable-no-node"}

    # ── the two keyings, side by side ─────────────────────────────────────────────────────────────────
    #   contract-keyed (the P6-era rule): a contract reaches edges iff it IS the tie-break winner.
    #   node-keyed (T2-1, SHIPPED): a contract reaches edges iff its NODE is a tie-break winner's node.
    indexed = [p for p in pairs if p["foreign"] not in untradeable]
    seeds_ck = sorted({p["seed"] for p in indexed})
    seed_nodes = sorted({p["seed_node"] for p in indexed})
    reach_nk = sorted(c for c in loaded if node_of(c) in set(seed_nodes))
    counts_ck = {c: sum(1 for p in indexed if p["seed"] == c) for c in sorted(loaded)}
    counts_nk = {c: sum(1 for p in indexed if p["seed_node"] == node_of(c)) for c in sorted(loaded)}

    naive_seeds = sorted({r["driver_commodity"] for r in table if r["driver_commodity"] in loaded})
    naive_zero = sorted(loaded - set(naive_seeds))

    inv_hier = {}
    for c in hier:                                   # key order = hierarchy YAML order; values sorted
        inv_hier.setdefault(hier[c], []).append(c)
    inv_hier = {k: sorted(v) for k, v in inv_hier.items()}

    return {"G": G, "hier": hier, "covered": covered, "nodes": nodes, "loaded": loaded,
            "untradeable": untradeable, "node_of": node_of, "table": table, "pairs": pairs,
            "qualifying": qualifying, "deck": deck, "candidates": candidates, "alias": alias,
            "ties": ties, "no_node_classes": no_node_classes, "seeds_ck": seeds_ck,
            "seed_nodes": seed_nodes, "reach_nk": reach_nk, "counts_ck": counts_ck,
            "counts_nk": counts_nk, "naive_seeds": naive_seeds, "naive_zero": naive_zero,
            "inv_hier": inv_hier, "per_seed_n": per_seed_n}


def _invariant_blocks(d: dict) -> dict:
    """The blocks the re-key CANNOT move. `--verify-legacy` diffs exactly these against the P6 artifact."""
    G, table, pairs = d["G"], d["table"], d["pairs"]
    node_of, hier, loaded = d["node_of"], d["hier"], d["loaded"]
    b = collections.Counter(r["bucket"] for r in table)
    lit = collections.Counter(r["literal_prose_bucket"] for r in table)
    return {
        "inputs": {
            "causal_yamls": len(loaded),
            "loaded_contracts": sorted(loaded), "n_loaded_contracts": len(loaded),
            "hierarchy_contracts": sorted(hier), "n_hierarchy_contracts": len(hier),
            "non_hierarchy_loaded_contracts": sorted(loaded - set(hier)),
            "nodes": sorted(d["nodes"]), "n_nodes": len(d["nodes"]),
            "evidence_covered_nodes": sorted(d["covered"]), "n_covered_nodes": len(d["covered"]),
            "inverted_hier_map": d["inv_hier"],
        },
        "totals": {
            "inter_commodity_edges": len(table),
            "resolved": b["resolved"],
            "unresolvable_no_node": b["unresolvable-no-node"],
            "unresolvable_no_contract": b["unresolvable-no-contract"],
            "naive_inversion_tracked_edges": sum(1 for r in table if r["driver_commodity"] in loaded),
            "driver_commodity_strings_not_contract_ids": sum(1 for r in table
                                                             if r["driver_commodity"] not in loaded),
            "edges_rescued_by_alias_resolution": (b["resolved"]
                                                  - sum(1 for r in table
                                                        if r["driver_commodity"] in loaded)),
        },
        # THE DECOMPOSITION ITSELF, not its counts (the counts live in `totals`): the three buckets carry
        # their resolution-table ROWS, so a shrink decision can read WHICH edges landed where.
        "buckets": {"resolved": [r for r in table if r["bucket"] == "resolved"],
                    "unresolvable_no_node": [r for r in table if r["bucket"] == "unresolvable-no-node"],
                    "unresolvable_no_contract": [r for r in table
                                                 if r["bucket"] == "unresolvable-no-contract"]},
        "unresolvable_no_node_classes": d["no_node_classes"],
        "tie_breaks_recorded": d["ties"],
        "alias_classes": d["alias"],
        "resolution_table": table,
        "inverted_pairs_all": pairs,
        "qualifying_pairs": d["qualifying"],
        "qualification_rule": QUALIFICATION_RULE,
        "deck_eligible_pairs": d["deck"],
        "deck_candidates_one_per_seed": d["candidates"],
        "deck_eligibility_rule": DECK_ELIGIBILITY_RULE,
        "_literal": {"resolved": lit["resolved"], "unresolvable-no-node": lit["unresolvable-no-node"]},
        "_node_of": node_of, "_G": G,
    }


def _self_tests(d: dict, inv: dict) -> dict:
    """The artifact's OWN checks. The P6 names are kept (a renamed check is an unnoticed dropped check) and
    the T2-1 ones are appended, including the one that matters most: the SHIPPED index equals this census's
    node-keyed derivation, contract by contract."""
    G, table, node_of = d["G"], d["table"], d["node_of"]
    errors = []
    out = collections.OrderedDict()
    out["edge_count_117"] = len(table) == 117
    out["buckets_sum_to_edges"] = (inv["totals"]["resolved"] + inv["totals"]["unresolvable_no_node"]
                                   + inv["totals"]["unresolvable_no_contract"]) == len(table)
    out["plan_52_tracked_65_alias_arithmetic"] = (
        inv["totals"]["naive_inversion_tracked_edges"] == 52
        and inv["totals"]["driver_commodity_strings_not_contract_ids"] == 65)
    out["no_node_classes_match_plan_round3_enumeration"] = (
        set(d["no_node_classes"]) == {"wheat", "sunflower_oil", "sorghum", "barley", "ethanol"})
    out["wheat_is_the_10_edge_largest_class"] = d["no_node_classes"].get("wheat") == 10 and \
        d["no_node_classes"]["wheat"] == max(d["no_node_classes"].values())
    # inversion parity: every resolved+tradeable edge is exactly one index row, and nothing else is
    fwd = {(c, i): e for c in G.contracts for i, e in enumerate(G.cross_links(c))}
    hit = 0
    for r in table:
        if r["bucket"] != "resolved" or r["declaring_contract"] in d["untradeable"]:
            continue
        rows = [x for x in G.rev_cross_links(r["seed"])
                if (x["contract"], x["idx"]) == (r["declaring_contract"], r["idx"])]
        if len(rows) != 1 or rows[0]["mechanism"] != fwd[(r["declaring_contract"], r["idx"])]["mechanism"]:
            errors.append("inversion parity: %s#%s" % (r["declaring_contract"], r["idx"]))
        hit += 1
    total_rows = sum(len(G.rev_cross_links(s)) for s in d["seed_nodes"])
    out["inversion_parity_vs_forward_map"] = (not errors) and total_rows == hit
    out["every_seed_is_a_loaded_contract"] = all(p["seed"] in d["loaded"] for p in d["pairs"])
    out["every_seed_is_backed"] = all(p["seed_backed"] for p in d["pairs"])
    out["plan_20_of_33_naive_zero_pair_claim"] = len(d["naive_zero"]) == 20
    out["no_unbacked_foreign_among_hierarchy_contracts"] = all(
        p["backed"] for p in d["pairs"] if p["foreign_is_hierarchy_contract"])
    out["node_for_parity_vs_evidence_py"] = "PASS" if all(
        G.contract_node(c) == ev.node_for(c) for c in G.contracts) else "FAIL"
    out["cross_links_forward_parity_vs_graph_py"] = "PASS" if len(fwd) == len(table) else "FAIL"
    # ── T2-1 ──────────────────────────────────────────────────────────────────────────────────────────
    out["t2_1_index_is_node_keyed"] = sorted(G._rev_index) == d["seed_nodes"]
    out["t2_1_shipped_index_matches_this_censuss_node_keyed_derivation"] = all(
        len(G.rev_cross_links(c)) == d["counts_nk"][c] for c in sorted(d["loaded"]))
    out["t2_1_every_co_node_contract_sees_the_SAME_rows"] = all(
        [(x["contract"], x["idx"]) for x in G.rev_cross_links(a)]
        == [(x["contract"], x["idx"]) for x in G.rev_cross_links(b)]
        for members in d["inv_hier"].values() for a in members[:1] for b in members)
    out["t2_1_corn_cbot_reaches_node_corns_edges"] = (
        d["counts_ck"]["corn_cbot"] == 0 and d["counts_nk"]["corn_cbot"] == 19
        and len(G.rev_cross_links("corn_cbot")) == 19)
    out["t2_1_buckets_and_deck_are_UNCHANGED_by_the_rekey"] = (
        G.rev_cross_link_buckets()["resolved"] == inv["totals"]["resolved"] == 94
        and G.rev_cross_link_buckets()["unresolvable-no-node"] == 23 and len(d["deck"]) == 63)
    out["t2_1_rev_cross_links_never_raises_on_unknown_or_node_ids"] = (
        G.rev_cross_links("no_such_contract") == [] and G.rev_cross_links("wheat") == [])
    out["errors"] = errors
    return out


def build() -> dict:
    d = _derive()
    inv = _invariant_blocks(d)
    lit = inv.pop("_literal")
    inv.pop("_node_of")
    inv.pop("_G")
    G = d["G"]
    counts_ck, counts_nk = d["counts_ck"], d["counts_nk"]
    qual_by_seed = {}
    for p in d["qualifying"]:
        qual_by_seed.setdefault(p["seed"], []).append(p["foreign"])
    qual_by_seed = {k: sorted(v) for k, v in sorted(qual_by_seed.items())}
    qual_by_node = {}
    for p in d["qualifying"]:
        qual_by_node.setdefault(p["seed_node"], set()).add(p["foreign"])
    qual_by_node = {k: sorted(v) for k, v in sorted(qual_by_node.items())}

    out = collections.OrderedDict()
    out["record"] = RECORD
    out["date"] = datetime.date.today().isoformat()
    out["cost_usd"] = 0.0
    out["method"] = METHOD
    out["producer"] = "jobs/utils/dmw_census/dmw_census.py"
    out["direction"] = DIRECTION
    out["index_keying"] = {
        "applied": "node -- graph.rev_cross_links(x) resolves x through contract_node(x) before the lookup",
        "ratified_by": ("docs/private/CASCADE_HOME_AND_SMALL_ITEMS_PLAN.md, TRACK 2 opening ratification "
                        "+ T2-1; the defect is recorded verbatim at graph.py's rev_cross_links docstring"),
        "superseded": "contract -- the P6-era key, the lexicographic-first tie-break WINNER",
        "what_moved": {"contracts_reaching_pairs": [len(d["seeds_ck"]), len(d["reach_nk"])],
                       "corn_cbot_pairs": [counts_ck["corn_cbot"], counts_nk["corn_cbot"]],
                       "zero_pair_contracts": [len(d["loaded"]) - len(d["seeds_ck"]),
                                               len(d["loaded"]) - len(d["reach_nk"])]},
        "what_did_not_move": {"inter_commodity_edges": inv["totals"]["inter_commodity_edges"],
                              "resolved": inv["totals"]["resolved"],
                              "unresolvable_no_node": inv["totals"]["unresolvable_no_node"],
                              "unresolvable_no_contract": inv["totals"]["unresolvable_no_contract"],
                              "n_qualifying_pairs": len(d["qualifying"]),
                              "deck_eligible_pairs": len(d["deck"]),
                              "deck_candidates_one_per_seed": len(d["candidates"]),
                              "resolution_rule": "unchanged", "tie_breaks": "unchanged",
                              "base_yaml_fence": "unchanged"},
        "T2_3_join_note": ("`deck_eligible_pairs` entries carry BOTH column families -- contract-keyed "
                           "`seed`/`foreign` and node-keyed `seed_node`/`foreign_node` -- plus `qualifies`. "
                           "T2-3.D takes ONE of them as the liveness join and writes the choice into the "
                           "freeze block; the node-keyed halves must move TOGETHER or not at all. "
                           "THE TWO SPELLINGS ARE NOT EQUALLY AVAILABLE AFTER T2-1 -- see "
                           "`T2_3_join_soundness`, which measures the contract-keyed spelling BLIND on "
                           "exactly the population T2-1 creates."),
        # ── THE T2-1 JOIN HAZARD, MEASURED (review finding, 2026-08-15) ───────────────────────────────
        # `planner._cascade_plan` stamps `ancestor_of` = the WALK's REALIZED seed contract (planner.py:642,
        # :697). Before T2-1 only the tie-break WINNER could return rev_cross_links rows, so `ancestor_of`
        # was ALWAYS one of the 15 contracts `deck_eligible_pairs` carries in its `seed` column and the
        # contract-keyed (seed, foreign) join was sound. T2-1 hands the same rows to every CO-NODE sibling
        # while `deck_eligible_pairs` is byte-identical to P6 (63 entries, the same 15 winner seeds) -- so a
        # foreign bought under a sibling has NO `seed`-column match and reads NOT LIVE under the
        # contract-keyed spelling, on the exact contracts T2-1 exists to enfranchise. The block below is
        # DERIVED, so it cannot be argued with and cannot go stale.
        "T2_3_join_soundness": {
            "hazard": ("the contract-keyed (`seed`,`foreign`) join is BLIND to every seed contract T2-1 "
                       "gained, because `deck_eligible_pairs.seed` still carries only the tie-break "
                       "WINNERS while `ancestor_of` can now be any co-node sibling"),
            "why_it_bites_exactly_here": ("`ancestor_of` is the REALIZED seed of the walk (planner.py:642, "
                                          ":697), not the deck row's `contract`; T2-3.D's liveness join "
                                          "reads it directly"),
            "deck_eligible_pairs_seed_column": sorted({p["seed"] for p in d["deck"]}),
            "deck_eligible_pairs_seed_node_column": sorted({p["seed_node"] for p in d["deck"]}),
            "seed_contracts_gained_by_T2_1": sorted(set(d["reach_nk"]) - set(d["seeds_ck"])),
            "deck_rows_reachable_per_gained_seed": {
                c: {"contract_keyed": sum(1 for p in d["deck"] if p["seed"] == c),
                    "node_keyed": sum(1 for p in d["deck"] if p["seed_node"] == d["node_of"](c))}
                for c in sorted(set(d["reach_nk"]) - set(d["seeds_ck"]))},
            "n_gained_seeds_with_zero_contract_keyed_deck_rows": sum(
                1 for c in set(d["reach_nk"]) - set(d["seeds_ck"])
                if not any(p["seed"] == c for p in d["deck"])),
            "consequence_for_T2_3_D": ("a row whose ON-arm `ancestor_of` is one of the gained contracts "
                                       "reads NOT LIVE under (`seed`,`foreign`) even though the mechanism "
                                       "fired, which can drive the '< 3 LIVE rows -> INSTRUMENT-DEAD' "
                                       "misread on a LIVE instrument -- the same failure T2-3.D already "
                                       "fences on the FOREIGN half, re-opened on the SEED half by T2-1"),
            "RECOMMENDATION_TO_THE_FREEZE_BLOCK": ("take the NODE-KEYED pair (`seed_node` against "
                                                   "evidence.node_for(ancestor_of), `foreign_node` against "
                                                   "evidence.node_for(key[1])). It is the only spelling "
                                                   "sound on the post-T2-1 seed population, and T2-3.D "
                                                   "already requires the two halves to move TOGETHER. "
                                                   "THE CHOICE IS THE ADJUDICATOR'S AND IS MADE AT THE "
                                                   "FREEZE, BEFORE ANY ARM; this census only measures it."),
        },
    }
    out["resolution_rule_reading"] = {
        "applied": RESOLUTION_RULE_APPLIED, "why": RESOLUTION_RULE_WHY,
        "literal_prose_buckets": {"resolved": lit["resolved"],
                                  "unresolvable-no-node": lit["unresolvable-no-node"]},
        "delta_vs_applied": ("literal strands 13 contract-id-valued edges as no-node (%d vs %d) and loses "
                             "13 resolved edges (%d vs %d)"
                             % (lit["unresolvable-no-node"], inv["totals"]["unresolvable_no_node"],
                                lit["resolved"], inv["totals"]["resolved"])),
    }
    out["inputs"] = inv["inputs"]
    out["totals"] = inv["totals"]
    out["buckets"] = inv["buckets"]
    out["unresolvable_no_node_classes"] = inv["unresolvable_no_node_classes"]
    out["tie_breaks_recorded"] = inv["tie_breaks_recorded"]
    out["alias_classes"] = inv["alias_classes"]
    out["resolution_table"] = inv["resolution_table"]
    out["inverted_pairs_all"] = inv["inverted_pairs_all"]
    out["qualifying_pairs"] = inv["qualifying_pairs"]
    out["qualification_rule"] = inv["qualification_rule"]
    out["deck_eligible_pairs"] = inv["deck_eligible_pairs"]
    out["deck_candidates_one_per_seed"] = inv["deck_candidates_one_per_seed"]
    out["zero_pair_decomposition"] = {
        "plan_round2_claim": PLAN_ROUND2_CLAIM,
        "naive_inversion_zero_pair_contracts": d["naive_zero"],
        "n_naive_zero": len(d["naive_zero"]),
        "plan_claim_reproduced": len(d["naive_zero"]) == 20,
        "after_alias_resolution_zero_pair_contracts": sorted(d["loaded"] - set(d["seeds_ck"])),
        "n_after_alias_resolution_zero": len(d["loaded"]) - len(d["seeds_ck"]),
        "after_node_keying_zero_pair_contracts": sorted(d["loaded"] - set(d["reach_nk"])),
        "n_after_node_keying_zero": len(d["loaded"]) - len(d["reach_nk"]),
        "n_seeds_naive": len(d["naive_seeds"]),
        "n_seeds_after_alias_resolution": len(d["seeds_ck"]),
        "n_contracts_reaching_pairs_after_node_keying": len(d["reach_nk"]),
        "FINDING": ZERO_PAIR_FINDING,
        "REMEDY": ZERO_PAIR_REMEDY,
    }
    out["node_keyed_view"] = {
        "why": NODE_KEYED_WHY,
        "seed_nodes_with_qualifying_pairs": d["seed_nodes"],
        "n_seed_nodes_with_qualifying_pairs": len(d["seed_nodes"]),
        "contracts_that_gain_cascade_under_node_keying": sorted(set(d["reach_nk"]) - set(d["seeds_ck"])),
        "n_contracts_gained": len(set(d["reach_nk"]) - set(d["seeds_ck"])),
        "zero_pair_contracts_under_node_keying": sorted(d["loaded"] - set(d["reach_nk"])),
        "n_zero_under_node_keying": len(d["loaded"]) - len(d["reach_nk"]),
        "STATUS": ("APPLIED (T2-1, 2026-08-15). The P6-era artifact recorded this block as a D-MW-29 "
                   "design input and did NOT apply it; TRACK 2 of the CASCADE_HOME plan ratified it before "
                   "any arm was designed, and this census is re-derived against the re-keyed graph."),
    }
    out["deck_eligibility_rule"] = inv["deck_eligibility_rule"]
    out["contract_pair_counts"] = {
        "note": ("rows the shipped rev_cross_links returns per LOADED contract, both keyings. "
                 "`node_keyed` is what the graph does today; `contract_keyed` is what it did at P6."),
        "contract_keyed": counts_ck, "node_keyed": counts_nk,
    }
    # ── the P6-era summary quantities, RESTORED (T2-1 review finding, 2026-08-15) ─────────────────────
    # These five keys were dropped when this producer was rebuilt, and `--verify-legacy` could not see it
    # because `summary` is not a re-key-invariant block and was therefore not in `_INVARIANT_BLOCKS`.
    # `deck_shrink_verdict` + `n_deck_eligible_seeds` are the AUTHORABILITY RECORD for the very 6-row deck
    # T2-3 fires on, so losing them silently was record loss at the worst possible moment. They are
    # DERIVED here, never carried as literals, so they cannot go stale. The schema-superset check added to
    # `--verify-legacy` is the structural half of this fix.
    deck_by_seed = {}
    for p in d["deck"]:
        deck_by_seed.setdefault(p["seed"], []).append(p["foreign"])
    deck_by_seed = {k: sorted(v) for k, v in sorted(deck_by_seed.items())}
    n_deck_seeds = len(deck_by_seed)

    out["summary"] = {
        "n_inverted_pairs": len(d["pairs"]),
        "n_distinct_pairs": sum(1 for p in d["pairs"] if not p["duplicate_edge"]),
        "n_qualifying_pairs": len(d["qualifying"]),
        "index_keying": "node",
        "seeds_with_pairs_are": ("COMMODITY NODES since T2-1 (the index key). The P6-era census listed the "
                                 "15 tie-break-winner CONTRACTS here; the count is the same 15 because the "
                                 "winner was injective onto its node, the POPULATION is not."),
        "n_seeds_with_pairs": len(d["seed_nodes"]),
        "seeds_with_pairs": d["seed_nodes"],
        "n_contracts_reaching_pairs": len(d["reach_nk"]),
        "contracts_reaching_pairs": d["reach_nk"],
        "n_deck_eligible_pairs": len(d["deck"]),
        "n_deck_eligible_seeds": n_deck_seeds,
        "deck_eligible_by_seed": deck_by_seed,
        "n_pairs_failing_backed": sum(1 for p in d["pairs"] if not p["backed"]),
        "n_pairs_failing_slice_distinct": sum(1 for p in d["pairs"] if not p["slice_distinct"]),
        "deck_shrink_verdict": (
            ("NO SHRINK -- %d seeds carry a deck-eligible qualifying pair (>= 6), so D-MW-29's deck is "
             "authorable at its full 6 rows" % n_deck_seeds) if n_deck_seeds >= 6 else
            ("SHRINK -- only %d seeds carry a deck-eligible qualifying pair (< 6), so D-MW-29's 6-row deck "
             "is NOT authorable as written" % n_deck_seeds)),
        "qualifying_by_seed": qual_by_seed,
        "qualifying_by_seed_node": qual_by_node,
    }
    out["self_tests"] = _self_tests(d, inv)
    assert G.rev_cross_link_buckets()["seeds_with_pairs"] == out["summary"]["n_seeds_with_pairs"]
    return out


def _schema_paths(census: dict) -> set:
    """Every key path this check polices: the top level, plus ONE level down inside each top-level dict
    block that `_INVARIANT_BLOCKS` does NOT already byte-diff.

    WHY IT STOPS THERE. The invariant blocks are compared byte for byte, so a key lost inside one of them
    already prints a DIFF; going deeper into them would only re-report data keys (alias names, contract
    ids) as if they were schema. The blocks OUTSIDE that list -- `summary`, `zero_pair_decomposition`,
    `node_keyed_view`, `index_keying`, `self_tests`, ... -- had NO check of any kind, which is how five
    `summary` keys were dropped in the T2-1 rebuild while `--verify-legacy` printed '0 block(s) differ'.
    `self_tests` is deliberately in scope: a renamed check is an unnoticed dropped check."""
    paths = set()
    for k, v in census.items():
        paths.add(k)
        if k in _INVARIANT_BLOCKS or not isinstance(v, dict):
            continue
        for k2 in v:
            paths.add("%s.%s" % (k, k2))
    return paths


def verify_legacy(path: str) -> int:
    """Diff every re-key-invariant block against the committed P6 artifact, THEN assert the schema is a
    SUPERSET of the reference's. Zero diffs + zero dropped keys == this producer is a faithful rebuild of
    the one that wrote it. Added keys are fine and are listed; REMOVED keys are a failure, because the
    artifact is a RECORD and a record that quietly loses a column is worse than one that never had it."""
    ref = json.load(open(path, encoding="utf-8"))
    d = _derive()
    inv = _invariant_blocks(d)
    lit = inv.pop("_literal")
    inv.pop("_node_of")
    inv.pop("_G")
    bad = 0
    for k in _INVARIANT_BLOCKS:
        if k not in ref:
            print("MISSING IN REF: %s" % k)
            bad += 1
            continue
        if json.dumps(inv[k], sort_keys=False) != json.dumps(ref[k], sort_keys=False):
            print("DIFF: %s" % k)
            bad += 1
        else:
            n = len(inv[k]) if isinstance(inv[k], (list, dict)) else 1
            print("OK  : %-32s (%d)" % (k, n))
    want = ref.get("resolution_rule_reading", {}).get("literal_prose_buckets")
    ok = want == {"resolved": lit["resolved"], "unresolvable-no-node": lit["unresolvable-no-node"]}
    print("%s: literal_prose_buckets %s" % ("OK  " if ok else "DIFF", lit))
    bad += 0 if ok else 1

    # ── THE SCHEMA-SUPERSET CHECK (T2-1 review finding, 2026-08-15) ───────────────────────────────────
    old, new = _schema_paths(ref), _schema_paths(build())
    dropped, added = sorted(old - new), sorted(new - old)
    for p in dropped:
        print("DROPPED KEY: %s" % p)
    bad += len(dropped)
    if dropped:
        print("FAIL: %-32s (%d ref paths, %d DROPPED, %d added)"
              % ("schema_superset", len(old), len(dropped), len(added)))
    else:
        print("OK  : %-32s (%d ref paths, 0 dropped, %d added)" % ("schema_superset", len(old), len(added)))
    if added:
        print("      added: %s" % ", ".join(added))
    print("\n%d block(s) differ" % bad)
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="D-MW-27 / T2-1 inversion census")
    ap.add_argument("--out", help="write the census JSON here (relative paths resolve off the repo root)")
    ap.add_argument("--verify-legacy", help="diff the re-key-invariant blocks against a committed census")
    a = ap.parse_args()
    if a.verify_legacy:
        p = a.verify_legacy if os.path.isabs(a.verify_legacy) else os.path.join(ROOT, a.verify_legacy)
        return 1 if verify_legacy(p) else 0
    census = build()
    st = census["self_tests"]
    failed = [k for k, v in st.items() if k != "errors" and v not in (True, "PASS")]
    for k, v in st.items():
        print("  %-58s %s" % (k, v))
    if failed or st["errors"]:
        print("SELF-TESTS FAILED: %s" % (failed or st["errors"]))
        return 1
    if a.out:
        p = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(census, fh, indent=1)
            fh.write("\n")
        print("wrote %s" % p)
    else:
        print(json.dumps(census["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
