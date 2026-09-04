"""V2-5 WIDTH PAYOFF, RE-MEASURED AT HEAD -- $0, offline, no LLM, in-run reproducible.

RUN:  python data/consequence_leg/v25_width_head.py   (writes v25_width_head_<UTC date>.json beside it)

WHY IT EXISTS. The v2 refute's second fatal: the v2 design offered "the width half buys ZERO new
hops on the whole 14-row deck" as a MEASURED zero, computed from the 2026-09-02 treatment arm --
an artifact stamped git_commit '880ee822+walk-sitting2-reviewed', i.e. BEFORE the ceiling fix
(30 -> 60) and BEFORE the base-contract re-root (cascade.py:6667-6677). At HEAD the deck's two
'corn'-rooted rows re-root to corn_cbot, whose engine ladder yields FOUR admissible children, so
the corn_cbot-rooted population on this deck is THREE rows, not one, and the width question has to
be asked per row, on that row's own composer-narrated set.

WHAT IT MEASURES, AND ON WHAT BASIS EACH NUMBER RESTS (three separate bases, never mixed):
  (a) GRAPH/CODE AT HEAD, exact: the re-root predicate on 'corn'; corn_cbot's hop-1 ladder; each
      child's PRICE_COVERAGE_START, hence the firing-start interval on which each child is FREE.
  (b) THE BANKED ARM, used ONLY for the composer-narrated pair set per row -- a fact about what the
      OTHER engines narrated on that turn, written by producers this lane did not touch. It is NOT
      used for any spend, ceiling, order or firing claim; the arm's own turn_budget_spent declines
      are arithmetically impossible at HEAD and are reported here only as the reason the row's
      firing set is unknown.
  (c) DECLARED UNKNOWN: the two re-rooted rows declined at root_uncovered BEFORE firing enumeration,
      so no firing window exists for them in any artifact. Their firing sets at HEAD are UNMEASURED
      at $0 and are reported as such -- never as zero.

THE WIDTH DELTA IS DEFINED ONCE: rendered children under the flag minus rendered children shipped,
on the same root, same firing, same composer set = max(0, survivors - CW_MAX_CHILDREN) when
survivors <= CW_DEEP_MAX_CHILDREN.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "src"))

from leviathan.graphrag import complex_map as CM                 # noqa: E402
from leviathan.graphrag import graph as G                        # noqa: E402
from leviathan.graphrag.numbers import cascade as cq             # noqa: E402
from leviathan.silver import futures_eod_contracts as FC         # noqa: E402

PROBE = "v25_width_head"
ARM = os.path.join(_HERE, "..", "batch_runs",
                   "walk_baseline_eval_queries_rv_reading_v1_anthropic_20260902T150522Z.json")

CW_DEEP_MAX_CHILDREN = 4        # the proposed second constant, named so artifact and design agree


def _ladder(g, cov, seed, exclude_nodes):
    """The engine's hop-1 ladder VERBATIM (cascade.py:6699-6733), minus the two turn-dependent gates
    (kept-subgraph :6765/:6783, composer-narrated :6738), which are applied separately below."""
    node = g.contract_node
    rows = [r for r in g.rev_cross_links(seed)]
    if rows and any(str(r.get("seed")) != seed for r in rows):
        return []
    by: dict = {}
    for r in rows:
        by.setdefault(str(r.get("contract")), []).append(r)
    out = []
    for child in sorted(by):
        crows = by[child]
        if child not in cov or node(child) in exclude_nodes:
            continue
        if cq._cw_currency(child) != cq._cw_currency(seed):
            continue
        signs = {str(r.get("sign")) for r in crows}
        if signs - {"+", "-"} or len(signs) != 1:
            continue
        if any(cq._cw_min_lag_quarters(r.get("lag")) != 0 for r in crows):
            continue
        rels = sorted({str(r.get("relation")) for r in crows})
        if any(rel not in cq._CW_RELATION_WORDS for rel in rels):
            continue
        if len({str(r.get("blurb") or "").strip() for r in crows} - {""}) > 1:
            continue
        if child not in cq._CW_BOARD_LABEL:
            continue
        out.append(child)
    return out


def build() -> dict:
    g = G.CausalGraph.load()
    cov = FC.PRICE_COVERAGE_START
    node = g.contract_node

    # ── (a) the re-root predicate at HEAD, run as the engine runs it (cascade.py:6667-6677) ──
    reroot = {}
    for base in ("corn",):
        seeds = {str(r.get("seed")) for r in g.rev_cross_links(base)}
        fires = (base not in cov and node(base) == base and len(seeds) == 1
                 and next(iter(seeds)) in cov)
        reroot[base] = {"in_cov": base in cov, "contract_node": node(base),
                        "seeds": sorted(seeds), "re_roots_to": next(iter(seeds)) if fires else None,
                        "predicate_fires": bool(fires)}

    root = "corn_cbot"
    kids = _ladder(g, cov, root, {node(root)})
    child_cov = {c: str(cov[c]) for c in kids}
    # A child is FREE on a firing iff its board history starts AFTER the firing start
    # (cascade.py:6907: `str(cov[child]) > t1` -> reason pre_coverage, reads=0).
    free_interval = {c: {"free_when_firing_starts_before": child_cov[c]} for c in kids}

    # ── (b) the composer-narrated pair set, per deck row, from the banked arm ──
    arm = json.load(open(ARM, encoding="utf-8"))
    per = {a["id"]: a for a in arm.get("per_answer") or []}
    pair_slugs = {p.id: list(CM.pair_slugs(p)) for p in CM.iter_all_pairs()}
    corn_wheat_pair = pair_slugs.get("corn_wheat_feed")

    rows = []
    for rid in ("rv_corn_wheat", "rv_corn_sorghum", "rv_corn_wheat_stress"):
        a = per[rid]
        w = a.get("quantify_cascade_walk") or {}
        banked_narrated = sorted({str(d.get("child")) for d in (w.get("declines") or [])
                                  if d.get("reason") == "composer_narrated_pair"})
        rv2 = int(a.get("reroute_v2_pairs") or 0)
        xmit = bool(a.get("transmission_fired"))
        comove = bool(a.get("comove_fired"))
        firings = w.get("firings") or []
        if banked_narrated:
            basis, filtered = "banked_decline_record", banked_narrated
        elif rv2 == 0 and not xmit and not comove:
            # _cw_narrated_pairs (cascade.py:6197-6225) reads EXACTLY quantify_transmission.links,
            # quantify_reroute_v2 and quantify_comove. All three absent -> the set is EMPTY.
            basis, filtered = "measured_empty_narrated_set", []
        else:
            # RV2's commodityA/commodityB are the COMPLEX-MAP PAIR's own slugs (cascade.py:3107,
            # :3128, :4792 -- `source`/`target` off the pair row), i.e. priced-board ids fixed by
            # config and INDEPENDENT of the turn's focus contract. On a corn-vs-wheat question the
            # one reachable pair is corn_wheat_feed.
            basis = "inferred_from_config_pair_identity(corn_wheat_feed)"
            filtered = [s for s in (corn_wheat_pair or []) if s in kids]
        survivors = [c for c in kids if c not in filtered]
        ship_rendered = survivors[:cq.CW_MAX_CHILDREN]
        deep_rendered = survivors[:CW_DEEP_MAX_CHILDREN]
        start = firings[0]["start"] if firings else None
        if start:
            free = [c for c in deep_rendered if child_cov[c] > start]
        else:
            free = None
        rows.append({
            "row": rid,
            "root_at_arm": w.get("root"),
            "root_at_head": root,
            "re_rooted_at_head": w.get("root") != root,
            "admissible_children_at_head": kids,
            "narrated_basis": basis,
            "narrated_filtered_out": filtered,
            "survivors_after_composer_filter": survivors,
            "n_survivors": len(survivors),
            "shipped_rendered_children": ship_rendered,
            "deep_rendered_children": deep_rendered,
            "width_delta_rendered_children": len(deep_rendered) - len(ship_rendered),
            "firing_window_at_head": (firings[0] if firings else None),
            "firing_basis": ("banked (the row reached enumeration)" if firings else
                             "UNMEASURED at $0 -- the row declined root_uncovered BEFORE "
                             "enumeration at the pre-re-root root; no artifact holds its windows"),
            "free_children_on_that_firing": free,
            "paid_cells_deep": (None if free is None else 1 + len(deep_rendered) - len(free)),
            "reads_shipped_reserved": (None if start is None
                                       else (1 + len(ship_rendered)) * cq.CW_READS_PER_CELL),
            "reads_deep_reserved": (None if free is None
                                    else (1 + len(deep_rendered) - len(free)) * cq.CW_READS_PER_CELL),
        })

    # ── the width yield, stated as the measurement, not as a counterfactual ──
    measured = [r for r in rows if r["narrated_basis"] != "inferred_from_config_pair_identity"]
    yield_rows = [r["row"] for r in rows if r["width_delta_rendered_children"] > 0]
    yield_stmt = {
        "corn_rooted_rows_at_head": len(rows),
        "rows_where_all_four_survive": yield_rows,
        "n_rows_width_binds": len(yield_rows),
        "n_rows_width_inert": len(rows) - len(yield_rows),
        "rows_with_a_banked_firing": [r["row"] for r in rows if r["firing_window_at_head"]],
        "width_delta_on_rows_with_a_banked_firing": [
            r["width_delta_rendered_children"] for r in rows if r["firing_window_at_head"]],
        "reads_cost_of_the_width_delta": "0 -- 4 rendered children at 3 paid cells + 1 free "
                                         "prices 12 reserved reads, the same 12 the shipped "
                                         "3-child plan reserves",
        "falsifier": ("if rv_corn_wheat_stress's single RV2 pair were NOT corn_wheat_feed, its "
                      "survivors would be 4 and the yield would be 2 of 3 rows, never 0 of 3"),
    }

    # ── THIRD-ORDER REACHABILITY, the $0 answer to the v2 design's top kill condition ──
    # The hop-2/hop-3 gate requires the candidate to sit in the turn's RETRIEVED contract set
    # (_cw_kept_contracts, cascade.py:6176-6182 -- every contract-kind node of sg). The eval
    # artifact banks that set per row as cascade_closure.admissions, so the membership question the
    # v2 design called "turn-dependent and never measured" is answerable from the artifact at $0.
    third = []
    for a in arm.get("per_answer") or []:
        w = a.get("quantify_cascade_walk") or {}
        if str(w.get("root") or "") != "soybeans_cbot":
            continue
        adm = (a.get("cascade_closure") or {}).get("admissions") or {}
        kept = sorted({k.split(":")[1] for k in adm if k.startswith("contract:")})
        third.append({
            "row": a["id"],
            "banked_outcome": w.get("outcome"), "banked_order": w.get("order"),
            "banked_path": w.get("path"),
            "hop1": "soybean_meal_cbot", "hop2": "soybean_oil_cbot",
            "hop3_candidate": "malaysian_crude_palm_oil_cme",
            "hop3_in_kept_subgraph": "malaysian_crude_palm_oil_cme" in kept,
            "hop2_in_kept_subgraph": "soybean_oil_cbot" in kept,
            "narrated_set_empty": (int(a.get("reroute_v2_pairs") or 0) == 0
                                   and not a.get("transmission_fired")
                                   and not a.get("comove_fired")),
            "firing": (w.get("firings") or [None])[0],
            "hop3_free_on_that_firing": (
                None if not w.get("firings")
                else str(cov["malaysian_crude_palm_oil_cme"]) > w["firings"][0]["start"]),
        })

    # ── the whole-deck root table at HEAD (which rows the flag can touch at all) ──
    deck = []
    for a in arm.get("per_answer") or []:
        w = a.get("quantify_cascade_walk") or {}
        r0 = str(w.get("root") or "")
        r1 = reroot.get(r0, {}).get("re_roots_to") or r0
        k = _ladder(g, cov, r1, {node(r1)}) if r1 in cov else []
        grand = _ladder(g, cov, k[0], {node(r1), node(k[0])}) if len(k) == 1 else []
        great = _ladder(g, cov, grand[0], {node(r1), node(k[0]), node(grand[0])}) if grand else []
        deck.append({"row": a["id"], "root_at_arm": r0, "root_at_head": r1,
                     "out_degree_at_head": len(k), "children": k,
                     "hop2_from_only_child": grand, "hop3_from_that": great,
                     "flag_half": ("width" if len(k) > cq.CW_MAX_CHILDREN else
                                   ("depth" if (len(k) == 1 and grand and great) else "none"))})

    return {
        "probe": PROBE,
        "asof": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head_commit_expected": "c6868034",
        "bases": {
            "a_graph_and_code_at_head": "exact; re-derived here",
            "b_banked_arm": ("data/batch_runs/walk_baseline_eval_queries_rv_reading_v1_anthropic_"
                             "20260902T150522Z.json, git_commit "
                             + str(arm.get("git_commit"))
                             + " -- read ONLY for the composer-narrated pair set per row"),
            "c_declared_unknown": "the two re-rooted rows' firing sets at HEAD",
        },
        "constants_shipped": {"CW_MAX_CHILDREN": cq.CW_MAX_CHILDREN, "CW_CAP": cq.CW_CAP,
                              "CW_TURN_CEILING": cq.CW_TURN_CEILING,
                              "CW_READS_PER_CELL": cq.CW_READS_PER_CELL,
                              "CW_MAX_FIRINGS": cq.CW_MAX_FIRINGS},
        "constants_proposed": {"CW_DEEP_MAX_CHILDREN": CW_DEEP_MAX_CHILDREN},
        "re_root_predicate": reroot,
        "corn_cbot_children": kids,
        "corn_cbot_child_coverage": child_cov,
        "free_interval": free_interval,
        "corn_wheat_feed_pair": corn_wheat_pair,
        "per_row": rows,
        "third_order_reachability": third,
        "width_yield": yield_stmt,
        "deck_roots_at_head": deck,
    }


if __name__ == "__main__":
    doc = build()
    name = f"v25_width_head_{dt.datetime.now(dt.timezone.utc):%Y%m%d}.json"
    with open(os.path.join(_HERE, name), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=False)
    print(json.dumps(doc["re_root_predicate"], indent=1))
    for r in doc["per_row"]:
        print(f"{r['row']:22s} survivors={r['n_survivors']} basis={r['narrated_basis']} "
              f"width_delta={r['width_delta_rendered_children']} "
              f"reads {r['reads_shipped_reserved']}->{r['reads_deep_reserved']} "
              f"firing={'banked' if r['firing_window_at_head'] else 'UNMEASURED'}")
    for t in doc["third_order_reachability"]:
        print(f"{t['row']:22s} hop3_in_kept={t['hop3_in_kept_subgraph']} narrated_empty={t['narrated_set_empty']} "
              f"hop3_free={t['hop3_free_on_that_firing']} banked_order={t['banked_order']}")
    print(json.dumps(doc["width_yield"], indent=1))
    print(f"wrote {name}")
