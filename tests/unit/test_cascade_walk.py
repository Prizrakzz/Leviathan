"""CASCADE EPISODE WALK -- sitting-1 pins (charter STEPS 1-3 + A2/A3 counters).

Scope: the graph accessor, the pure `sign_agreement` verdict, and the read-counter contracts the
turn ceiling will sum. The leg proper (resolvers, path selection, budget, render, the ceiling
itself) lands in sitting 2 and grows its groups HERE. Hermetic except the two real-graph pins
(the accessor is a one-line read off the loaded index; loading it is the pin).

The counter DOCTRINE these pins hold (charter A2/A3, K7's own wording):
  * a count is READ at the site that paid it, never inferred from a reason->cost map;
  * a PRE-fetch decline says `net_reads: 0` -- zero paid, said so;
  * a POST-fetch decline carries what was actually paid;
  * an UNMEASURABLE spend leaves the key ABSENT -- absent is never zero (the ceiling declines);
  * none of the counter edits changes a rendered byte (K10(ii) -- the six engine suites that pin
    rendered lines all pass unchanged beside this file).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import stats as st

ASOF = "2026-07-31"


# ── STEP 1: the public seed enumerator ──────────────────────────────────────────────────────────────
def test_rev_cross_link_seeds_is_the_sorted_private_index():
    from leviathan.graphrag import graph as G
    g = G.CausalGraph.load()
    seeds = g.rev_cross_link_seeds()
    assert seeds == sorted(g._rev_index)
    assert seeds == sorted(seeds)                                  # sorted -> deterministic
    assert len(seeds) == g.rev_cross_link_buckets()["seeds_with_pairs"] == 23


# ── STEP 3: sign_agreement -- pure, three-valued, a WORD never a number ─────────────────────────────
def test_sign_agreement_aligned_and_at_odds_on_the_measured_hop():
    # The K0 fence artifact's own numbers (natural_gas firing): corn +4.4618 / HRW +29.2614 on a
    # declared '+' hop -> aligned -- and the verdict is SYMMETRIC under traversal order (K3's
    # both-orders clause), because sign() of both legs is what it reads, never which leg is which.
    assert st.sign_agreement(4.4618, 29.2614, "+")["value"] == "aligned"
    assert st.sign_agreement(29.2614, 4.4618, "+")["value"] == "aligned"
    # cattle_on_feed firing: corn +1.5722 / soymeal -3.961 on '+' -> at_odds, both orders.
    assert st.sign_agreement(1.5722, -3.961, "+")["value"] == "at_odds"
    assert st.sign_agreement(-3.961, 1.5722, "+")["value"] == "at_odds"
    # a '-' edge inverts the expectation, not the moves.
    assert st.sign_agreement(2.0, -3.0, "-")["value"] == "aligned"
    assert st.sign_agreement(2.0, 3.0, "-")["value"] == "at_odds"


def test_sign_agreement_undetermined_is_the_protective_default():
    # sign '0' / None / junk -> the edge declines to declare; a zero move on either leg -> no sign
    # to compare; a non-numeric move -> never a raise, never a guess. All 'undetermined' (K4).
    for bad_sign in ("0", None, "", "up"):
        assert st.sign_agreement(1.0, 2.0, bad_sign)["value"] == "undetermined"
    assert st.sign_agreement(0.0, 2.0, "+")["value"] == "undetermined"
    assert st.sign_agreement(2.0, 0.0, "+")["value"] == "undetermined"
    assert st.sign_agreement("n/a", 2.0, "+")["value"] == "undetermined"
    assert st.sign_agreement(None, 2.0, "+")["value"] == "undetermined"


def test_sign_agreement_contract_shape_and_governance():
    out = st.sign_agreement(1.0, 2.0, "+")
    assert out == {"stat": "sign_agreement", "declined": False, "value": "aligned"}
    assert isinstance(out["value"], str)                           # a WORD -- no copy surface can
    #                                                                mistake the verdict for a magnitude
    assert "sign_agreement" not in st.STAT_REGISTRY                # engine calculator, NOT the agent enum
    assert not st.is_banned_name("sign_agreement")


# ── STEP 2 / A2: the base-wave counter (the largest producer, previously invisible) ─────────────────
def test_wave_counter_stamped_zero_on_the_all_dark_early_return():
    sg = SimpleNamespace(nodes=[], trace={}, fired_regimes=[])
    block, trace, rtrace = cq.quantify(sg, None, qfn=lambda s: [], asof=ASOF, near=None,
                                       extra_number_calls=[])
    assert block is None and trace == [] and rtrace == []
    # stamped BEFORE the early return, zero included -- the quantify_dark_refs discipline verbatim:
    # absent means "never quantified", 0 means "quantified and the wave ran nothing".
    assert sg.trace["quantify_wave_reads"] == 0


def test_wave_counter_records_the_real_spec_count(monkeypatch):
    row = {"table": "silver_cot", "metric": "mm_net", "agg": "latest", "period_type": "date",
           "leg_mode": "current", "country_rule": "none", "native_unit": "contracts",
           "narrate_unit": "contracts", "scale": 1}
    monkeypatch.setattr(cq, "load_map", lambda: {"cot_mm_positioning": row})
    node = SimpleNamespace(contract="corn_cbot", id="managed_money_positioning",
                           prior={"silver_ref": "cot_mm_positioning", "region": "US"},
                           evidence=[{"date": "2012-06-01", "source": "usda_gain",
                                      "source_key": "k1", "text": "t"},
                                     {"date": "2012-08-01", "source": "usda_gain",
                                      "source_key": "k2", "text": "t"}])
    sg = SimpleNamespace(nodes=[node], trace={}, fired_regimes=[])
    calls: list = []

    def qfn(sql):                                                  # the cot-context suite's qfn shape
        s = (sql or "").lower()
        if "desc" in s and "limit 1" in s:
            return [{"value": "118432", "report_date": "2026-07-28"}]
        return [{"value": str(111232 + 2400 * i), "report_date": f"2026-07-{7 + 7 * i:02d}"}
                for i in range(4)]

    block, _tr, _rt = cq.quantify(sg, None, qfn=qfn, asof=ASOF, near="2012",
                                  extra_number_calls=calls, pace=False)
    assert block is not None                                       # the wave really ran
    assert sg.trace["quantify_wave_reads"] == 1                    # one current-leg spec == one read


# ── STEP 2 / A2: the transmission stamp helper -- absent is never zero ──────────────────────────────
def test_xmit_stamp_reads_counts_distinct_memo_round_trips():
    mq = cq._xmit_memo_qfn(lambda sql: [])
    mq("SELECT a")
    mq("SELECT a")                                                 # memo hit -- NOT a second round-trip
    mq("SELECT b")
    d = cq._xmit_stamp_reads({"reason": "x"}, mq)
    assert d["net_reads"] == 2


def test_xmit_stamp_reads_none_mqfn_leaves_the_key_absent():
    # The default-backend path (`_xmit_memo_qfn(None)` passes through): the spend is unmeasurable,
    # so the key stays ABSENT -- the ceiling reads that as UNKNOWN and declines the walk, which is
    # the fail-closed direction. A raise here would have converted a fired chain into an error
    # decline (the K10 behavior change this helper exists to prevent).
    d = {"reason": "x"}
    assert cq._xmit_stamp_reads(d, None) is d
    assert "net_reads" not in d


# ── STEP 2: the J4/J6 per-entry `reads` law -- minted 0, set at the paying site ─────────────────────
def test_j4_and_j6_entry_reads_are_minted_zero_and_only_grow():
    # Source-level pin (the entries are minted inside serving loops whose fixtures live in the
    # engine suites): every entry literal that opens with the mint carries "reads": 0, and the only
    # assignments are the literal paid counts at the read sites -- never a reason->cost map.
    import inspect
    src = inspect.getsource(cq._episode_outcome_legs)
    assert '"reads": 0' in src and 'entry["reads"] = 2' in src and 'entry["reads"] = 3' in src
    src6 = inspect.getsource(cq._cot_outcome_legs)
    assert src6.count('"reads": 0') == 2 and 'entry["reads"] = 1' in src6
    for body in (src, src6):
        assert "reason_cost" not in body and "COST_BY_REASON" not in body


# ══ SITTING 2 -- THE LEG PROPER (charter STEPS 4-8 under A1-A6 + both refute adjudications) ═════════
#
# Hermetic (the test_outcomes_serving_legs convention): the tape arrives through an injected
# qfn(sql) -> rows; the graph is a shaped stub over REAL slugs (coverage, currency and board labels
# are the real registers -- the "probe the REAL row shape first" law); the driver-id -> slice join
# runs the REAL shipped resolver ('heat' is a live slice), never a stub of it.
import datetime as _dt

ASOF_W = "2026-07-31"
ROOT, CHILD, GRAND = "corn_cbot", "soft_red_winter_wheat_cbot", "soybean_meal_cbot"
W_START, W_END, W_SPAN = "2021-03-05", "2021-06-25", "2021-03..2021-06"

_LIFE_W = {"2021-05": ("2021-02-15", "2021-05-10"),
           "2021-07": ("2021-02-15", "2021-07-12"),   # nearest expiry surviving t2+5 -> SELECTED
           "2021-09": ("2021-02-15", "2021-08-15"),
           "2021-12": ("2021-02-15", "2021-08-15")}


def _w_tape_rows(px0=500.0, px1=575.0, life=None):
    d, end = _dt.date.fromisoformat("2021-02-15"), _dt.date.fromisoformat("2021-08-15")
    out = []
    while d <= end:
        iso = d.isoformat()
        for cm, (first, last) in (life or _LIFE_W).items():
            if not (first <= iso <= last):
                continue
            settle = (px0 if iso <= W_START else px1) if cm == "2021-07" else 400.0
            out.append({"value": settle, "knowledge_date": iso, "contract_month": cm,
                        "unit": "US cents/bushel", "currency": "USD",
                        "settle_kind": "settlement"})
        d += _dt.timedelta(days=1)
    return out


class _WTape:
    """A slug-aware qfn: serves `rows_by_slug[slug]` for whichever board the SQL names, records
    every SQL handed to it (the read-count assertions read `len(self.sql)`)."""

    def __init__(self, rows_by_slug):
        self.rows_by_slug = rows_by_slug
        self.sql: list[str] = []

    def __call__(self, sql):
        self.sql.append(sql)
        for slug, rows in self.rows_by_slug.items():
            if slug in (sql or ""):
                return list(rows)
        return []


def _w_edge(seed=ROOT, contract=CHILD, relation="competes_with", sign="+",
            lag="0-1 quarters", blurb="one board's demand spills into the other"):
    return {"seed": seed, "contract": contract, "relation": relation, "sign": sign,
            "lag": lag, "blurb": blurb, "mechanism": "m"}


def _w_graph(edges, drivers=("heat",), child_edges=()):
    nodes = {ROOT: "corn", CHILD: "srw_wheat", GRAND: "soymeal", "canola_ice": "canola",
             "campinas_corn_reference_bmf": "corn"}
    by_seed: dict = {}
    for e in list(edges) + list(child_edges):
        by_seed.setdefault(nodes.get(e["seed"], e["seed"]), []).append(e)
    return SimpleNamespace(
        contracts={ROOT: SimpleNamespace(drivers=[SimpleNamespace(id=d) for d in drivers])},
        rev_cross_links=lambda c, _b=by_seed, _n=nodes: [dict(r)
                                                         for r in _b.get(_n.get(c, c), [])],
        contract_node=lambda c, _n=nodes: _n.get(c, c),
    )


def _w_sg(windows=None, node="heat", trace_extra=None, kept=()):
    win = windows if windows is not None else [{"start": W_START, "end": W_END,
                                               "span": W_SPAN, "n": 7}]
    trace = {"episodes_injected": [{"node": node, "line": f"DATED EPISODES for {node} ...",
                                    "spans": [W_SPAN], "windows": win}],
             "quantify_wave_reads": 0}
    trace.update(trace_extra or {})
    return SimpleNamespace(nodes=[SimpleNamespace(id=k, kind="contract") for k in kept],
                           trace=trace, fired_regimes=[])


def _w_run(sg=None, graph=None, qfn=None, calls=None):
    sg = sg if sg is not None else _w_sg()
    graph = graph if graph is not None else _w_graph([_w_edge()])
    qfn = qfn if qfn is not None else _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows()})
    calls = [] if calls is None else calls
    lines, payload = cq._cascade_walk_leg_or_nothing(sg, graph, {"focus_contract": ROOT},
                                                     qfn, ASOF_W, calls)
    return lines, payload, calls, qfn, sg


# ── the fired path: acceptance, rectangle, register ─────────────────────────────────────────────────
def test_walk_fires_first_order_aligned_with_bound_handles():
    lines, payload, calls, qfn, sg = _w_run()
    assert payload["outcome"] == "fired" and payload["order"] == "first"
    assert sg.trace["quantify_cascade_walk"] is payload
    assert payload["firings"] == [{"span": W_SPAN, "slice": "heat", "start": W_START,
                                   "end": W_END, "span_days": 112, "node_token": "heat"}]
    # two ROW-1 cells, both +15 % on the survivor, handles continuing from base
    row1 = [ln for ln in lines if ln.startswith("- [N")]
    assert len(row1) == 2 and len(calls) == 2
    assert "[N1] CBOT corn" in row1[0] and "+15 %" in row1[0] and W_SPAN in row1[0]
    assert "[N2] CBOT srw wheat" in row1[1]
    assert all(c.get("shown") for c in calls)                      # _shown-bound, every minted row
    assert any(ln.startswith("CONSEQUENCE HOP CBOT corn and CBOT srw wheat")
               and "compete for the same demand" in ln and "heat firing window" in ln
               for ln in lines)
    assert any(ln.startswith("CONSEQUENCE READ") and "held" in ln and "in-sample" in ln
               for ln in lines)
    assert lines[-1].startswith("CASCADE EPISODE WALK (first order)")
    # the K2 rectangle, both identities, exact
    assert payload["children_declared"] == 1 == payload["children_priced"]
    assert payload["children_named"] == 0
    assert len(payload["cells"]) == 2
    assert sum(1 for c in payload["cells"] if c["status"] == "closed") == 2
    assert payload["net_reads"] == 4 and all(c["reads"] == 2 for c in payload["cells"])
    assert cq._cw_register_fence(lines)                            # the serve fence passes clean


def test_walk_at_odds_renders_honestly_and_symmetrically():
    inv = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows(px0=575.0, px1=500.0)})
    lines, payload, _c, _q, _s = _w_run(qfn=inv)
    assert payload["outcome"] == "fired"
    assert any("sat at odds with the declared relation" in ln for ln in lines)
    # the reverse traversal (child as root) reads the same verdict -- K3's both-orders clause
    rev_graph = _w_graph([_w_edge(seed=CHILD, contract=ROOT)])
    rev_graph.contracts = {CHILD: SimpleNamespace(drivers=[SimpleNamespace(id="heat")])}
    rev_inv = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows(px0=575.0, px1=500.0)})
    r_lines, r_payload = cq._cascade_walk_leg_or_nothing(_w_sg(), rev_graph,
                                                         {"focus_contract": CHILD}, rev_inv,
                                                         ASOF_W, [])
    assert r_payload["outcome"] == "fired"
    assert any("sat at odds" in ln for ln in r_lines)


def test_fence_failed_pair_verdicts_undetermined_never_a_direction():
    # the child's surviving month is pushed two cycles out -> tenor fence fails -> K4's protective
    # direction: the moves render, the verdict is undetermined, no direction word survives.
    far = {"2021-05": ("2021-02-15", "2021-05-10"),
           "2021-09": ("2021-02-15", "2021-08-15"),
           "2021-12": ("2021-02-15", "2021-08-15")}
    qfn = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows(life=far)})
    lines, payload, _c, _q, _s = _w_run(qfn=qfn)
    assert payload["outcome"] == "fired"
    child_cell = next(c for c in payload["cells"] if c["slug"] == CHILD)
    assert child_cell["tenor_ok"] is False and child_cell["verdict"] == "undetermined"
    assert any("declines to read a direction" in ln for ln in lines)


# ── the pre-read gates: absences in words, zero reads ───────────────────────────────────────────────
@pytest.mark.parametrize("edge, reason", [
    (_w_edge(sign="0"), "sign_undeclared"),
    (_w_edge(contract="canola_ice"), "cross_currency"),           # CAD board vs USD root
    (_w_edge(lag="2-4 quarters"), "lag_gate"),
    (_w_edge(relation="refined_into"), "relation_unmapped"),
    (_w_edge(contract="campinas_corn_reference_bmf"), "node_cycle"),   # same commodity node
])
def test_gated_children_decline_before_any_read(edge, reason):
    lines, payload, calls, qfn, _s = _w_run(graph=_w_graph([edge]))
    assert payload["outcome"] == "declined" and calls == [] and qfn.sql == []
    assert any(d["reason"] == reason for d in payload["declines"])


def test_non_unanimous_parallel_signs_decline_sign_not_unanimous():
    g = _w_graph([_w_edge(sign="+"), _w_edge(sign="-", relation="correlates_with")])
    _l, payload, _c, qfn, _s = _w_run(graph=g)
    assert qfn.sql == []
    assert any(d["reason"] == "sign_not_unanimous" for d in payload["declines"])


def test_root_gates_on_the_real_graph_cost_zero_reads():
    """focus_not_node_seed (french_maize_matif reaches corn's rev rows, every seed is corn_cbot)
    and root_uncovered (palm carries no coverage floor) -- on the LIVE graph, pre-read."""
    from leviathan.graphrag import graph as G
    g = G.CausalGraph.load()
    qfn = _WTape({})
    # the LABEL gate runs first (review D1's own placement), so an unlabeled non-canonical focus
    # declines root_unlabeled...
    _l, p0 = cq._cascade_walk_leg_or_nothing(_w_sg(), g, {"focus_contract": "french_maize_matif"},
                                             qfn, ASOF_W, [])
    assert any(d["reason"] == "root_unlabeled" for d in p0["declines"])
    # ...and with a label supplied, the SEED gate catches the same focus (graph.py files every
    # row of a node under ONE canonical seed -- the 3-covered-non-canonical class).
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setitem(cq._CW_BOARD_LABEL, "french_maize_matif", "MATIF corn")
    try:
        _l, p1 = cq._cascade_walk_leg_or_nothing(_w_sg(), g,
                                                 {"focus_contract": "french_maize_matif"},
                                                 qfn, ASOF_W, [])
    finally:
        mp.undo()
    assert any(d["reason"] == "focus_not_node_seed" for d in p1["declines"])
    _l, p2 = cq._cascade_walk_leg_or_nothing(_w_sg(), g,
                                             {"focus_contract": "malaysian_crude_palm_oil_cme"},
                                             qfn, ASOF_W, [])
    assert any(d["reason"] == "root_uncovered" for d in p2["declines"])
    assert qfn.sql == []


def test_firing_selection_windows_out_of_span_or_coverage_never_fire():
    for win in ([{"start": "2021-03-05", "end": "2021-03-20", "span": "2021-03..2021-03", "n": 3}],
                [{"start": "2020-01-05", "end": "2021-06-25", "span": "2020-01..2021-06", "n": 9}],
                [{"start": "2001-03-05", "end": "2001-06-25", "span": "2001-03..2001-06", "n": 7}],
                []):
        _l, payload, _c, qfn, _s = _w_run(sg=_w_sg(windows=win))
        assert any(d["reason"] == "no_firing_window" for d in payload["declines"]), win
        assert qfn.sql == []


def test_a_non_tree_driver_window_is_not_a_firing():
    _l, payload, _c, qfn, _s = _w_run(sg=_w_sg(node="drought"))   # not in the fixture tree
    assert any(d["reason"] == "no_firing_window" for d in payload["declines"])
    assert payload["grounded_tree_slices"] == [] and qfn.sql == []


# ── the J4 dedup gate (A4 + refute-major-5), all three branches ─────────────────────────────────────
def test_j4_closed_same_board_defers_the_firing_never_double_prices():
    # STEP-12 review D6 (confirmed): the reuse render handed the writer a verdict whose parent
    # magnitude sat in no walk row, and J4's handle cannot ride a non-ROW-1 line under the
    # numeral fence. Adjudicated: a closed J4 hit DEFERS the firing -- counted, handle on the
    # trace, zero reads, no block (K11's no-double-price by construction).
    j4 = [{"node": "corn", "slug": ROOT, "span": W_SPAN, "status": "closed", "move_pct": 15.0,
           "anchor_date": "2021-03-05", "endpoint_date": "2021-06-25",
           "contract_month": "2021-07", "handle": "N9", "reads": 2}]
    sg = _w_sg(trace_extra={"quantify_episode_outcomes": j4})
    lines, payload, calls, qfn, _s = _w_run(sg=sg)
    assert payload["outcome"] == "declined" and lines == [] and calls == []
    root_cell = next(c for c in payload["cells"] if c["slug"] == ROOT)
    assert root_cell["reason"] == "j4_owns_window" and root_cell["j4_handle"] == "N9"
    assert root_cell["reads"] == 0 and payload["net_reads"] == 0 and qfn.sql == []


def test_j4_budget_decline_is_honoured_not_respent():
    j4 = [{"node": "corn", "slug": ROOT, "span": W_SPAN, "status": "declined",
           "reason": cq.EP_DECLINE_BUDGET, "reads": 0}]
    sg = _w_sg(trace_extra={"quantify_episode_outcomes": j4})
    lines, payload, calls, qfn, _s = _w_run(sg=sg)
    root_cell = next(c for c in payload["cells"] if c["slug"] == ROOT)
    assert root_cell["reason"] == "j4_budget_deferred" and root_cell["reads"] == 0
    # zero closed cells -> the marker guard declines the whole block (review minor: no marker
    # claiming rows over a row-less block); the reason stays counted on the trace.
    assert payload["outcome"] == "declined" and lines == []
    assert calls == [] and qfn.sql == []                           # no root -> nothing priced


def test_j4_absent_prices_the_cell():
    _l, payload, calls, _q, _s = _w_run()                          # no J4 trace at all
    assert len(calls) == 2 and payload["net_reads"] == 4


# ── K3: the composer-pair check, both narrating engines ─────────────────────────────────────────────
@pytest.mark.parametrize("extra", [
    {"quantify_transmission": {"links": [{"source": ROOT, "target": CHILD}], "net_reads": 4}},
    {"quantify_reroute_v2": {"commodityA": ROOT, "commodityB": CHILD, "net_reads": 3}},
    {"quantify_comove": {"commodityA": CHILD, "commodityB": ROOT, "comove": True,
                         "net_reads": 3}},
])
def test_a_pair_another_engine_narrates_is_never_walked(extra):
    _l, payload, _c, qfn, _s = _w_run(sg=_w_sg(trace_extra=extra))
    assert any(d["reason"] == "composer_narrated_pair" for d in payload["declines"])
    assert payload["children_named"] >= 1 and qfn.sql == []


# ── K7: the measured ceiling, fail-closed on unknowns ───────────────────────────────────────────────
def test_unmeasured_fired_producer_declines_turn_spend_unknown_at_zero_cost():
    sg = _w_sg(trace_extra={"quantify_reroute_v2": {"commodityA": "x", "commodityB": "y"}})
    _l, payload, _c, qfn, _s = _w_run(sg=sg)
    assert any(d["reason"] == "turn_spend_unknown" for d in payload["declines"])
    assert qfn.sql == [] and payload["net_reads"] == 0


def test_turn_budget_spent_declines_before_any_read():
    sg = _w_sg(trace_extra={"quantify_wave_reads": 57})            # 57 + 6 planned > 60
    _l, payload, _c, qfn, _s = _w_run(sg=sg)
    assert any(d["reason"] == "turn_budget_spent" for d in payload["declines"])
    assert qfn.sql == []


def test_wave_counter_absent_is_unknown_never_zero():
    sg = _w_sg()
    del sg.trace["quantify_wave_reads"]
    _l, payload, _c, qfn, _s = _w_run(sg=sg)
    assert any(d["reason"] == "turn_spend_unknown" for d in payload["declines"])
    assert qfn.sql == []


# ── the register fence: atomic, rolled back, counted ────────────────────────────────────────────────
def test_fence_trip_drops_the_whole_block_and_rolls_back_rows(monkeypatch):
    monkeypatch.setattr(cq, "_cw_marker",
                        lambda order: "CASCADE EPISODE WALK: momentum is accelerating into 2027")
    calls = [{"query": {}, "rows": [], "shown": [1.0]}]            # a pre-existing foreign call
    lines, payload, calls_out, _q, _s = _w_run(calls=calls)
    assert payload["outcome"] == "fenced" and lines == []
    assert len(calls_out) == 1                                     # the walk's rows rolled back
    assert all(c.get("handle") is None for c in payload["cells"])  # no orphan handle claims


def test_every_digit_bearing_line_is_a_row1_template():
    lines, payload, _c, _q, _s = _w_run()
    for ln in lines:
        if any(ch.isdigit() for ch in ln):
            assert ln.startswith("- [N"), ln
        if ln.startswith("- [N"):
            assert len(cq._CW_SPAN_TOKEN_RX.findall(ln)) == 1, ln  # one clock per line


def test_walk_calls_round_trip_from_number_leak_free():
    from leviathan.graphrag import citations as CIT
    from leviathan.graphrag import register as reg
    _l, _p, calls, _q, _s = _w_run()
    for i, call in enumerate(calls, start=1):
        cit = CIT.from_number(call, i)
        label = " ".join(str(getattr(cit, a, "") or "") for a in ("label", "source", "detail"))
        assert reg.internal_leaks(label.replace(cq._TAPE_TABLE, "")) == []


# ── deep-vs-wide (refute-v3 major-3, the deterministic rule) ────────────────────────────────────────
def test_two_children_go_breadth_at_one_firing():
    g = _w_graph([_w_edge(), _w_edge(contract=GRAND, relation="crushed_into")])
    tape = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows(), GRAND: _w_tape_rows()})
    win2 = [{"start": W_START, "end": W_END, "span": W_SPAN, "n": 7},
            {"start": "2020-03-05", "end": "2020-06-25", "span": "2020-03..2020-06", "n": 5}]
    lines, payload, calls, _q, _s = _w_run(graph=g, qfn=tape, sg=_w_sg(windows=win2))
    assert payload["outcome"] == "fired" and len(payload["firings"]) == 1   # breadth -> ONE firing
    assert payload["children_declared"] == 2 == payload["children_priced"]
    assert len(calls) == 3                                         # one root + two children


def test_one_child_with_grandchild_goes_second_order():
    g = _w_graph([_w_edge()],
                 child_edges=[_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")])
    tape = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows(), GRAND: _w_tape_rows()})
    lines, payload, calls, _q, _s = _w_run(graph=g, qfn=tape, sg=_w_sg(kept=(GRAND,)))
    assert payload["outcome"] == "fired" and payload["order"] == "second"
    assert payload["path"] == [ROOT, CHILD, GRAND] and len(calls) == 3
    assert lines[-1].startswith("CASCADE EPISODE WALK (second order)")


def test_one_child_no_grandchild_goes_depth_in_time():
    # the second window wears its OWN month token (one window per visible clock -- a same-token
    # twin would be dropped by the collision rule, which its own pin covers).
    win2 = [{"start": W_START, "end": W_END, "span": W_SPAN, "n": 7},
            {"start": "2021-04-01", "end": "2021-06-20", "span": "2021-04..2021-06", "n": 5}]
    lines, payload, calls, _q, _s = _w_run(sg=_w_sg(windows=win2))
    assert payload["outcome"] == "fired" and len(payload["firings"]) == 2
    assert len(calls) == 4                                         # (root + child) x two firings


# ── the persona license rides the flag, omit-when-off ───────────────────────────────────────────────
def test_persona_license_rides_the_flag(monkeypatch):
    from leviathan.graphrag import answer as ans
    monkeypatch.delenv("GRAPHRAG_CASCADE_WALK", raising=False)
    off = ans._system()
    assert "CONSEQUENCE HOP" not in off                            # flag-off prompt byte-identical
    monkeypatch.setenv("GRAPHRAG_CASCADE_WALK", "on")
    on = ans._system()
    assert ans._SYSTEM_CASCADE_WALK in on
    assert on.replace(ans._SYSTEM_CASCADE_WALK, "") == off         # a pure append, nothing edited


# ── the seam: flag-off byte-identity + the early return ─────────────────────────────────────────────
def test_quantify_without_the_kwarg_is_byte_identical_and_with_it_walks_the_early_return():
    sg0 = SimpleNamespace(nodes=[], trace={}, fired_regimes=[])
    out0 = cq.quantify(sg0, None, qfn=lambda s: [], asof=ASOF_W, near=None,
                       extra_number_calls=[])
    assert out0 == (None, [], []) and "quantify_cascade_walk" not in sg0.trace
    g = _w_graph([_w_edge()])
    sgw = _w_sg()
    calls: list = []
    tape = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows()})
    block, tr, rr = cq.quantify(sgw, g, qfn=tape, asof=ASOF_W, near=None,
                                extra_number_calls=calls,
                                cascade_walk={"focus_contract": ROOT})
    assert block is not None and block.startswith(cq._BLOCK_HEADER)
    assert "CONSEQUENCE HOP" in block and (tr, rr) == ([], [])
    assert sgw.trace["quantify_cascade_walk"]["outcome"] == "fired"
def test_run_xc_fired_dict_gains_net_reads_at_the_seam(monkeypatch):
    # The seam stamps `net_reads` = calls-delta on the FIRED xc trace (the adjudicated proxy). A
    # stub _run_xc that appends two calls and fires must surface net_reads == 2 in the trace key.
    def fake_run_xc(xc_request, sg, graph, groups, qfn, asof, near, calls, **kw):
        calls.append({"query": {}, "rows": []})
        calls.append({"query": {}, "rows": []})
        return ["- [N1] stub line"], {"pair_id": "stub_pair"}
    monkeypatch.setattr(cq, "_run_xc", fake_run_xc)
    sg = SimpleNamespace(nodes=[], trace={}, fired_regimes=[])
    calls: list = []
    # groups empty would early-return; ride the chain kwarg to pass the gate with zero groups.
    monkeypatch.setattr(cq, "_chain_legs", lambda *a, **k: ([], None, None))
    block, _tr, _rt = cq.quantify(sg, None, qfn=lambda s: [], asof=ASOF, near=None,
                                  extra_number_calls=calls, chain=True,
                                  xc_request={"source_slug": "corn_cbot", "trigger": "named"})
    assert sg.trace["quantify_reroute_v2"]["net_reads"] == 2

# -- STEP-12 review adjudications, pinned ------------------------------------------------------------
def test_unlabeled_root_declines_root_unlabeled_at_zero_reads(monkeypatch):
    # review D1 (the reproduced MGEX KeyError class): an unlabeled covered root DECLINES with a
    # named reason before rev_cross_links, never an error payload after paid reads.
    monkeypatch.delitem(cq._CW_BOARD_LABEL, ROOT)
    _l, payload, _c, qfn, _s = _w_run()
    assert any(d["reason"] == "root_unlabeled" for d in payload["declines"])
    assert qfn.sql == [] and payload["net_reads"] == 0


def test_k2_rectangle_holds_on_the_modal_no_firing_decline():
    # review D5 (confirmed): the root-scope declines after child enumeration NAME the children.
    _l, payload, _c, _q, _s = _w_run(sg=_w_sg(windows=[]))
    assert any(d["reason"] == "no_firing_window" for d in payload["declines"])
    assert (payload["children_declared"]
            == payload["children_priced"] + payload["children_named"] == 1)


def test_grandchild_hop_respects_the_composer_pair_check():
    # review D8 (confirmed): the sole live second-order shape IS the fork's own pair.
    g = _w_graph([_w_edge()],
                 child_edges=[_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")])
    sg = _w_sg(kept=(GRAND,),
               trace_extra={"quantify_reroute_v2": {"commodityA": CHILD, "commodityB": GRAND,
                                                    "net_reads": 3}})
    tape = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows(), GRAND: _w_tape_rows()})
    lines, payload, _c, _q, _s = _w_run(graph=g, qfn=tape, sg=sg)
    assert any(d["reason"] == "composer_narrated_pair" and d.get("child") == GRAND
               for d in payload["declines"])
    assert payload["order"] == "first" and GRAND not in payload["path"]


def test_order_and_path_derive_from_the_rendered_hops():
    # review D7 (confirmed): a rendered-but-declined grandchild hop still makes the render
    # second order -- the marker, the trace and the page agree about the depth SHOWN.
    g = _w_graph([_w_edge()],
                 child_edges=[_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")])
    tape = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows(), GRAND: []})   # grandchild dark
    lines, payload, _c, _q, _s = _w_run(graph=g, qfn=tape, sg=_w_sg(kept=(GRAND,)))
    assert payload["outcome"] == "fired"
    assert payload["order"] == "second" and payload["path"] == [ROOT, CHILD, GRAND]
    assert lines[-1].startswith("CASCADE EPISODE WALK (second order)")
    assert any(ln.startswith("CONSEQUENCE ABSENCE CBOT soybean meal") for ln in lines)


def test_a_firing_before_the_childs_own_coverage_costs_zero_reads(monkeypatch):
    # review minor: the child-side pre-coverage decline is ARITHMETIC, never two paid reads.
    import datetime as dtm

    import leviathan.silver.futures_eod_contracts as FC
    monkeypatch.setitem(FC.PRICE_COVERAGE_START, CHILD, dtm.date(2024, 1, 1))
    qfn = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows()})
    lines, payload, _c, _q, _s = _w_run(qfn=qfn)
    child_cell = next(c for c in payload["cells"] if c["slug"] == CHILD)
    assert child_cell["reason"] == "pre_coverage" and child_cell["reads"] == 0
    assert any(ln.startswith("CONSEQUENCE ABSENCE CBOT srw wheat") for ln in lines)
    assert "predates" in "".join(lines)                            # the named prose, not the fallback


def test_two_firings_sharing_one_month_token_keep_only_the_newer():
    # review minor: one window per VISIBLE clock -- two day-grain windows wearing one month span
    # would put two magnitudes for one board under one rendered window.
    win2 = [{"start": W_START, "end": W_END, "span": W_SPAN, "n": 7},
            {"start": "2021-03-08", "end": "2021-06-20", "span": W_SPAN, "n": 4}]
    _l, payload, _c, _q, _s = _w_run(sg=_w_sg(windows=win2))
    assert len(payload["firings"]) == 1


def test_walk_call_keeps_the_machine_slug_in_the_query():
    # review D9 (confirmed): the citations locator -- the chart click-target -- reads
    # query.commodity unresolved, so the call record carries the REAL slug, exactly as J4 does;
    # the reader tag carries display's label through the line's own dict.
    _l, _p, calls, _q, _s = _w_run()
    assert all(c["query"]["commodity"] in (ROOT, CHILD) for c in calls)


def test_row3_carries_the_injected_lines_own_token():
    # review D11 / M4 (confirmed): one window, one spelling -- ROW 3 names the firing with the
    # injected DATED EPISODES line's own node token, verbatim (the fixture id aliases to the
    # 'heat' slice through the REAL resolver, so the two spellings genuinely diverge here).
    sg = _w_sg(node="heat_stress")
    g = _w_graph([_w_edge()], drivers=("heat_stress",))
    lines, payload, _c, _q, _s = _w_run(sg=sg, graph=g)
    assert payload["outcome"] == "fired"
    assert any("the heat_stress firing window" in ln for ln in lines)
    assert not any("the heat firing window" in ln for ln in lines)


def test_ceiling_never_binds_on_the_measured_legitimate_shape():
    # Owner doctrine (quality beats latency; a budget never binds on a legitimate shape): the arm
    # measured pre-walk spend of 25 on live cross-commodity turns, where v3's ceiling of 30 made
    # the walk yield. The ceiling is a runaway tripwire above the measured worst (~44) + CW_CAP.
    assert cq.CW_TURN_CEILING >= 44 + cq.CW_CAP
    sg = _w_sg(trace_extra={"quantify_wave_reads": 25})
    _l, payload, _c, _q, _s = _w_run(sg=sg)
    assert payload["outcome"] == "fired"
    assert not any(d["reason"] == "turn_budget_spent" for d in payload["declines"])


def test_base_contract_focus_reroots_on_the_nodes_priced_seed():
    # Sitting-3 arm finding: the focus-first seed on two corn rows was the BASE contract `corn`
    # (named as its own node, uncovered, a twin of corn_cbot) -> root_uncovered while the sibling
    # phrasing got corn_cbot. The walk now re-roots on the node's canonical priced seed; the
    # alias-collapse class (french_maize_matif: a different board) stays refused by the seed gate.
    from leviathan.graphrag import graph as G
    g = G.CausalGraph.load()
    qfn = _WTape({})
    sg = _w_sg(windows=[])                                         # no firings -> a clean pre-read decline
    _l, p = cq._cascade_walk_leg_or_nothing(sg, g, {"focus_contract": "corn"}, qfn, ASOF_W, [])
    assert p["root"] == "corn_cbot" and p.get("focus_base_contract") == "corn"
    assert not any(d["reason"] == "root_uncovered" for d in p["declines"])
    assert p["children_declared"] >= 1 and qfn.sql == []
    _l, p2 = cq._cascade_walk_leg_or_nothing(_w_sg(windows=[]), g,
                                             {"focus_contract": "french_maize_matif"}, qfn, ASOF_W, [])
    assert p2["root"] == "french_maize_matif"                      # NOT re-rooted: a different board


def test_walk_mandate_ships_only_with_the_flag_and_the_block(monkeypatch):
    # The W4-D3 shape: the MANDATE rides the marker's presence in the volatile prompt AND the flag;
    # the LICENSE rides the flag alone; flag off -> neither, byte-identical.
    from leviathan.graphrag import answer as ans
    monkeypatch.setenv("GRAPHRAG_CASCADE_WALK", "on")
    assert ans._cascade_walk_block_on("") is False
    assert ans._cascade_walk_block_on("... " + cq._cw_marker("first") + " ...") is True
    assert cq._cw_marker("second").startswith(cq.CW_MARKER_PREFIX)   # producer == gate constant
    lic = ans._system()
    both = ans._system(cascade_walk=True)
    assert ans._SYSTEM_CASCADE_WALK in lic and ans._SYSTEM_CASCADE_WALK_MANDATE not in lic
    assert both.replace(ans._SYSTEM_CASCADE_WALK_MANDATE, "") == lic   # a pure append
    monkeypatch.delenv("GRAPHRAG_CASCADE_WALK", raising=False)
    assert ans._cascade_walk_block_on("x " + cq._cw_marker("first")) is False
    off = ans._system(cascade_walk=True)
    assert ans._SYSTEM_CASCADE_WALK not in off and ans._SYSTEM_CASCADE_WALK_MANDATE not in off
