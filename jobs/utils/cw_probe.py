"""CASCADE EPISODE WALK -- K0, the blocking probe (v4 charter, sitting 0). $0 LLM.

THE CHARTER: docs/private/CASCADE_WALK_V4_CHARTER.md adjudicating the v3 design
(data/batch_runs/cascade_walk_design_v3_20260901.json). K0 has four halves plus the census
re-bank the round-3 refuter demanded (major-6: the banked census is stale on a shipping hop
post the arabica re-key -- it must be RE-RUN, never corrected in prose).

RUN MODES.
  LOCAL (halves 0/a/b/d -- census re-bank, episode half, admission half, trigger-overlap half):
      python jobs/utils/cw_probe.py --local --asof 2026-09-01
    Needs AWS creds for the S3 timeline artifact (set EVIDENCE_S3); never touches pg.
  IN-VPC (half c -- the fence dry replay; the dda_probe/rv_regional_probe bootstrap precedent,
  the laptop cannot reach the RDS):
      python jobs/utils/cw_probe.py --fence --asof 2026-09-01
    Needs EVIDENCE_PG_DSN (the evidence jobdef secret). ~120-200 pg reads, all bounded.

THRESHOLDS, PRE-REGISTERED BEFORE THE PROBE RUNS (v3 K0 + v4 amendments + refute major-7).
  (a) EPISODE HALF: >= 8 of the 18 census root NODES carry >= 2 post-coverage MIN_PROPS>=2
      windows on the live timeline artifact [v3's registered bar], AND -- re-registered over the
      SHIPPING denominator per refute major-7 (the 18 are nodes; 7 carry no fully-admissible hop
      and can never render) -- >= 5 of the 11 shipping parent CONTRACTS carry >= 2. One-firing
      parents are REPORTED beside (Q3 adjudication: one firing renders, labeled), never counted
      as passing the >=2 bar.
  (b) ADMISSION HALF, A1-REWRITTEN: >= 40% of the consequence-shaped frozen deck's turns
      (eval_queries_cascade_downstream_v2.yaml -- the instrument authored FOR that shape) carry
      a focus that is a shipping parent with >= 1 declared+covered child. Under A1 the union
      (kept-membership OR reverse-declaration) admits off the graph's own declarations, so the
      fire precondition IS focus-membership; v3's kept-half is not locally measurable and is no
      longer the admission gate (K1 measures live fire >= 60% in the arm).
  (c) FENCE HALF: >= 8 of the 15 shipping first-order hops survive BOTH fences on >= 1 of the
      <= 2 most recent post-coverage firings, priced through the J4 read shape VERBATIM
      (_tape_read -> _episode_candidates -> _tape_read -> _tape_frame -> span_outcome, with the
      lazy PENDING edge re-ask). Realized-interval fence: |d_anchor| + |d_endpoint| <=
      min(7 days, 10% of span). Tenor fence: contract_month_used same-or-adjacent calendar month.
      BASIS AMENDED MID-SITTING ON THE PROBE'S OWN MEASUREMENT (2026-09-01): the registered basis
      (the ROOT NODE's own post-coverage windows) measured EMPTY on 18 of 18 roots -- dense
      commodity slices cluster into one GAP_DAYS=90 mega-blob (corn: 1991-11-12..2026-09-01,
      n=2306; span 12,712d >> EPISODE_SPAN_MAX_DAYS=1460), everything else is pre-coverage.
      The viable substrate (cw_substrate_census_20260901.json): 1,193 sharp modern corroborated
      windows on 135 DRIVER slices. The fence half therefore prices each hop's two boards over
      the ROOT TREE'S DRIVER windows (strict id join: d.id / 'drivers/'+d.id), <= 2 most recent
      whose start clears BOTH boards' coverage. The THRESHOLD IS UNCHANGED; the basis shift is
      itself a K0 finding (charter amendment A6, owner decision).
  (d) TRIGGER-OVERLAP HALF (A3's K0 fourth half), REPORT-ONLY: the consequence-shaped decks'
      cross-market row share -- the structural overlap with the XC detector's population (the
      turns where RV2/comove can fire and, pre-A3, spend unmeasured reads). No kill bar: A3
      lands the RV2/comove net_reads counters in SITTING 1 regardless; the LIVE overlap number
      rides the sitting-3 arm as a K7 sub-measurement.
BELOW (a), (b) or (c): the leg is NOT built and the finding is the deliverable.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, "src")

ASOF_DEFAULT = "2026-09-01"
HISTORICAL_FLOOR_BEFORE = dt.date(2024, 1, 1)     # the census gate, verbatim
CW_MAX_FIRINGS = 2                                # the walk's depth-in-time bound (v3 STEP 6)
RI_TOL_DAYS = 7                                   # realized-interval fence absolute half
RI_TOL_FRAC = 0.10                                # realized-interval fence relative half
TENOR_ADJ_MONTHS = 1                              # tenor fence: same or adjacent month
LAG_RX = re.compile(r"^(\d+)-(\d+)\s+quarters?$")

REGISTERED = {
    "a_nodes": ">= 8 of 18 census root nodes carry >= 2 post-coverage MIN_PROPS>=2 windows",
    "a_parents": ">= 5 of the 11 shipping parent contracts carry >= 2 (refute major-7 denominator)",
    "b_admission": ">= 40% of cascade_downstream_v2 turns have focus in the shipping-parent set",
    "c_fence": ">= 8 of 15 hops survive realized-interval AND tenor on >= 1 recent firing",
    "d_overlap": "REPORT-ONLY -- structural trigger overlap; A3 counters land in sitting 1 regardless",
}


def _min_lag_q(lag):
    m = LAG_RX.match(str(lag or "").strip())
    return int(m.group(1)) if m else None


def _mkey(ym):
    s = str(ym or "")[:7]
    try:
        return int(s[:4]) * 12 + int(s[5:7])
    except (ValueError, IndexError):
        return None


def _days(iso):
    return dt.date.fromisoformat(str(iso)[:10]).toordinal()


def _graph_bits():
    from leviathan.graphrag import graph as G
    from leviathan.silver import futures_eod_contracts as FC
    g = G.CausalGraph.load()
    cov = FC.PRICE_COVERAGE_START
    cmap = FC.CONTRACT_MAP
    return g, cov, cmap


def _first_order(g, cov, cmap):
    """The census's shipping set, derived inline off the same gates -- half 0 asserts this equals
    reach_census_v2.build()'s own list, so drift between the two derivations is caught locally
    before the fence half ever runs on it."""
    node = g.contract_node
    cur = lambda s: (cmap.get(s) or {}).get("currency")            # noqa: E731

    def hops(nd):
        return [r for r in g.rev_cross_links(nd)
                if r["seed"] in cov and r["contract"] in cov]

    roots = [k for k in sorted(g._rev_index) if hops(k)]
    rows = [r for k in roots for r in hops(k)]

    def adm(a, b, r):
        return (node(a) != node(b) and cur(a) == cur(b)
                and cov[a] < HISTORICAL_FLOOR_BEFORE and cov[b] < HISTORICAL_FLOOR_BEFORE
                and _min_lag_q(r["lag"]) == 0 and r["sign"] in ("+", "-"))

    fo = sorted({(r["seed"], r["contract"], r["relation"], r["sign"], str(r["lag"]))
                 for r in rows if adm(r["seed"], r["contract"], r)})
    return roots, rows, fo


def _windows_for(node, asof, max_n=None):
    """The serve-real injected windows: episodes_for at SERVING DEFAULTS (MIN_PROPS floor,
    MAX_PER_NODE=4 biggest-first -- refute F1: the injector has NO span cap and NO recency
    preference, so the probe must not invent one here). Pass a large max_n only for ladders."""
    from leviathan.graphrag import timeline as TL
    os.environ["GRAPHRAG_TIMELINE"] = "on"
    kw = {"with_meta": True}
    if max_n is not None:
        kw["max_n"] = max_n
    eps, meta = TL.episodes_for(node, asof, **kw)
    return list(eps), meta


def half_census(out, emit, asof):
    """(0) The census re-bank (refute major-6). Writes a NEW dated-postrekey artifact -- the banked
    reach_census_v2_20260901.json keeps its bytes (the round-3 verification cites its numbers)."""
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "..", "data", "consequence_leg", "reach_census_v2.py")
    spec = importlib.util.spec_from_file_location("reach_census_v2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = mod.build()
    dst = os.path.join(here, "..", "..", "data", "consequence_leg",
                       f"reach_census_v2_{asof.replace('-', '')}_postrekey.json")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=2)
    g, cov, cmap = _graph_bits()
    _, _, fo = _first_order(g, cov, cmap)
    census_fo = [tuple(x) for x in res["fully_admissible_first_order"]]
    emit("census", {
        "artifact": os.path.relpath(dst, os.path.join(here, "..", "..")),
        "graph_version": res["graph_version"],
        "counts": res["counts"],
        "counts_unchanged_vs_banked": res["counts"] == {
            "admissible_hop_edge_rows": 70, "directed_measurable_pairs": 67,
            "measurement_distinct_triples": 185, "node_distinct_triples": 182,
            "fully_admissible_first_order_hops": 15, "fully_admissible_second_order_triples": 8},
        "signs_on_admissible_rows": res["signs_on_admissible_rows"],
        "reciprocal_rows": len(res["reciprocal_sign_disagreements"]),
        "inline_first_order_reconciles": sorted(census_fo) == list(fo),
    })
    return res


def half_episode(out, emit, asof):
    """(a) The episode half: post-coverage corroborated windows per root, serve-real cap."""
    from leviathan.graphrag import timeline as TL
    g, cov, cmap = _graph_bits()
    roots, rows, fo = _first_order(g, cov, cmap)
    parents = sorted({a for (a, b, *_rest) in fo})

    def count(node_key, cov_start):
        wins, meta = _windows_for(node_key, asof)
        post = [w for w in wins if str(w["start"]) >= cov_start]
        ladder, _ = _windows_for(node_key, asof, max_n=99)
        return {
            "artifact_has_key": (TL._load().get(node_key) is not None),
            "n_injected": len(wins), "n_suppressed": meta.get("n_suppressed"),
            "n_post_coverage": len(post),
            "n_post_coverage_uncapped": sum(1 for w in ladder if str(w["start"]) >= cov_start),
            "windows": [{"start": w["start"], "end": w["end"], "n": w["n"]} for w in post],
        }

    per_node = {}
    for nd in roots:
        seed = next(r["seed"] for r in g.rev_cross_links(nd) if r["seed"] in cov)
        per_node[nd] = count(nd, str(cov[seed]))
    per_parent = {}
    for a in parents:
        per_parent[a] = count(g.contract_node(a), str(cov[a]))

    nodes_ge2 = sorted(k for k, v in per_node.items() if v["n_post_coverage"] >= 2)
    parents_ge2 = sorted(k for k, v in per_parent.items() if v["n_post_coverage"] >= 2)
    parents_eq1 = sorted(k for k, v in per_parent.items() if v["n_post_coverage"] == 1)
    status = TL.load_status()                                      # AFTER the reads (refute minor 4:
    #                                                                r1 stamped 'unread' pre-load)
    emit("episode", {
        "timeline_status": {k: status.get(k) for k in ("state", "source", "n_nodes")},
        "per_node": per_node, "per_parent": per_parent,
        "nodes_ge2": nodes_ge2, "n_nodes_ge2": len(nodes_ge2),
        "parents_ge2": parents_ge2, "n_parents_ge2": len(parents_ge2),
        "parents_one_firing_reported": parents_eq1,
        "PASS_a_nodes": len(nodes_ge2) >= 8,
        "PASS_a_parents": len(parents_ge2) >= 5,
    })


def half_admission(out, emit):
    """(b) The admission half under A1: focus-membership on the consequence-shaped deck."""
    import yaml
    g, cov, cmap = _graph_bits()
    _, _, fo = _first_order(g, cov, cmap)
    parents = {a for (a, b, *_rest) in fo}
    here = os.path.dirname(os.path.abspath(__file__))

    def deck(name):
        p = os.path.join(here, "..", "..", "configs", "graphrag", name)
        rows = (yaml.safe_load(open(p, encoding="utf-8")) or {}).get("queries") or []
        hits = [r["id"] for r in rows if str(r.get("contract") or "") in parents]
        return {"rows": len(rows), "focus_in_parent_set": len(hits), "hit_ids": hits,
                "share": round(len(hits) / len(rows), 3) if rows else None}

    primary = deck("eval_queries_cascade_downstream_v2.yaml")
    secondary = deck("eval_queries_rv_reading_v1.yaml")
    emit("admission", {
        "shipping_parents": sorted(parents),
        "cascade_downstream_v2": primary,
        "rv_reading_v1_secondary": secondary,
        "PASS_b": (primary["share"] or 0.0) >= 0.40,
    })


def half_xc(out, emit):
    """(d) Trigger-overlap, REPORT-ONLY: the consequence-shaped decks are cross-market by
    authorship -- structurally the XC detector's own population. The consequence recorded here is
    that A3's sitting-1 counters are REQUIRED (an uncounted RV2/comove firing on these turns
    would decline the walk `turn_spend_unknown` on its own trigger set); the LIVE fire-overlap
    number is a sitting-3 arm K7 sub-measurement, not a local guess."""
    import yaml
    here = os.path.dirname(os.path.abspath(__file__))

    def census(name):
        p = os.path.join(here, "..", "..", "configs", "graphrag", name)
        rows = (yaml.safe_load(open(p, encoding="utf-8")) or {}).get("queries") or []
        cats = collections.Counter(str(r.get("category") or "") for r in rows)
        cross = sum(n for c, n in cats.items() if c.startswith(("xmc", "rv_")))
        return {"rows": len(rows), "cross_market_rows": cross, "categories": dict(cats)}

    emit("xc_overlap", {
        "cascade_downstream_v2": census("eval_queries_cascade_downstream_v2.yaml"),
        "rv_reading_v1": census("eval_queries_rv_reading_v1.yaml"),
        "structural_note": "cross-market consequence asks ARE the XC detector's population "
                           "(owner-ratified n=6, 13-14/14 measured recall); A3 counters are "
                           "REQUIRED in sitting 1; live fire-overlap rides the arm (K7).",
    })


def _price_cell(qfn, slug, t1, t2, asof):
    """ONE cell, the J4 pricing sequence verbatim (cascade.py _episode_outcome_legs body):
    dry run -> curve read -> candidates -> deep read -> saturation decline -> frame ->
    span_outcome -> lazy edge re-ask on PENDING. Returns (record, n_reads)."""
    from leviathan.graphrag.numbers import cascade as C
    from leviathan.graphrag.numbers import outcomes as OC
    span_days = _days(t2) - _days(t1)
    if span_days > C.EPISODE_SPAN_MAX_DAYS:
        return {"status": "declined", "reason": C.EP_DECLINE_SPAN_TOO_LONG}, 0
    empty = C._tape_frame("", [])
    dry = OC.span_outcome(empty, slug=slug, span_start=t1, span_end=t2, asof=asof,
                          event_key="cw_probe", tape_edge=None)
    if str(dry.get("status") or "") == OC.STATUS_PENDING:
        return {"status": "pending", "reason": "horizon_open"}, 0
    dr = dry.get("decline_reason")
    if dr and dr != OC.DECLINE_NO_ANCHOR_SESSION:
        return {"status": "declined", "reason": dr}, 0
    lo = C._iso_shift(t1, -OC.OUTCOME_LOOKBACK_DAYS)
    hi = C._iso_shift(t2, OC.SURVIVE_DAYS + OC.OUTCOME_LOOKBACK_DAYS)
    curve, sat_a = C._tape_read(qfn, slug=slug, t1=lo, t2=t1, asof=asof)
    months = C._episode_candidates(curve, t2)
    deep, sat_b = C._tape_read(qfn, slug=slug, t1=lo, t2=hi, asof=asof,
                               contract_months=months or None)
    n = 2
    if sat_a or sat_b:
        return {"status": "declined", "reason": C.EP_DECLINE_READ_TRUNCATED}, n
    tape = C._tape_frame(slug, curve, deep)
    if not len(tape):
        return {"status": "declined", "reason": C.EP_DECLINE_NO_TAPE}, n
    res = OC.span_outcome(tape, slug=slug, span_start=t1, span_end=t2, asof=asof,
                          event_key="cw_probe")
    if str(res.get("status") or "") == OC.STATUS_PENDING:
        edge_rows, sat_c = C._tape_read(qfn, slug=slug, t1=t2, t2=hi, asof=asof)
        n += 1
        ef = C._tape_frame(slug, edge_rows)
        edge = (OC.tape_edges(ef) or {}).get(str(slug)) if len(ef) else None
        if edge is not None and not sat_c:
            res = OC.span_outcome(tape, slug=slug, span_start=t1, span_end=t2, asof=asof,
                                  event_key="cw_probe", tape_edge=edge)
    st = str(res.get("status") or "")
    if st != OC.STATUS_CLOSED or res.get("move_pct") is None:
        return {"status": ("pending" if st == OC.STATUS_PENDING else "declined"),
                "reason": res.get("decline_reason") or st or "no_move"}, n
    return {"status": "closed", "move_pct": round(float(res["move_pct"]), 4),
            "anchor_date": str(res.get("anchor_date")),
            "endpoint_date": str(res.get("endpoint_date")),
            "contract_month": str(res.get("contract_month_used"))}, n


def _sharp_windows(asof):
    """The viable firing substrate, from the raw artifact with the PIT vis clamp: per node, the
    corroborated (n>=2) windows with span <= EPISODE_SPAN_MAX_DAYS, newest-ending first."""
    from leviathan.graphrag import timeline as TL
    from leviathan.graphrag.numbers import cascade as C
    os.environ["GRAPHRAG_TIMELINE"] = "on"
    art = TL._load()
    asof_d = dt.date.fromisoformat(str(asof)[:10])
    out = {}
    for node, eps in (art or {}).items():
        keep = []
        for ep in eps or []:
            vis = [d for d in ep.get("dates") or []
                   if dt.date.fromisoformat(str(d)[:10]) <= asof_d]
            if len(vis) < 2:
                continue
            start, end = str(vis[0]), str(vis[-1])
            if _days(end) - _days(start) <= C.EPISODE_SPAN_MAX_DAYS:
                keep.append({"start": start, "end": end, "n": len(vis)})
        if keep:
            keep.sort(key=lambda w: w["end"], reverse=True)
            out[node] = keep
    return out


CW_SPAN_MAX_DAYS = 270      # A6.2 (owner-ratified); the r2 run also certifies the 230-270 band (M7)


def half_fence(out, emit, asof):
    """(c) r2 -- THE A6-FAITHFUL BASIS, adjudicating refute wf_e6a93bf1-0d5 F1/F2/F3 + M3/M6/M7.
    r1's pool was drawn from the RAW artifact through a STRICT id join; the shipped walk sees
    neither. Here the windows are exactly what serving would inject and A6 would select:
      * JOIN (F3/M1): tree drivers resolve through the SHIPPED `ev.slice_for_driver` (the same
        function planner calls); unresolvable drivers are skipped (serving cannot inject them);
      * CAP (F1): windows read at the SERVING INJECTION CAP -- episodes_for defaults, the 4
        BIGGEST per slice, no span cap, no recency preference;
      * KEY (M3): the firing is keyed and labelled by the RESOLVED SLICE, deduped by (start, end);
      * FILTER: window start clears BOTH boards' coverage; span <= CW_SPAN_MAX_DAYS=270;
      * SELECTIONS (F2/M6, both PRE-REGISTERED): A = recency-only top-2 (A6.1 as written; the
        registered >= 8-of-15 bar binds on A) and B = (n desc, recency desc) top-2 (M6's candidate
        rank, REPORT-ONLY -- it calibrates CW_SPAN_MIN_DAYS / the rank rule off one measurement).
    The A-union-B window set is priced once per hop; fences verbatim; per-hop incremental emit."""
    assert os.environ.get("EVIDENCE_PG_DSN"), "the fence half needs EVIDENCE_PG_DSN (in-VPC)"
    os.environ.setdefault("GRAPHRAG_NUMBERS_BACKEND", "pg")
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import timeline as TL
    from leviathan.graphrag.numbers import pgnumbers
    qfn = pgnumbers.pg_query
    g, cov, cmap = _graph_bits()
    _, _, fo = _first_order(g, cov, cmap)
    reads_total = 0
    hops_out = []
    for (a, b, rel, sign, lag) in fo:
        floor = str(max(cov[a], cov[b]))
        slices, unresolved = [], 0
        for d in getattr(g.contracts.get(a), "drivers", []) or []:
            s = ev.slice_for_driver(str(d.id))
            if not s:
                unresolved += 1
                continue
            key = f"drivers/{s}"
            if key not in slices:
                slices.append(key)
        pool, seen_w = [], set()
        for sk in slices:
            wins, _m = _windows_for(sk, asof)                     # SERVING defaults: 4 biggest
            for w in wins:
                t1, t2 = str(w["start"]), str(w["end"])
                span = _days(t2) - _days(t1)
                if t1 >= floor and span <= CW_SPAN_MAX_DAYS and (t1, t2) not in seen_w:
                    seen_w.add((t1, t2))
                    pool.append({"start": t1, "end": t2, "n": int(w["n"]), "span_days": span,
                                 "slice": sk})
        sel_a = sorted(pool, key=lambda w: w["end"], reverse=True)[:CW_MAX_FIRINGS]
        sel_b = sorted(pool, key=lambda w: (w["n"], w["end"]), reverse=True)[:CW_MAX_FIRINGS]
        union = {(w["start"], w["end"]): w for w in (sel_a + sel_b)}
        in_a = {(w["start"], w["end"]) for w in sel_a}
        in_b = {(w["start"], w["end"]) for w in sel_b}
        rec = {"hop": f"{a}->{b}", "relation": rel, "sign": sign,
               "basis": "a6_injected_resolver_joined_r2", "coverage_floor": floor,
               "n_tree_slices": len(slices), "n_unresolved_drivers": unresolved,
               "n_pool_capped": len(pool), "firings": []}
        for wk in sorted(union, key=lambda k: k[1], reverse=True):
            w = union[wk]
            t1, t2, span_days = w["start"], w["end"], w["span_days"]
            ca, na = _price_cell(qfn, a, t1, t2, asof)
            cb, nb = _price_cell(qfn, b, t1, t2, asof)
            reads_total += na + nb
            f = {"window": f"{t1}..{t2}", "span_days": span_days, "n_props": w["n"],
                 "slice": w["slice"],
                 "selections": [s for s, mem in (("A", in_a), ("B", in_b)) if wk in mem],
                 "root_cell": ca, "child_cell": cb, "reads": na + nb}
            if ca["status"] == "closed" and cb["status"] == "closed":
                d_anchor = abs(_days(ca["anchor_date"]) - _days(cb["anchor_date"]))
                d_end = abs(_days(ca["endpoint_date"]) - _days(cb["endpoint_date"]))
                tol = min(RI_TOL_DAYS, RI_TOL_FRAC * span_days)
                f["ri"] = {"d_anchor": d_anchor, "d_endpoint": d_end, "tol": round(tol, 1),
                           "pass": (d_anchor + d_end) <= tol}
                ma, mb = _mkey(ca["contract_month"]), _mkey(cb["contract_month"])
                f["tenor"] = {"months": [ca["contract_month"], cb["contract_month"]],
                              "pass": (ma is not None and mb is not None
                                       and abs(ma - mb) <= TENOR_ADJ_MONTHS)}
                sa = (ca["move_pct"] > 0) - (ca["move_pct"] < 0)
                sb = (cb["move_pct"] > 0) - (cb["move_pct"] < 0)
                es = 1 if sign == "+" else -1
                f["sign_agree_preview"] = ("aligned" if sa and sb and sb == sa * es else
                                           "at_odds" if sa and sb else "undetermined")
            rec["firings"].append(f)

        def _ok(f):
            return (f.get("ri") or {}).get("pass") and (f.get("tenor") or {}).get("pass")

        rec["survives_a"] = any(_ok(f) for f in rec["firings"] if "A" in f["selections"])
        rec["survives_b"] = any(_ok(f) for f in rec["firings"] if "B" in f["selections"])
        emit(f"fence:{a}->{b}", rec)
        hops_out.append(rec)
    surv_a = sorted(r["hop"] for r in hops_out if r["survives_a"])
    surv_b = sorted(r["hop"] for r in hops_out if r["survives_b"])
    summary = {"hops": len(hops_out),
               "survivors_a": surv_a, "n_survivors_a": len(surv_a),
               "survivors_b": surv_b, "n_survivors_b": len(surv_b),
               "reads_total": reads_total,
               "PASS_c": len(surv_a) >= 8,                        # the registered bar binds on A
               "timeline_status_after_read": {k: TL.load_status().get(k)
                                              for k in ("state", "n_nodes")}}
    emit("fence_summary", summary)
    out["halves"]["fence_hops"] = hops_out
    # bank to EVIDENCE_S3 (the rv_regional_probe precedent); r2 keeps r1's artifact intact --
    # the refute cites r1 by name and a rescinded verdict must stay readable.
    base = os.environ.get("EVIDENCE_S3", "")
    if base.startswith("s3://"):
        import boto3
        bucket, _, prefix = base[5:].partition("/")
        key = f"{prefix.rstrip('/')}/probes/cw_probe_fence_r2_{asof}.json"
        boto3.client("s3").put_object(Bucket=bucket, Key=key,
                                      Body=json.dumps(out, indent=1, default=str).encode())
        print(f"[cw_probe] banked s3://{bucket}/{key}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default=ASOF_DEFAULT)
    ap.add_argument("--local", action="store_true", help="halves 0/a/b/d (no pg)")
    ap.add_argument("--fence", action="store_true", help="half c (in-VPC, pg)")
    args = ap.parse_args()
    out: dict = {"probe": "cw_probe_k0", "asof": args.asof, "registered": REGISTERED,
                 "halves": {}}

    def emit(name, payload):
        out["halves"][name] = payload
        print(f"[cw_probe] {name}: {json.dumps(payload, default=str)[:1400]}")

    if args.local:
        half_census(out, emit, args.asof)
        half_episode(out, emit, args.asof)
        half_admission(out, emit)
        half_xc(out, emit)
        here = os.path.dirname(os.path.abspath(__file__))
        dst = os.path.join(here, "..", "..", "data", "batch_runs",
                           f"cw_probe_local_{args.asof.replace('-', '')}.json")
        with open(dst, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, default=str)
        print(f"[cw_probe] banked {dst}")
    if args.fence:
        half_fence(out, emit, args.asof)
    if not (args.local or args.fence):
        print("nothing to do: pass --local and/or --fence")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
