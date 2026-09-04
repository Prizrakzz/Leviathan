"""V2-5 v4 RE-MEASUREMENT -- what the adjudicated LAWS change, measured at $0, offline.

FOUR QUESTIONS THE v4 LAWS FORCED, NONE OF WHICH v3 ANSWERED:

 (1) M1 -- the free set is ONE aggregation over ALL legs (children, grand, great). v3's set was
     hop-1 only, which made its own grand/great tests vacuous. Re-measure the ALL-LEGS free set on
     the shipped ladder and state paid_cells on EVERY shape.
 (2) THE SHARED DEEP REGIME -- CW_DEEP_MAX_CHILDREN 5 (v3 had 4, "tracking the graph"). 5 carries
     one slot of margin because V2-3's cross-currency rider LIFTS children onto the same seam. So:
     how many children does each root gain when the cross_currency gate at cascade.py:6707 stops
     declining? That is the number that says whether 5 is margin or a future CI red.
 (3) THE CEILING -- CW_DEEP_TURN_CEILING 80. Recompute the config-driven pre-walk terms AT HEAD and
     state the FX allowance that keeps 80 safe, with the enumerated-worst case named honestly.
 (4) THE ORDER-LABEL EQUIVALENCE -- v3 claimed "MEASURED TRUE 14/14". Re-read the banked replay and
     split it into RENDERED shapes (the discriminating population) and empty rows (trivially equal).

$0: no model calls, no AWS, no network. Re-runnable:
    python data/consequence_leg/v25_v4_remeasure.py
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "src"))

from leviathan.graphrag import graph as G                        # noqa: E402
from leviathan.graphrag import params as _pr                     # noqa: E402
from leviathan.graphrag.numbers import cascade as cq             # noqa: E402
from leviathan.silver import futures_eod_contracts as FC         # noqa: E402

PROBE = "v25_v4_remeasure"
LADDER = os.path.join(_HERE, "v25_ladder_20260903_palm.json")

# THE v4 REGIME (LAW, superseding v3's 4 / 15): one shared flag-gated deep regime on the UNION of
# GRAPHRAG_CASCADE_DEEP and GRAPHRAG_CASCADE_XCCY.
CW_DEEP_MAX_CHILDREN = 5
CW_DEEP_CAP = 24            # = (1 root + 5 children + 1 grand + 1 great) * CW_READS_PER_CELL 3
CW_DEEP_MAX_ORDER = 3
CW_DEEP_TURN_CEILING = 80


def _ladder(g, cov, node, seed, exclude_nodes, *, lift_currency=False):
    """The engine's hop-1 ladder VERBATIM (cascade.py:6699-6733), minus the two TURN-dependent gates
    (kept-subgraph, composer-narrated), which are declared not applied. `lift_currency` simulates
    V2-3: the cross_currency decline at :6707 stops firing and those children become admissible."""
    rows = [r for r in g.rev_cross_links(seed)]
    if rows and any(str(r.get("seed")) != seed for r in rows):
        return [], [], {"focus_not_node_seed": 1}
    by: dict = {}
    for r in rows:
        by.setdefault(str(r.get("contract")), []).append(r)
    same, xccy, decl = [], [], {}
    for child in sorted(by):
        crows = by[child]

        def d(reason):
            decl[reason] = decl.get(reason, 0) + 1

        if child not in cov:
            d("child_uncovered"); continue
        if node(child) in exclude_nodes:
            d("node_cycle"); continue
        _is_x = cq._cw_currency(child) != cq._cw_currency(seed)
        if _is_x and not lift_currency:
            d("cross_currency"); continue
        signs = {str(r.get("sign")) for r in crows}
        if signs - {"+", "-"}:
            d("sign_undeclared" if signs <= {"0", "None", ""} else "sign_not_unanimous"); continue
        if len(signs) != 1:
            d("sign_not_unanimous"); continue
        if any(cq._cw_min_lag_quarters(r.get("lag")) != 0 for r in crows):
            d("lag_gate"); continue
        rels = sorted({str(r.get("relation")) for r in crows})
        if any(rel not in cq._CW_RELATION_WORDS for rel in rels):
            d("relation_unmapped"); continue
        blurbs = sorted({str(r.get("blurb") or "").strip() for r in crows} - {""})
        if len(blurbs) > 1:
            d("blurb_not_unanimous"); continue
        if child not in cq._CW_BOARD_LABEL:
            d("child_uncovered"); continue
        (xccy if _is_x else same).append(child)
    return same, xccy, decl


def build() -> dict:
    g = G.CausalGraph.load()
    cov = FC.PRICE_COVERAGE_START
    node = g.contract_node
    roots = sorted(s for s in cov if s in cq._CW_BOARD_LABEL)

    # ── (2) THE V2-3 WIDTH HEADROOM ───────────────────────────────────────────────────────────
    width: dict = {}
    for root in roots:
        same, xccy, decl = _ladder(g, cov, node, root, {node(root)})
        same2, xccy2, _ = _ladder(g, cov, node, root, {node(root)}, lift_currency=True)
        if not (same or xccy2):
            continue
        width[root] = {"same_currency_children": same, "n_same": len(same),
                       "xccy_children_if_v23_lifts": sorted(set(same2 + xccy2) - set(same)),
                       "n_if_v23_lifts": len(same2) + len(xccy2),
                       "cross_currency_declines_today": decl.get("cross_currency", 0)}
    max_same = max((v["n_same"] for v in width.values()), default=0)
    max_lift = max((v["n_if_v23_lifts"] for v in width.values()), default=0)
    over5 = sorted(r for r, v in width.items() if v["n_if_v23_lifts"] > CW_DEEP_MAX_CHILDREN)

    # ── (1) THE ALL-LEGS FREE SET AND paid_cells ON EVERY SHAPE ───────────────────────────────
    # _cw_free(cov, slug, firing) == str(cov[slug]) > str(firing["start"]) -- cascade.py:6907.
    def free(slug, start):
        return str(cov[slug]) > str(start)

    lad = json.load(open(LADDER, encoding="utf-8"))
    shapes: list = []
    for root, e in sorted((lad.get("ladder") or {}).items()):
        kids = e["children"]
        # SHAPE 1 BREADTH: >1 admissible child (or a grandchild exists) -> ONE firing.
        # SHAPE 2 DEPTH-IN-GRAPH: exactly one child WITH a qualifying grandchild -> ONE firing,
        #         ladder to CW_DEEP_MAX_ORDER.
        # SHAPE 3 DEPTH-IN-TIME: exactly one child, no grandchild -> CW_MAX_FIRINGS firings.
        gmap = e.get("grand") or {}
        chain = None
        if len(kids) == 1:
            c = kids[0]
            gk = gmap.get(c) or []
            if gk:
                gg = (e.get("great") or {}).get("%s>%s" % (c, gk[0])) or []
                chain = [c, gk[0]] + ([gg[0]] if gg else [])
        # the free/paid split is a function of the FIRING START, so it is swept, not asserted.
        legs = (chain if chain else kids)
        floors = sorted({str(cov[s]) for s in legs})
        # the sweep carries the THREE measured deck/window starts beside the structural probes:
        # rv_beans_oil's banked firing (2015-06-01, which predates palm's 2016-08-01 floor) and the
        # two deep windows G0b prices palm over (2019-12-01, 2023-10-01).
        probes = sorted(set(["2010-01-01", "2015-06-01", "2019-12-01", "2023-10-01",
                             "2026-01-01"] + floors))
        rows = []
        for st in probes:
            fset = {s for s in legs if free(s, st)}
            if chain:
                # transitive: a leg any of whose ANCESTORS on its own path is free is removed
                drop, seen_free = set(), False
                for s in chain:
                    if seen_free:
                        drop.add(s)
                    if s in fset:
                        seen_free = True
                paid = 1 + sum(1 for s in chain if s not in fset and s not in drop)
                cells = 1 + sum(1 for s in chain if s not in drop)
                nfir = 1
            elif len(kids) > 1:
                paid = 1 + sum(1 for s in kids[:CW_DEEP_MAX_CHILDREN] if s not in fset)
                cells = 1 + len(kids[:CW_DEEP_MAX_CHILDREN])
                drop, nfir = set(), 1
            else:
                nfir = 2                                    # depth-in-time, CW_MAX_FIRINGS
                paid = nfir * (1 + sum(1 for s in kids if s not in fset))
                cells = nfir * (1 + len(kids))
                drop = set()
            rows.append({"firing_start": st, "free": sorted(fset), "transitively_dropped":
                         sorted(drop), "rendered_cells": cells, "paid_cells": paid,
                         "paid_reads": paid * cq.CW_READS_PER_CELL,
                         "fits_deep_cap": paid * cq.CW_READS_PER_CELL <= CW_DEEP_CAP})
        shapes.append({"root": root,
                       "shape": ("depth_in_graph" if chain else
                                 "breadth" if len(kids) > 1 else "depth_in_time"),
                       "legs": legs, "chain": chain, "n_children": len(kids),
                       "firings": (1 if (chain or len(kids) > 1) else 2),
                       "coverage_floors": {s: str(cov[s]) for s in legs},
                       "sweep": rows})
    worst_reads = max((r["paid_reads"] for s in shapes for r in s["sweep"]), default=0)
    all_fit = all(r["fits_deep_cap"] for s in shapes for r in s["sweep"])

    # THE MAXIMAL LEGITIMATE SHAPE the cap is sized on (the union of both branches, deliberately
    # over-provisioned so no future shape-rule change can make the cap bind).
    maximal = {"root": 1, "children": CW_DEEP_MAX_CHILDREN, "grand": 1, "great": 1}
    maximal["cells"] = sum(maximal.values())
    maximal["reads"] = maximal["cells"] * cq.CW_READS_PER_CELL
    maximal["equals_cw_deep_cap"] = maximal["reads"] == CW_DEEP_CAP

    # ── (3) THE CEILING, RECOMPUTED AT HEAD ───────────────────────────────────────────────────
    terms = {"CASCADE_CAP": int(_pr.get("serving.cascade.cap", 12)),
             "CHAIN_CAP": int(_pr.get("serving.cascade.chain.cap", 12)),
             "TRANSMISSION_CAP": int(_pr.get("serving.cascade.transmission.cap", 18)),
             "price_leg": 2,
             "j4": 3 * 3,                                   # EPISODE_OUTCOME_MAX_WINDOWS x reads=3
             "xc_fork_calls_delta": 12}
    prewalk_enumerated = sum(terms.values())
    measured_turns = [13, 14, 19, 25, 25]
    ceiling = {"terms": terms, "prewalk_enumerated_worst": prewalk_enumerated,
               "prewalk_measured_turns": measured_turns,
               "prewalk_measured_worst": max(measured_turns),
               "cw_deep_cap": CW_DEEP_CAP, "cw_context_cap": cq.CW_CONTEXT_CAP,
               "round3_prewalk_allowance": 44,
               "fx_allowance": CW_DEEP_TURN_CEILING - (44 + CW_DEEP_CAP + cq.CW_CONTEXT_CAP),
               "derivation": "80 = 44 (round-3 pre-walk allowance) + 24 (CW_DEEP_CAP) + 2 "
                             "(CW_CONTEXT_CAP) + 10 (V2-3 FX allowance)",
               "headroom_over_measured_worst":
                   CW_DEEP_TURN_CEILING - (max(measured_turns) + CW_DEEP_CAP + cq.CW_CONTEXT_CAP),
               "binds_under_enumerated_worst":
                   prewalk_enumerated + CW_DEEP_CAP + cq.CW_CONTEXT_CAP > CW_DEEP_TURN_CEILING,
               "enumerated_worst_total": prewalk_enumerated + CW_DEEP_CAP + cq.CW_CONTEXT_CAP,
               "max_non_root_cells_on_maximal_shape": CW_DEEP_MAX_CHILDREN + 2}

    # ── (4) THE ORDER-LABEL EQUIVALENCE, SPLIT BY DISCRIMINATING POWER ────────────────────────
    ol = lad.get("order_label") or {}
    rows_ol = ol.get("rows") or []
    rendered, empty = [], []
    for i, r in enumerate(rows_ol):
        rp = r.get("rendered_pairs")
        tag = {"i": i, "root": r.get("root"), "children_declared": r.get("children_declared"),
               "order_n_edges": r.get("order_n_edges"), "banked_order": r.get("banked_order"),
               "shipped_expr": r.get("shipped_expr"), "depth_minus_one": r.get("depth_minus_one")}
        (empty if not rp else rendered).append(tag)
    order_label = {"banked_all_agree": ol.get("all_agree"), "n_rows": len(rows_ol),
                   "n_rendered_shapes": len(rendered), "rendered_rows": rendered,
                   "n_empty_rendered_pairs": len(empty), "empty_rows": empty,
                   "note": ("an empty rendered_pairs makes BOTH expressions return 'first' "
                            "trivially -- those rows carry no discriminating power")}

    return {
        "probe": PROBE, "graph_version": getattr(g, "version", None),
        "basis": "HEAD c6868034; working tree modifies answer.py + config_check.py ONLY",
        "regime_v4": {"CW_DEEP_MAX_CHILDREN": CW_DEEP_MAX_CHILDREN, "CW_DEEP_CAP": CW_DEEP_CAP,
                      "CW_DEEP_MAX_ORDER": CW_DEEP_MAX_ORDER,
                      "CW_DEEP_TURN_CEILING": CW_DEEP_TURN_CEILING,
                      "CW_READS_PER_CELL": cq.CW_READS_PER_CELL,
                      "CW_MAX_FIRINGS": cq.CW_MAX_FIRINGS},
        "v23_width_headroom": {"per_root": width, "max_same_currency_out_degree": max_same,
                               "max_out_degree_if_v23_lifts_currency": max_lift,
                               "roots_over_cw_deep_max_children": over5,
                               "cw_deep_max_children": CW_DEEP_MAX_CHILDREN},
        "free_set_all_legs": {"rule": "a leg is FREE iff str(cov[slug]) > str(firing['start']) on "
                                      "EVERY selected firing; ONE set over children+grand+great",
                              "shapes": shapes, "worst_paid_reads": worst_reads,
                              "every_swept_shape_fits_cw_deep_cap": all_fit,
                              "maximal_legitimate_shape": maximal},
        "ceiling": ceiling,
        "order_label": order_label,
    }


if __name__ == "__main__":
    out = os.path.join(_HERE, "v25_v4_remeasure_20260903.json")
    doc = build()
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=False)
    print("wrote", out)
    print(json.dumps({k: v for k, v in doc.items()
                      if k in ("regime_v4", "ceiling", "order_label")}, indent=1)[:4000])
    print("max same-ccy out-degree:", doc["v23_width_headroom"]["max_same_currency_out_degree"],
          "| if V2-3 lifts:", doc["v23_width_headroom"]["max_out_degree_if_v23_lifts_currency"],
          "| roots over 5:", doc["v23_width_headroom"]["roots_over_cw_deep_max_children"])
    print("worst paid reads over all swept shapes:",
          doc["free_set_all_legs"]["worst_paid_reads"],
          "| all fit cap:", doc["free_set_all_legs"]["every_swept_shape_fits_cw_deep_cap"])
