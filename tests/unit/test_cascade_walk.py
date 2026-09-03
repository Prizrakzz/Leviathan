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

V2-1 CONTEXT CELL (the rider, built dark 2026-09-02; its group is the LAST section of this file):
  * flag-off BYTE-IDENTITY is the first law (the walk serves live) -- pinned on lines, payload,
    calls, the marker literal and the persona;
  * PRE-ARM GATE (refute M4): KC0b (does a mapped slice WIN position 1 on a covered root) is
    RE-RUN against the artifact that will actually serve any arm before that arm fires -- these
    pins hold the ENGINE on a fixture, never the substrate.
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


def _w_run(sg=None, graph=None, qfn=None, calls=None, request=None):
    sg = sg if sg is not None else _w_sg()
    graph = graph if graph is not None else _w_graph([_w_edge()])
    qfn = qfn if qfn is not None else _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows()})
    calls = [] if calls is None else calls
    # `request` (V2-1 extension, default = the shipped {focus_contract} dict, byte for byte)
    req = request if request is not None else {"focus_contract": ROOT}
    lines, payload = cq._cascade_walk_leg_or_nothing(sg, graph, req, qfn, ASOF_W, calls)
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
    and root_uncovered -- on the LIVE graph, pre-read.

    RE-KEYED (V2-4 walk-side commit, 2026-09-03): the root_uncovered witness WAS the palm slug and
    can no longer be -- palm now carries a coverage floor and a board label, so it clears the root
    ladder. The witness moves to palm_olein_dce, which is the sole seed of its own node (so the
    seed gate passes it, exactly as palm's did) and has no floor because DCE never landed."""
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
    # THE WITNESS'S OWN FUTURE (review m8): palm_olein_dce is uncovered only because DCE has landed
    # no canonical bytes. The day it does and PRICE_COVERAGE_START gains a floor, this decline flips
    # to root_unlabeled (the label gate runs first and no DCE board is in _CW_BOARD_LABEL) -- that is
    # the SAME re-key this comment sits above, not a bug: move the witness to whichever slug is then
    # uncovered, never patch the reason string.
    _l, p2 = cq._cascade_walk_leg_or_nothing(_w_sg(), g,
                                             {"focus_contract": "palm_olein_dce"},
                                             qfn, ASOF_W, [])
    assert any(d["reason"] == "root_uncovered" for d in p2["declines"])
    # ...and the AFFIRMATIVE half of the same re-key: the palm slug now CLEARS every root gate
    # (covered, labeled, its node's own seed) and its declines are the honest CHILD reasons --
    # still at zero reads, because the walk gates children before it reads anything.
    _l, p3 = cq._cascade_walk_leg_or_nothing(_w_sg(), g,
                                             {"focus_contract": "malaysian_crude_palm_oil_cme"},
                                             qfn, ASOF_W, [])
    reasons = {d["reason"] for d in p3["declines"]}
    assert not (reasons & {"root_uncovered", "root_unlabeled", "focus_not_node_seed",
                           "no_declared_children"})
    assert reasons <= {"cross_currency", "child_uncovered", "no_firing_window"}
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


# == V2-1 -- THE CONTEXT CELL RIDER (design v2 + refute, adjudicated 2026-09-02; flag-gated, DARK) ===
#
# The same hermetic idiom: the tape serves the boards, and `_WTape` serves the PINK rows whenever the
# SQL names the card metric ('chicken_usd_t') -- rows shaped {value, knowledge_date, revision_stamp}
# with NO unit key (the measured row shape: v21_context_probe row_units == []). The driver id
# 'poultry_expansion' resolves to the mapped slice 'broiler_economics' through the REAL resolver; the
# window is the KC0b-selected broiler window 2026-01-01..2026-08-12 read at the turn asof 2026-09-02,
# where the card's 40-day lag makes the readable end 2026-07-24 and the prints run January..July.
ASOF_C = "2026-09-02"
C_START, C_END, C_SPAN = "2026-01-01", "2026-08-12", "2026-01..2026-08"
C_PINK = (1750, 1790, 1660, 1750, 1860, 1770, 1730)        # Jan..Jul 2026 -> 1730/1750 - 1 = -1.1429 %
ROW1C = ("- [N3] CONTEXT world chicken monthly cash benchmark price measured on the monthly prints "
         "from January through July inside the episode window 2026-01..2026-08 (per the World Bank "
         "release 2026M08): -1.1429 % [series: world chicken; table: World Bank Pink Sheet]")
ROW2C = ("CONSEQUENCE CONTEXT world chicken: this row is not part of any hop's read and carries no "
         "direction of its own; it is the monthly world cash average the World Bank publishes for "
         "that market, at its current published revision of the months the row names, placed beside "
         "the walk for scope only.")
_PLAIN_MARKER = ("CASCADE EPISODE WALK (first order): the rows above are observed settle changes on "
                 "the same dated firing window, one board per row; each hop's read is stated beside "
                 "it, in-sample on the named window only. Cite the [N] rows verbatim; never derive a "
                 "ratio, a spread, a lag or any magnitude the rows do not print; direction beyond the "
                 "stated read is the analyst's, never the engine's. Do not mint a new episodes-section "
                 "bullet from a consequence row -- the enumeration stays the episodes mandate's, and "
                 "the firing window named here is the same dated window that section enumerates.")


def _c_tape_rows(steps=(C_START,), px=500.0):
    """ONE far delivery month (2026-12) living across every 2025-2026 window these pins use; the settle
    steps +15 % after each date in `steps`, so a window opening on a step closes a +15 % move."""
    d, end = _dt.date.fromisoformat("2025-04-01"), _dt.date.fromisoformat("2026-10-15")
    out = []
    while d <= end:
        iso = d.isoformat()
        settle = px * (1.15 ** sum(1 for s in steps if iso > s))
        out.append({"value": settle, "knowledge_date": iso, "contract_month": "2026-12",
                    "unit": "US cents/bushel", "currency": "USD", "settle_kind": "settlement"})
        d += _dt.timedelta(days=1)
    return out


def _c_pink(values=C_PINK, start_ym=(2026, 1), stamp="2026M08", stamps=None):
    """Pink rows in the MEASURED shape: value + knowledge_date + revision_stamp, NO unit key."""
    y, m = start_ym
    out = []
    for i, v in enumerate(values):
        row = {"value": v, "knowledge_date": f"{y:04d}-{m:02d}-01"}
        s = stamps[i] if stamps is not None else stamp
        if s is not None:
            row["revision_stamp"] = s
        out.append(row)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _c_sg(windows=None, node="poultry_expansion", trace_extra=None):
    win = windows if windows is not None else [{"start": C_START, "end": C_END, "span": C_SPAN,
                                               "n": 20}]
    return _w_sg(windows=win, node=node, trace_extra=trace_extra)


def _c_graph(node="poultry_expansion"):
    return _w_graph([_w_edge()], drivers=(node,))


def _c_tape(pink=None, root=None, child=None):
    return _WTape({ROOT: root if root is not None else _c_tape_rows(),
                   CHILD: child if child is not None else _c_tape_rows(),
                   "chicken_usd_t": pink if pink is not None else _c_pink()})


def _c_run(request=None, sg=None, graph=None, qfn=None, calls=None):
    sg = sg if sg is not None else _c_sg()
    graph = graph if graph is not None else _c_graph()
    qfn = qfn if qfn is not None else _c_tape()
    calls = [] if calls is None else calls
    req = request if request is not None else {"focus_contract": ROOT, "context": True}
    lines, payload = cq._cascade_walk_leg_or_nothing(sg, graph, req, qfn, ASOF_C, calls)
    return lines, payload, calls, qfn, sg


def _c_cell(payload):
    return next(x for x in payload["cells"] if x.get("kind") == "context")


# -- KC5: flag-off byte-identity, the first law ------------------------------------------------------
def test_context_flag_off_is_byte_identical():
    import json
    lines_off, p_off, calls_off, _q, _s = _w_run()
    lines_on, p_on, calls_on, _q2, _s2 = _w_run(request={"focus_contract": ROOT, "context": True})
    assert p_off["outcome"] == "fired" and lines_off == lines_on
    assert set(p_on) - set(p_off) == {"context"}
    assert {k: v for k, v in p_on.items() if k != "context"} == p_off
    blob = json.dumps(p_off, sort_keys=True)
    assert '"kind"' not in blob and '"context"' not in blob            # no kind, no context, anywhere
    assert set(p_off) == {"outcome", "root", "order", "path", "firings", "cells", "declines",
                          "children_declared", "children_priced", "children_named",
                          "grounded_tree_slices", "net_reads", "turn_spent_before"}
    assert json.dumps(calls_off, sort_keys=True) == json.dumps(calls_on, sort_keys=True)
    assert lines_off[-1] == _PLAIN_MARKER
    # the unmapped slice is a COUNTED decline under the rider, at zero reads, and the block is untouched
    assert p_on["context"]["declines"] == [{"slice": "heat", "span": W_SPAN, "reason": "unmapped_slice"}]
    assert p_on["context"]["planned"] == 0 == p_on["context"]["reads"]
    assert p_on["context"]["board_reads_planned"] == 6


def test_marker_plain_bytes_unchanged():
    assert cq._cw_marker("first") == _PLAIN_MARKER
    ctx = cq._cw_marker("first", context=True)
    assert ctx.startswith(cq.CW_MARKER_PREFIX) and "marked CONTEXT" in ctx
    assert "Rows marked CONTEXT" in ctx and "transcribe each with its own handle" in ctx   # review F1
    assert "one series per row" in ctx and "one board per row" not in ctx     # the conditional head
    assert not any(ch.isdigit() for ch in ctx) and cq._cw_register_fence([ctx])
    assert cq.CW_CONTEXT_LINE_RX.search(ctx) is None       # the marker never arms the mandate gate


# -- the rendered pair: handle, months, stamp, ledger ------------------------------------------------
def test_context_cell_renders_the_pair_with_handle_months_and_stamp():
    lines, payload, calls, qfn, sg = _c_run()
    assert payload["outcome"] == "fired" and payload["order"] == "first"
    i = lines.index(ROW1C)
    assert lines[i + 1] == ROW2C                           # the pair is adjacent and atomic
    assert lines[-1] == cq._cw_marker("first", context=True)
    assert cq._cw_register_fence(lines)
    c = calls[-1]
    assert c["shown"] == [-1.1429]
    assert c["query"]["metric"] == "monthly benchmark change"
    assert c["query"]["commodity"] == "world chicken" and c["query"]["period"] == C_SPAN
    assert c["query"]["table"] == "silver_pink_sheet" and c["query"]["asof"] == ASOF_C
    assert c["rows"][0]["revision_stamp"] == "2026M08"
    assert c["rows"][0]["source_metric"] == "chicken_usd_t"
    assert c["rows"][0]["unit"] == "percent change in USD/mt"
    assert c["rows"][0]["knowledge_date"] == "2026-07-01"
    assert payload["context"] == {"planned": 1, "admitted": 1, "rendered": 1, "reads": 1,
                                  "cap": cq.CW_CONTEXT_CAP, "board_reads_planned": 6,
                                  "declines": [], "slices": ["broiler_economics"]}
    cell = _c_cell(payload)
    assert cell["status"] == "closed" and cell["n_obs"] == 7 and cell["handle"] == "N3"
    assert cell["first_date"] == "2026-01-01" and cell["last_date"] == "2026-07-01"
    assert cell["metric"] == "chicken_usd_t" and cell["unit"] == "USD/mt"
    assert cell["revision_stamp"] == "2026M08" and cell["move_pct"] == -1.1429
    assert payload["net_reads"] == 4 + 1 and len(calls) == 3
    assert sum(1 for x in payload["cells"] if "kind" in x) == 1   # board cells carry NO kind key
    assert sg.trace["quantify_cascade_walk"] is payload


def test_context_line_keys_on_the_resolved_slice_never_the_node_token():
    l_a, p_a, _c, _q, _s = _c_run()
    l_b, p_b, _c2, _q2, _s2 = _c_run(sg=_c_sg(node="broiler_margins"),
                                     graph=_c_graph("broiler_margins"))
    assert p_a["outcome"] == p_b["outcome"] == "fired"
    assert ROW1C in l_a and ROW1C in l_b                   # identical ROW-1C bytes on both ids
    assert any("the poultry_expansion firing window" in ln for ln in l_a)
    assert any("the broiler_margins firing window" in ln for ln in l_b)
    assert p_a["firings"][0]["slice"] == p_b["firings"][0]["slice"] == "broiler_economics"


def test_context_read_is_at_the_turn_asof_and_months_are_the_returned_prints():
    lines, payload, _c, qfn, _s = _c_run()
    sql = next(s for s in qfn.sql if "chicken_usd_t" in s)
    # refute m1: the turn asof reaches the SQL ONLY as the lagged guard literal (asof - the card's 40 d)
    assert "'2026-07-24'" in sql and "2026-09-02" not in sql
    assert "'2026-01-01'" in sql and "'2026-08-12'" in sql and "silver_pink_sheet" in sql
    assert sum(1 for s in qfn.sql if "chicken_usd_t" in s) == 1     # ONE read per cell
    l5, p5, _c5, _q5, _s5 = _c_run(qfn=_c_tape(pink=_c_pink(C_PINK[:5])))
    row = next(ln for ln in l5 if cq.CW_CONTEXT_TOKEN in ln)
    assert "from January through May inside the episode window 2026-01..2026-08" in row
    cell = _c_cell(p5)
    assert cell["n_obs"] == 5 and cell["last_month"] == "May" and cell["last_date"] == "2026-05-01"


# -- the counted declines: replay, budget, cap, grain, root, stamp, unit, fence, error ---------------
def test_context_replay_declines_with_zero_reads():
    lines, payload, calls, qfn, _s = _c_run(request={"focus_contract": ROOT, "context": True,
                                                    "replay": True})
    assert payload["outcome"] == "fired" and len(calls) == 2
    assert not any(cq.CW_CONTEXT_TOKEN in ln for ln in lines)
    assert payload["context"]["declines"] == [{"slice": "broiler_economics", "span": C_SPAN,
                                               "reason": "replay"}]
    assert payload["context"]["reads"] == 0 == payload["context"]["admitted"]
    assert not any("chicken_usd_t" in s for s in qfn.sql)
    assert lines[-1] == _PLAIN_MARKER
    assert not any(x.get("kind") == "context" for x in payload["cells"])   # no cell was minted


def test_context_budget_is_subordinate_never_the_block():
    # 2 board cells x 3 = 6 planned reads. At spent = CEILING - 6 the walk fires at EXACTLY the ceiling
    # (its own test keeps its bytes) and the CELL declines budget_cap at zero reads; one read of slack
    # admits it. The rider can never be the reason a walk declines.
    tight = _c_sg(trace_extra={"quantify_wave_reads": cq.CW_TURN_CEILING - 6})
    lines, payload, calls, qfn, _s = _c_run(sg=tight)
    assert payload["outcome"] == "fired" and len(calls) == 2
    assert not any(d["reason"] == "turn_budget_spent" for d in payload["declines"])
    assert payload["context"]["declines"] == [{"slice": "broiler_economics", "span": C_SPAN,
                                               "reason": "budget_cap"}]
    assert payload["context"]["reads"] == 0 and payload["context"]["board_reads_planned"] == 6
    assert payload["turn_spent_before"] == cq.CW_TURN_CEILING - 6
    assert not any("chicken_usd_t" in s for s in qfn.sql) and lines[-1] == _PLAIN_MARKER
    slack = _c_sg(trace_extra={"quantify_wave_reads": cq.CW_TURN_CEILING - 7})
    l2, p2, c2, _q2, _s2 = _c_run(sg=slack)
    assert p2["outcome"] == "fired" and ROW1C in l2 and p2["context"]["rendered"] == 1
    assert p2["turn_spent_before"] == cq.CW_TURN_CEILING - 7 and len(c2) == 3
    # and the walk's OWN ceiling decline (one read over) is a POST-enumeration root decline: the mapped
    # firing WAS planned and is recorded as root_declined (review F2 -- never a false planned=0); the
    # board plan never existed, so board_reads_planned stays None
    over = _c_sg(trace_extra={"quantify_wave_reads": cq.CW_TURN_CEILING - 5})
    l3, p3, c3, q3, _s3 = _c_run(sg=over)
    assert p3["outcome"] == "declined" and any(d["reason"] == "turn_budget_spent"
                                                for d in p3["declines"])
    assert p3["firings"] and p3["firings"][0]["slice"] == "broiler_economics"
    assert p3["context"]["planned"] == 1 and p3["context"]["slices"] == ["broiler_economics"]
    assert p3["context"]["board_reads_planned"] is None
    assert p3["context"]["declines"] == [{"slice": "broiler_economics", "span": C_SPAN,
                                          "reason": "root_declined"}]
    assert p3["context"]["rendered"] == 0 == p3["context"]["reads"] == p3["context"]["admitted"]
    assert q3.sql == [] and c3 == []


def test_context_plan_is_none_before_enumeration_and_stamped_after(monkeypatch):
    # review F2: absent is never zero. A PRE-enumeration root decline (no focus / uncovered root) leaves
    # planned and slices None with no context decline; every POST-enumeration root decline stamps the
    # plan and records each mapped firing as root_declined, so planned == rendered + len(declines).
    _l, p, c, q, _s = _c_run(request={"focus_contract": "", "context": True})
    assert p["outcome"] == "declined" and p["declines"] == [{"scope": "root", "reason": "no_focus"}]
    assert p["context"]["planned"] is None and p["context"]["slices"] is None
    assert p["context"]["declines"] == [] and p["context"]["board_reads_planned"] is None
    _l, p, c, q, _s = _c_run(request={"focus_contract": "not_a_board", "context": True})
    assert any(d["reason"] == "root_uncovered" for d in p["declines"])
    assert p["context"]["planned"] is None and p["context"]["slices"] is None
    assert p["context"]["declines"] == [] and q.sql == [] and c == []
    # a firing enumerated with ZERO mapped slices is a true zero, not an absence
    _l, p_off, _c, _q, _s = _w_run(request={"focus_contract": ROOT, "context": True})
    assert p_off["context"]["planned"] == 0 and p_off["context"]["slices"] == []
    # the unknown-spend decline: enumerated, then lost to K7 -> planned 1, root_declined, zero reads
    unk = _c_sg(trace_extra={"quantify_reroute_v2": {"commodityA": "x", "commodityB": "y"}})
    _l, p2, c2, q2, _s2 = _c_run(sg=unk)
    assert any(d["reason"] == "turn_spend_unknown" for d in p2["declines"])
    assert p2["context"]["planned"] == 1 and p2["context"]["slices"] == ["broiler_economics"]
    assert p2["context"]["declines"] == [{"slice": "broiler_economics", "span": C_SPAN,
                                          "reason": "root_declined"}]
    assert p2["context"]["planned"] == p2["context"]["rendered"] + len(p2["context"]["declines"])
    assert q2.sql == [] and c2 == []
    # the CW_CAP belt (unreachable today; forced by the knob) takes the same path
    monkeypatch.setattr(cq, "CW_CAP", 0)
    _l, p3, c3, q3, _s3 = _c_run()
    assert any(d["reason"] == "cap" for d in p3["declines"])
    assert p3["context"]["planned"] == 1 and p3["context"]["declines"][0]["reason"] == "root_declined"
    assert q3.sql == [] and c3 == []


def test_context_cap_binds_only_the_depth_in_time_shape(monkeypatch):
    # one child, no grandchild -> depth-in-time: two firings, two cells each. Two mapped windows with
    # distinct month tokens -> two context pairs; CW_CONTEXT_CAP = 1 leaves the second as context_cap.
    win2 = [{"start": C_START, "end": C_END, "span": C_SPAN, "n": 20},
            {"start": "2025-06-01", "end": "2025-12-20", "span": "2025-06..2025-12", "n": 9}]
    pink = _c_pink(values=(1500, 1520, 1510, 1530, 1540, 1550, 1560) + C_PINK, start_ym=(2025, 6))
    steps = ("2025-06-01", C_START)
    tape = _c_tape(pink=pink, root=_c_tape_rows(steps), child=_c_tape_rows(steps))
    l, p, calls, _q, _s = _c_run(sg=_c_sg(windows=win2), qfn=tape)
    assert p["outcome"] == "fired" and len(p["firings"]) == 2
    assert p["context"]["rendered"] == 2 == p["context"]["reads"] and len(calls) == 6
    assert sum(1 for ln in l if cq.CW_CONTEXT_TOKEN in ln) == 2
    # review F1 (major): TWO pairs rendered -> the marker tail and the mandate are COUNT-FREE. Neither
    # surface carries a singular count word; 'each' is the only quantifier, and it is per row.
    from leviathan.graphrag import answer as ans
    assert l[-1] == cq._cw_marker("first", context=True) and "Rows marked CONTEXT" in l[-1]
    for surface in (l[-1], ans._SYSTEM_CASCADE_CONTEXT):
        low = surface.lower()
        assert "one row" not in low and "that row" not in low and "ONE ROW" not in surface, surface
    assert "transcribe each with its own handle" in l[-1]
    assert "ROWS MARKED CONTEXT" in ans._SYSTEM_CASCADE_CONTEXT
    assert "transcribe each such row once with its own handle" in ans._SYSTEM_CASCADE_CONTEXT
    assert any("from June through December inside the episode window 2025-06..2025-12" in ln
               for ln in l)
    assert p["net_reads"] == 8 + 2
    monkeypatch.setattr(cq, "CW_CONTEXT_CAP", 1)
    tape1 = _c_tape(pink=pink, root=_c_tape_rows(steps), child=_c_tape_rows(steps))
    l1, p1, c1, _q1, _s1 = _c_run(sg=_c_sg(windows=win2), qfn=tape1)
    assert p1["outcome"] == "fired" and sum(1 for ln in l1 if cq.CW_CONTEXT_TOKEN in ln) == 1
    assert p1["context"]["declines"] == [{"slice": "broiler_economics", "span": "2025-06..2025-12",
                                          "reason": "context_cap"}]
    assert p1["context"]["reads"] == 1 and p1["context"]["cap"] == 1 and len(c1) == 5


def test_context_grain_floor_declines_at_zero_cost_below_min_span():
    # 45 days (passes the walk's own CW_SPAN_MIN_DAYS) but only ONE first-of-month print is readable
    # before the lagged end (2026-07-24) -> grain_thin at ZERO reads, no pink SQL compiled.
    win = [{"start": "2026-06-20", "end": "2026-08-04", "span": "2026-06..2026-08", "n": 4}]
    steps = ("2026-06-20",)
    tape = _c_tape(root=_c_tape_rows(steps), child=_c_tape_rows(steps))
    l, p, calls, qfn, _s = _c_run(sg=_c_sg(windows=win), qfn=tape)
    assert p["outcome"] == "fired" and len(calls) == 2
    assert p["context"]["declines"] == [{"slice": "broiler_economics", "span": "2026-06..2026-08",
                                         "reason": "grain_thin"}]
    assert p["context"]["reads"] == 0 and _c_cell(p)["reads"] == 0
    assert not any("chicken_usd_t" in s for s in qfn.sql)
    assert cq._cw_first_of_months("2026-06-20", "2026-07-24") == ["2026-07-01"]
    assert cq._cw_first_of_months("2026-01-01", "2026-07-24") == [f"2026-{m:02d}-01"
                                                                  for m in range(1, 8)]
    assert cq._cw_first_of_months("2025-11-15", "2026-02-01") == ["2025-12-01", "2026-01-01",
                                                                  "2026-02-01"]
    assert cq._cw_first_of_months("2026-02-01", "2026-04-01") == ["2026-02-01", "2026-03-01",
                                                                  "2026-04-01"]   # 59 d holds three
    assert cq._cw_first_of_months("2026-02-02", "2026-04-01") == ["2026-03-01", "2026-04-01"]


def test_context_grain_floor_post_read_at_two_prints():
    l, p, calls, qfn, _s = _c_run(qfn=_c_tape(pink=_c_pink(C_PINK[:2])))
    assert p["outcome"] == "fired" and len(calls) == 2
    cell = _c_cell(p)
    assert cell["status"] == "declined" and cell["reason"] == "grain_thin"
    assert cell["reads"] == 1 and p["context"]["reads"] == 1        # the paid read is counted
    assert p["net_reads"] == 5 and not any(cq.CW_CONTEXT_TOKEN in ln for ln in l)


def test_context_declined_root_firing_emits_zero_context_lines():
    l, p, calls, qfn, _s = _c_run(qfn=_c_tape(root=[]))
    assert p["outcome"] == "declined" and l == [] and calls == []      # rolled back, as the walk does
    assert p["context"]["declines"] == [{"slice": "broiler_economics", "span": C_SPAN,
                                         "reason": "root_declined"}]
    assert p["context"]["reads"] == 0 == p["context"]["rendered"]
    assert not any(x.get("kind") == "context" for x in p["cells"])
    assert not any("chicken_usd_t" in s for s in qfn.sql)


def test_dormant_guard_kind_filters_context_cells():
    import inspect
    src = inspect.getsource(cq._cascade_walk_legs)
    assert 'if not _cw_board_row_closed(payload["cells"])' in src
    assert 'c.get("kind") != "context"' in inspect.getsource(cq._cw_board_row_closed)
    assert cq._cw_board_row_closed([{"status": "closed", "kind": "context"}]) is False   # declines
    assert cq._cw_board_row_closed([{"status": "closed", "kind": "context"},
                                    {"status": "closed", "slug": ROOT}]) is True
    assert cq._cw_board_row_closed([{"status": "declined", "slug": ROOT}]) is False
    assert cq._cw_board_row_closed([]) is False


def test_context_pair_is_atomic_and_pre_fenced(monkeypatch):
    monkeypatch.setattr(cq, "_cw_context_words",
                        lambda rec: "CONSEQUENCE CONTEXT world chicken: momentum into 2027")
    l, p, calls, _q, _s = _c_run()
    assert p["outcome"] == "fired" and len(calls) == 2              # no context call minted
    assert not any(cq.CW_CONTEXT_TOKEN in ln or ln.startswith("CONSEQUENCE CONTEXT") for ln in l)
    cell = _c_cell(p)
    assert cell["reason"] == "render_fence" and cell["reads"] == 1 and "handle" not in cell
    assert p["context"]["rendered"] == 0
    assert p["context"]["declines"] == [{"slice": "broiler_economics", "span": C_SPAN,
                                         "reason": "render_fence"}]
    assert l[-1] == _PLAIN_MARKER                                     # the PLAIN marker


@pytest.mark.parametrize("pink, reason", [
    (_c_pink(stamp=None), "no_release_stamp"),
    (_c_pink(stamps=["2026M08"] * 6 + [None]), "no_release_stamp"),      # refute m3: PARTIAL = absent
    (_c_pink(stamps=["2026M08"] * 6 + ["2026M07"]), "mixed_release_stamp"),
    (_c_pink(stamp="2026-08"), "stamp_shape"),
])
def test_context_stamp_declines_when_absent_mixed_or_misshapen(pink, reason):
    l, p, calls, _q, _s = _c_run(qfn=_c_tape(pink=pink))
    assert p["outcome"] == "fired" and len(calls) == 2
    cell = _c_cell(p)
    assert cell["reason"] == reason and cell["reads"] == 1
    assert not any(cq.CW_CONTEXT_TOKEN in ln for ln in l) and l[-1] == _PLAIN_MARKER


def test_context_declines_no_unit_and_read_error_off_the_card(monkeypatch):
    # refute m9: the unit is a ROW fact -- an empty unit declines no_unit, never 'percent change in '.
    class _Card:
        publication_lag_days = 40
        metrics: dict = {}
    monkeypatch.setattr(cq, "_registry", lambda: SimpleNamespace(get=lambda t: _Card()))
    l, p, calls, _q, _s = _c_run()
    assert p["outcome"] == "fired" and len(calls) == 2
    cell = _c_cell(p)
    assert cell["reason"] == "no_unit" and cell["reads"] == 1
    assert not any(cq.CW_CONTEXT_TOKEN in ln for ln in l)
    assert not any("percent change in " in (ln or "") for ln in l)

    def _boom():
        raise RuntimeError("registry unreadable")
    monkeypatch.setattr(cq, "_registry", _boom)                     # an unreadable card -> read_error, $0
    l2, p2, c2, q2, _s2 = _c_run()
    assert p2["outcome"] == "fired" and len(c2) == 2
    assert p2["context"]["declines"] == [{"slice": "broiler_economics", "span": C_SPAN,
                                          "reason": "read_error"}]
    assert p2["context"]["reads"] == 0 and not any("chicken_usd_t" in s for s in q2.sql)


def test_context_helper_raise_never_drops_the_walk(monkeypatch):
    # refute M1: the rider's OWN belt -- a raise inside the emission declines the CELL with reason
    # 'error', counts the read that was paid, rolls back its own call, and the walk block ships intact.
    def boom(*a, **k):
        raise RuntimeError("context axes exploded")
    monkeypatch.setattr(cq, "_rv_axes", boom)                       # AFTER the fetch -> read paid
    l, p, calls, qfn, _s = _c_run()
    assert p["outcome"] == "fired" and len(calls) == 2 and len(l) == 5
    assert l[-1] == _PLAIN_MARKER and not any(cq.CW_CONTEXT_TOKEN in ln for ln in l)
    cell = _c_cell(p)
    assert cell["status"] == "declined" and cell["reason"] == "error" and cell["reads"] == 1
    assert "handle" not in cell
    assert p["context"] == {"planned": 1, "admitted": 1, "rendered": 0, "reads": 1,
                            "cap": cq.CW_CONTEXT_CAP, "board_reads_planned": 6,
                            "declines": [{"slice": "broiler_economics", "span": C_SPAN,
                                          "reason": "error"}],
                            "slices": ["broiler_economics"]}
    assert p["net_reads"] == 5 and sum(1 for s in qfn.sql if "chicken_usd_t" in s) == 1
    monkeypatch.setattr(cq, "_cw_first_of_months", boom)            # BEFORE any fetch -> $0
    l2, p2, c2, q2, _s2 = _c_run()
    assert p2["outcome"] == "fired" and len(c2) == 2 and l2[-1] == _PLAIN_MARKER
    cell2 = _c_cell(p2)
    assert cell2["reason"] == "error" and cell2["reads"] == 0
    assert not any("chicken_usd_t" in s for s in q2.sql) and p2["net_reads"] == 4
    monkeypatch.setattr(cq, "_cw_context_call", boom)               # AFTER the pair passed the fence
    l3, p3, c3, _q3, _s3 = _c_run()
    assert p3["outcome"] == "fired" and len(c3) == 2 and l3[-1] == _PLAIN_MARKER
    assert not any(cq.CW_CONTEXT_TOKEN in ln or ln.startswith("CONSEQUENCE CONTEXT") for ln in l3)
    assert _c_cell(p3)["reason"] == "error" and p3["context"]["rendered"] == 0
    assert cq._cw_register_fence(l3)


# -- identity: K2's rectangle, eval's counters, the citation ledger, the fences ----------------------
def test_k2_rectangle_and_eval_counters_ignore_context_cells():
    from leviathan.graphrag import eval as EV
    l, p, calls, _q, _s = _c_run()
    assert p["children_declared"] == p["children_priced"] + p["children_named"] == 1
    out = {"trace": {"quantify_cascade_walk": p}, "citations": [], "structured": None, "answer": ""}
    cs = EV._cascade_stats(out)
    assert cs["cw_cells_declared"] == 2 and cs["cw_cells_measured"] == 2
    assert cs["cw_context_on"] is True and cs["cw_context_rendered"] == 1
    assert cs["cw_context_cells_measured"] == 1
    assert cs["cw_context_planned"] == cs["cw_context_admitted"] == cs["cw_context_reads"] == 1
    assert cs["cw_context_declines"] == [] and cs["cw_context_slices"] == ["broiler_economics"]
    assert cs["cw_child_identity_ok"] is True and cs["cw_reads"] == 5      # cw_reads INCLUDES the rider
    # a walk-less / rider-off row reads the same keys as false/zero -- never KeyError, never None-noise
    cs0 = EV._cascade_stats({"trace": {}, "citations": [], "structured": None, "answer": ""})
    assert cs0["cw_context_on"] is False and cs0["cw_context_rendered"] == 0
    assert cs0["cw_context_declines"] == [] and cs0["cw_context_slices"] == []
    _lo, p_off, _co, _qo, _so = _w_run()
    cs_off = EV._cascade_stats({"trace": {"quantify_cascade_walk": p_off}, "citations": [],
                                "structured": None, "answer": ""})
    assert cs_off["cw_context_on"] is False and cs_off["cw_cells_declared"] == 2


def test_context_call_round_trips_from_number_leak_free_and_unit_present():
    from leviathan.graphrag import citations as CIT
    from leviathan.graphrag import register as reg
    _l, _p, calls, _q, _s = _c_run()
    cit = CIT.from_number(calls[-1], 3)
    assert cit.label == ("World Bank Pink Sheet monthly benchmark change world chicken "
                         "2026-01..2026-08 = -1.1429 percent change in USD/mt "
                         "(latest available 2026-07-01; as-of 2026-09-02)")
    assert reg.internal_leaks(cit.label) == []
    assert cit.unit == "percent change in USD/mt" and cit.value == "-1.1429" and cit.id == "N3"
    assert "2026M08" not in cit.label                       # the stamp's ONE rendering is the LINE
    assert cit.locator["metric"] == "monthly benchmark change"
    assert cit.locator["source_metric"] == "chicken_usd_t"  # refute M5: the drill-down's level series
    assert cit.locator["table"] == "silver_pink_sheet" and cit.locator["commodity"] == "world chicken"
    assert cit.locator["period"] == C_SPAN
    assert CIT.extra_number_citations(calls[-1], 3, [-1.1429]) == []
    # eval's price_cited / unit_present predicates hold on this citation by construction
    assert cit.locator["table"] == "silver_pink_sheet" and cit.value is not None
    assert (cit.unit or "").strip()
    # pre-rider rows are locator-byte-identical: no source_metric key without the row key
    for i, call in enumerate(calls[:-1], start=1):
        assert "source_metric" not in CIT.from_number(call, i).locator


def test_context_line_claim_numbers_fence_and_eval_targets():
    from leviathan.graphrag import eval as EV
    from leviathan.graphrag import verify as vf
    assert vf._claim_numbers_with_decimals(ROW1C) == ([1.1429], [4])   # the move alone
    assert vf._claim_numbers_with_decimals(ROW2C) == ([], [])
    assert cq._cw_register_fence([ROW1C, ROW2C])
    assert len(cq._CW_SPAN_TOKEN_RX.findall(ROW1C)) == 1               # one clock on the line
    assert EV._line_targets(ROW1C, [{"start": "2026-01", "end": "2026-08"},
                                    {"start": "2025-11", "end": "2026-04"}]) == {0}
    rec = {"label": "world beef", "span": "2026-01..2026-08", "revision_stamp": "2026M08",
           "move_pct": 8.284}
    words = cq._cw_context_words(rec)
    for a in cq._CW_MONTHS:
        for b in cq._CW_MONTHS:
            row = cq._cw_context_line(4, dict(rec, first_month=a, last_month=b))
            assert cq._cw_register_fence([row, words]), (a, b)
            assert vf._claim_numbers_with_decimals(row)[0] == [8.284], (a, b)
            assert cq.CW_CONTEXT_LINE_RX.search(row) is not None


# -- the seam: flag, gate on the ROW SHAPE, the positive mandate -------------------------------------
def test_context_mandate_and_gate_ride_the_row_shape_and_both_flags(monkeypatch):
    from leviathan.graphrag import answer as ans
    from leviathan.graphrag import register as reg
    monkeypatch.setenv("GRAPHRAG_CASCADE_WALK", "on")
    monkeypatch.setenv("GRAPHRAG_CASCADE_CONTEXT", "on")
    mk = cq._cw_marker("first", context=True)
    block = "...\n" + ROW1C + "\n" + ROW2C + "\n" + mk          # the shape the producer emits
    assert ans._cascade_context_block_on("x " + mk) is False                    # marker, no row
    assert ans._cascade_context_block_on("[1] CONTEXT AND BACKGROUND\n"
                                         "[2] CONTEXT and outlook") is False    # refute M2
    assert ans._cascade_context_block_on("prefix " + cq.CW_CONTEXT_TOKEN + " bare") is False
    # review F3: the ROW SHAPE ALONE never arms -- evidence text rides raw with its newlines into the
    # volatile prompt, so a retrieved chunk quoting a context row must not ship the mandate on a
    # walk-less turn; the walk's own marker (CW_MARKER_PREFIX) is required beside the row
    assert ans._cascade_context_block_on(ROW1C) is False
    assert ans._cascade_context_block_on("...\n" + ROW1C + "\n" + ROW2C) is False
    assert ans._cascade_context_block_on("- [E4] a chunk quoting\n" + ROW1C + "\nmore text") is False
    assert ans._cascade_context_block_on(block) is True                        # row + marker arms
    assert ans._cascade_context_block_on(ROW1C + "\n" + mk) is True
    assert ans._cascade_context_block_on(ROW1C + "\n" + cq._cw_marker("second")) is True   # any walk marker
    assert ans._cascade_context_block_on("\n".join(_c_run()[0])) is True      # the REAL rendered block
    assert ans._cascade_context_block_on("") is False and ans._cascade_context_block_on(None) is False
    both = ans._system(cascade_walk=True, cascade_context=True)
    walk = ans._system(cascade_walk=True)
    assert ans._SYSTEM_CASCADE_CONTEXT in both and ans._SYSTEM_CASCADE_CONTEXT not in walk
    assert both.replace(ans._SYSTEM_CASCADE_CONTEXT, "") == walk               # a pure append
    assert ans._SYSTEM_CASCADE_CONTEXT not in ans._system(cascade_walk=True, cascade_context=False)
    assert ans._SYSTEM_CASCADE_CONTEXT not in ans._system()
    monkeypatch.delenv("GRAPHRAG_CASCADE_CONTEXT", raising=False)
    assert ans._cascade_context_block_on(block) is False
    assert ans._SYSTEM_CASCADE_CONTEXT not in ans._system(cascade_walk=True, cascade_context=True)
    assert ans._system(cascade_walk=True, cascade_context=True) == walk        # flag off: identical
    monkeypatch.setenv("GRAPHRAG_CASCADE_CONTEXT", "on")
    monkeypatch.delenv("GRAPHRAG_CASCADE_WALK", raising=False)
    assert ans._cascade_context_block_on(block) is False                       # a rider, never alone
    assert ans._SYSTEM_CASCADE_CONTEXT not in ans._system(cascade_walk=True, cascade_context=True)
    # the mandate: POSITIVELY phrased (refute M3), register-clean, no row token, no juxtaposition
    m = ans._SYSTEM_CASCADE_CONTEXT
    assert cq.CW_CONTEXT_TOKEN not in m and "beside the hop rows" not in m
    assert reg.count_flow_words(m) == 0 == reg.count_valuation_words(m)
    assert reg.internal_leaks(m) == [] and cq.pace_register_ok(m)
    for prohibition in ("never write", "never compare", "no 'because'", "RELATE IT TO NOTHING"):
        assert prohibition not in m
    assert "as DIGITS exactly as printed" in m and "stands on its own" in m
    # review F1: count-free on BOTH copy surfaces -- no singular row count anywhere
    for surface in (m, cq._cw_marker("first", context=True), cq._cw_marker("second", context=True)):
        assert "one row" not in surface.lower() and "that row" not in surface.lower(), surface
    assert "ROWS MARKED CONTEXT" in m and "under each" in m and "each such row once" in m
    # the seam builds the OFF request as exactly {focus_contract}; the two keys ride its own flag
    a_src = open(ans.__file__, encoding="utf-8").read()
    assert '_cw_req = {"focus_contract": _cw_focus}' in a_src
    assert 'if _cascade_context_on():' in a_src and '_cw_req["context"] = True' in a_src
    assert '_cw_req["replay"] = True' in a_src and '_cw_kw = {"cascade_walk": _cw_req}' in a_src
    assert a_src.count("cascade_context=_cascade_context_block_on(vp),") == 2   # both serving bodies


def test_context_constants_and_map_pins():
    from leviathan.graphrag import answer as ans
    from leviathan.graphrag import tracekeys as tk
    assert cq.CW_CONTEXT_CAP == cq.CW_MAX_FIRINGS == 2
    assert cq.CW_SPAN_MAX_DAYS < 365 and cq.CW_CONTEXT_MIN_OBS == 3
    assert cq.CW_CONTEXT_READS_PER_CELL == 1
    assert not hasattr(cq, "CW_CONTEXT_MIN_SPAN_DAYS")          # refute m2: the COUNT is the one floor
    assert set(cq._CW_CONTEXT_SERIES) == {"broiler_economics", "cattle_cycle_herd_size"}   # avian OUT
    assert cq._CW_CONTEXT_SERIES["broiler_economics"] == ("chicken_usd_t", "world chicken")
    assert cq._CW_CONTEXT_SERIES["cattle_cycle_herd_size"] == ("beef_usd_t", "world beef")
    assert cq._CW_CONTEXT_TABLE == cq._RV_PRICE_TABLE == "silver_pink_sheet"
    assert cq.CW_CONTEXT_TOKEN.startswith("] ")
    assert cq.CW_CONTEXT_LINE_RX.pattern.startswith(r"^- \[N\d+")
    assert set(cq._CW_CONTEXT_DECLINES) >= {"error", "no_unit", "no_release_stamp", "budget_cap",
                                            "context_cap", "replay", "grain_thin", "render_fence",
                                            "root_declined", "unmapped_slice"}
    assert tk.TRACE_RECORD_KEYS[-1] == "quantify_wave_reads"
    assert tk.TRACE_RECORD_KEYS[-2] == "quantify_cascade_walk"
    assert not any("context" in k for k in tk.TRACE_RECORD_KEYS)   # NO new trace key: the ledger rides inside
    src = open(cq.__file__, encoding="utf-8").read()
    assert src.count(cq.CW_CONTEXT_TOKEN) == 1 and "os.environ" not in src   # one producer, no env
    assert cq.CW_CONTEXT_TOKEN not in open(ans.__file__, encoding="utf-8").read()
    # the board ceiling test keeps its bytes (admission is SUBORDINATE)
    assert "if spent + cells_planned * CW_READS_PER_CELL > CW_TURN_CEILING:" in src
    assert "if cells_planned * CW_READS_PER_CELL > CW_CAP:" in src
    assert "spent + board_reads + ctx_admitted + 1 > CW_TURN_CEILING" in src


def test_check_cascade_context_and_r4c_fold_green(monkeypatch):
    from leviathan.graphrag import config_check as cc
    assert cc.check_cascade_context() == []
    assert cc._check_synthesized_price_legs() == []
    assert {"beef_usd_t", "chicken_usd_t"} <= cc.SYNTHESIZED_PRICE_LEG_ALLOW["silver_pink_sheet"]
    assert cc.check_cascade_walk() == []
    # the folds have teeth: an unregistered context metric reds R4c AND the naming clause; a slice no
    # shipping parent's tree resolves to reds the walk lint's (vii) enumeration (refute m8).
    monkeypatch.setattr(cq, "_CW_CONTEXT_SERIES",
                        dict(cq._CW_CONTEXT_SERIES, avian_influenza=("copper_usd_mt", "world copper")))
    assert any("copper_usd_mt" in e and "outside the ratified allow-list" in e
               for e in cc._check_synthesized_price_legs())
    errs = cc.check_cascade_context()
    assert any("avian_influenza" in e and "not named" in e for e in errs)
    assert any("copper_usd_mt" in e and "outside SYNTHESIZED_PRICE_LEG_ALLOW" in e for e in errs)
    monkeypatch.setattr(cq, "_CW_CONTEXT_SERIES",
                        dict(cq._CW_CONTEXT_SERIES, not_a_slice=("chicken_usd_t", "world chicken")))
    assert any("not_a_slice" in e and "reached by no shipping parent" in e
               for e in cc.check_cascade_walk())


def test_cw_context_rendered_expect_key_negative_branch():
    from leviathan.graphrag import eval as EV
    assert EV._CASCADE_EXPECT[-1] == "cw_context_rendered"
    empty = {"citations": [], "trace": {}, "structured": None, "answer": ""}
    assert EV._cascade_asserts({"expect": {"cw_context_rendered": False}}, empty)["cw_context_rendered"] is True
    assert EV._cascade_asserts({"expect": {"cw_context_rendered": True}}, empty)["cw_context_rendered"] is False
    _l, p, _c, _q, _s = _c_run()
    out = {"citations": [], "trace": {"quantify_cascade_walk": p}, "structured": None, "answer": ""}
    assert EV._cascade_asserts({"expect": {"cw_context_rendered": True}}, out)["cw_context_rendered"] is True
    assert EV._cascade_asserts({"expect": {"cw_context_rendered": False}}, out)["cw_context_rendered"] is False
    rec = next(iter([out]))
    assert EV._cascade_stats(rec)["cw_context_rendered"] == 1


def test_quantify_early_return_carries_the_context_pair():
    def _q(req):
        sgw, g, tape, calls = _c_sg(), _c_graph(), _c_tape(), []
        block, tr, rr = cq.quantify(sgw, g, qfn=tape, asof=ASOF_C, near=None,
                                    extra_number_calls=calls, cascade_walk=req)
        assert (tr, rr) == ([], [])
        return block, sgw, calls
    b_walk, sg_walk, c_walk = _q({"focus_contract": ROOT})
    b_ctx, sg_ctx, c_ctx = _q({"focus_contract": ROOT, "context": True})
    assert b_walk.startswith(cq._BLOCK_HEADER)
    assert "context" not in sg_walk.trace["quantify_cascade_walk"]
    assert ROW1C in b_ctx and ROW2C in b_ctx
    assert sg_ctx.trace["quantify_cascade_walk"]["context"]["rendered"] == 1
    assert len(c_ctx) == len(c_walk) + 1
    # the two blocks differ by EXACTLY the pair and the marker's context clause
    stripped = (b_ctx.replace("\n" + ROW1C + "\n" + ROW2C, "")
                .replace(cq._cw_marker("first", context=True), _PLAIN_MARKER))
    assert stripped == b_walk
    b_again, _s, _c = _q({"focus_contract": ROOT})
    assert b_again == b_walk                                        # deterministic, byte for byte


# == V2-4 -- THE PALM BOARD ON THE WALK (commit C, DARK on serving by construction) ==================
#
# The tenor rule lives in futures_roll (FORWARD_MONTH_FLOOR); what these pins hold is that it ARRIVES
# here through the shipped pricing sequence and that the MAJOR-8 tenor fence -- same-or-adjacent
# delivery month -- is still satisfiable once one leg of a hop is floored a month out.
#
# RE-CUT 2026-09-03 (STEP-12 review MAJ-2). The first cut of this fixture OMITTED the endpoint month
# from the soyoil tape, which parked the parent on X+1 and made a floor-2 child (X+2) look adjacent;
# the review measured the omission as the only reason the fence cleared (16 of 72 real endpoint
# dates fail it at floor 2). Both branches are now pinned on a soyoil tape that DOES list the
# endpoint month -- parent at X+1 because a CBOT oil contract stops trading mid-delivery-month, and
# parent at X on a board that trades through it -- and the fence clears on the rule's own merits at
# floor 1 in BOTH.
import pandas as pd
from leviathan.silver import futures_roll as FR

PALM = "malaysian_crude_palm_oil_cme"
SOYOIL = "soybean_oil_cbot"

# X = the endpoint month of the walk's firing window (W_END 2021-06-25) = 2021-06.
# THE PARENT, realistic CBOT shape: the endpoint month IS listed, and it is excluded by the BOARD'S
# OWN calendar (a soybean-oil contract's last trading day is the business day before the 15th of its
# delivery month) rather than by a hole in the fixture -- so the parent lands on X+1 honestly.
_LIFE_SOYOIL = {"2021-05": ("2021-02-15", "2021-05-14"),
                "2021-06": ("2021-02-15", "2021-06-14"),   # X -- LISTED, dies before t2 + 5
                "2021-07": ("2021-02-15", "2021-07-14"),   # X+1 -- nearest survivor, floor 0
                "2021-08": ("2021-02-15", "2021-08-13")}
# ...and the same board on a venue that trades INTO its delivery month, so the endpoint's own month
# survives t2 + 5 and the parent lands on X itself. This is the branch floor 2 could not serve.
_LIFE_SOYOIL_X = dict(_LIFE_SOYOIL, **{"2021-06": ("2021-02-15", "2021-06-30")})
# THE CHILD: the CPO calendar shape -- every contract prints to the last business day of its OWN
# delivery month, which is exactly why the shipped survivor rule would otherwise crown the
# endpoint's own still-accruing average.
_LIFE_PALM = {"2021-06": ("2021-02-15", "2021-06-30"),     # X -- survives t2+5, FLOORED OUT
              "2021-07": ("2021-02-15", "2021-07-30"),     # X+1 -- the floored survivor
              "2021-08": ("2021-02-15", "2021-08-31"),
              "2021-09": ("2021-02-15", "2021-09-30")}


def _v24_rows(life, priced_month, px0, px1, unit, currency):
    d, end = _dt.date.fromisoformat("2021-02-15"), _dt.date.fromisoformat("2021-08-15")
    out = []
    while d <= end:
        iso = d.isoformat()
        for cm, (first, last) in life.items():
            if not (first <= iso <= last):
                continue
            settle = (px0 if iso <= W_START else px1) if cm == priced_month else 400.0
            out.append({"value": settle, "knowledge_date": iso, "contract_month": cm,
                        "unit": unit, "currency": currency, "settle_kind": "settlement"})
        d += _dt.timedelta(days=1)
    return out


def _v24_graph():
    """A soyoil root with the palm child the LIVE graph declares (substitutes_for, plus, 0-2q)."""
    edge = {"seed": SOYOIL, "contract": PALM, "relation": "substitutes_for", "sign": "+",
            "lag": "0-2 quarters", "blurb": "the two oils stand in for one another in the same uses",
            "mechanism": "m"}
    nodes = {SOYOIL: "soybean_oil", PALM: "palm_oil"}
    return SimpleNamespace(
        contracts={SOYOIL: SimpleNamespace(drivers=[SimpleNamespace(id="heat")])},
        rev_cross_links=lambda c, _n=nodes: ([dict(edge)] if _n.get(c, c) == "soybean_oil" else []),
        contract_node=lambda c, _n=nodes: _n.get(c, c))


def _v24_tape_rows(soyoil_life=None, soyoil_priced="2021-07"):
    return {SOYOIL: _v24_rows(soyoil_life or _LIFE_SOYOIL, soyoil_priced, 60.0, 69.0,
                              "US cents/pound", "USD"),
            PALM: _v24_rows(_LIFE_PALM, "2021-07", 900.0, 990.0, "USD/metric ton", "USD")}


def _mk_month(s):
    return int(str(s)[:4]) * 12 + int(str(s)[5:7])


def test_the_floored_palm_child_lands_one_month_out_and_CLEARS_the_tenor_fence():
    """The whole point of the sitting: a floored child is still PAIRABLE. The endpoint month is in
    BOTH tapes; the parent takes X+1 because its own board stops trading mid-delivery-month, and the
    child is pushed to X+1 by the floor -- so the MAJOR-8 tenor fence (same-or-adjacent) sees the
    SAME month and the hop renders a verdict rather than declining."""
    calls: list = []
    qfn = _WTape(_v24_tape_rows())
    lines, payload = cq._cascade_walk_leg_or_nothing(
        _w_sg(), _v24_graph(), {"focus_contract": SOYOIL}, qfn, ASOF_W, calls)
    assert payload["outcome"] == "fired" and payload["order"] == "first"
    cells = {c["slug"]: c for c in payload["cells"]}
    assert cells[SOYOIL]["status"] == cells[PALM]["status"] == "closed"
    # X = the endpoint month, 2021-06 -- LISTED on both boards and taken by neither.
    assert cells[SOYOIL]["contract_month"] == "2021-07"
    assert cells[PALM]["contract_month"] == "2021-07"
    assert abs(_mk_month(cells[SOYOIL]["contract_month"])
               - _mk_month(cells[PALM]["contract_month"])) == 0
    assert cq._cw_fences(cells[SOYOIL], cells[PALM], 112) == (True, True)   # interval, TENOR
    # ...and the hop reached the reader as a verdict on the curated palm board label
    assert any(ln.startswith("CONSEQUENCE HOP CBOT soybean oil and CME palm oil") for ln in lines)
    assert any(ln.startswith("CONSEQUENCE READ") and "held" in ln for ln in lines)
    assert any("[N2] CME palm oil" in ln and "+10 %" in ln for ln in lines)
    assert cq._cw_register_fence(lines)
    # the machine slug NEVER leaves for the display label: the [N] call keeps the raw slug (review
    # D9 -- a display label in query.commodity kills the /v1/series chart locator).
    assert {c["query"]["commodity"] for c in calls} == {SOYOIL, PALM}
    assert not any(PALM in ln for ln in lines)


def test_the_fence_ALSO_clears_when_the_parent_lands_on_the_endpoint_month_itself(monkeypatch):
    """The other branch of MAJ-2, and the one that decided the recalibration. On a parent board that
    trades THROUGH its delivery month the shipped rule lands on X, so the child's floor is the whole
    tenor gap: at 1 the pair is adjacent and the hop serves; at 2 it is two months apart and the
    MAJOR-8 fence refuses a hop whose two legs both priced fine. That is the 16-of-72 coverage the
    review measured, reproduced here as a cell-level A/B on one fixture."""
    qfn = _WTape(_v24_tape_rows(soyoil_life=_LIFE_SOYOIL_X, soyoil_priced="2021-06"))
    soy, _r = cq._cw_cell(qfn, SOYOIL, W_START, W_END, W_SPAN, ASOF_W)
    palm, _r = cq._cw_cell(qfn, PALM, W_START, W_END, W_SPAN, ASOF_W)
    assert soy["status"] == palm["status"] == "closed"
    assert soy["contract_month"] == "2021-06"                    # X -- it survives t2 + 5 here
    assert palm["contract_month"] == "2021-07"                   # X+1 -- the shipped floor
    assert cq._cw_fences(soy, palm, 112) == (True, True)
    # ...and the counterfactual, measured rather than argued: floor 2 pushes the child to X+2 and
    # the tenor half of the SAME fence goes False on the SAME two priced cells.
    monkeypatch.setattr(FR, "FORWARD_MONTH_FLOOR", {PALM: 2})
    palm2, _r = cq._cw_cell(_WTape(_v24_tape_rows(soyoil_life=_LIFE_SOYOIL_X,
                                                  soyoil_priced="2021-06")),
                            PALM, W_START, W_END, W_SPAN, ASOF_W)
    assert palm2["contract_month"] == "2021-08"
    assert cq._cw_fences(soy, palm2, 112) == (True, False)       # interval OK, TENOR refused


def test_without_the_floor_the_palm_cell_would_price_the_endpoint_s_OWN_month(monkeypatch):
    """The guard on the guard. Emptying FORWARD_MONTH_FLOOR must visibly MOVE the palm cell -- if
    it did not, the pin above would be testing the fixture rather than the rule."""
    monkeypatch.setattr(FR, "FORWARD_MONTH_FLOOR", {})
    _l, payload = cq._cascade_walk_leg_or_nothing(
        _w_sg(), _v24_graph(), {"focus_contract": SOYOIL}, _WTape(_v24_tape_rows()), ASOF_W, [])
    cells = {c["slug"]: c for c in payload["cells"]}
    assert cells[PALM]["contract_month"] == "2021-06"        # the still-accruing average month


def test_the_floor_is_BYTE_IDENTICAL_on_every_non_palm_turn(monkeypatch):
    """The other direction, and the one that governs the live rev: no floored slug is reachable on
    a corn turn, so the whole rendered block, the payload and the minted calls must be identical
    with the floor table present and with it emptied."""
    def _run():
        calls: list = []
        qfn = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows()})
        lines, payload = cq._cascade_walk_leg_or_nothing(
            _w_sg(), _w_graph([_w_edge()]), {"focus_contract": ROOT}, qfn, ASOF_W, calls)
        return lines, payload, calls, list(qfn.sql)

    with_floor = _run()
    monkeypatch.setattr(FR, "FORWARD_MONTH_FLOOR", {})
    without = _run()
    assert with_floor == without
    assert FR._floor_months(pd.Series([ROOT, CHILD, GRAND])).tolist() == [0, 0, 0]


def test_the_episode_candidate_window_SHIFTS_rather_than_narrows():
    """The zero-margin hazard, pinned: with the floor and no shift the deep read would be scoped to
    [X, X+1, X+2] of which the selector can only take X+floor and up -- at the shipped floor of 1
    that leaves two usable months, at 2 exactly one, and one missing settlement row would decline a
    window on a board that priced fine. The window MOVES instead, so the margin is the same at every
    floor. The arithmetic is pinned at both 1 (shipped) and 2 (the pre-recalibration value, kept as
    the general case -- the shift is a function of the argument, not of the table)."""
    curve = [{"contract_month": m} for m in
             ("2021-05", "2021-06", "2021-07", "2021-08", "2021-09", "2021-10", "2021-11")]
    assert cq._episode_candidates(curve, "2021-06-25") == ["2021-06", "2021-07", "2021-08"]
    assert cq._episode_candidates(curve, "2021-06-25", floor_months=1) == \
        ["2021-07", "2021-08", "2021-09"]
    assert cq._episode_candidates(curve, "2021-06-25", floor_months=2) == \
        ["2021-08", "2021-09", "2021-10"]
    for k in (1, 2):
        assert len(cq._episode_candidates(curve, "2021-06-25", floor_months=k)) == \
            cq.EPISODE_OUTCOME_CANDIDATES
    # the shipped floor is what the cell actually passes, so pin the join to the table once
    assert cq._episode_candidates(curve, "2021-06-25",
                                  floor_months=FR.forward_month_floor(PALM)) == \
        ["2021-07", "2021-08", "2021-09"]
    # floor 0 is the shipped expression byte for byte, INCLUDING the year wrap the arithmetic adds
    months = sorted({r["contract_month"] for r in curve})
    for end in ("2021-01-04", "2021-06-25", "2021-12-31", "2022-03-01"):
        assert cq._episode_candidates(curve, end) == \
            [m for m in months if m >= str(end)[:7]][:cq.EPISODE_OUTCOME_CANDIDATES]
    wrap = [{"contract_month": m} for m in ("2021-12", "2022-01", "2022-02", "2022-03")]
    assert cq._episode_candidates(wrap, "2021-12-20", floor_months=2) == ["2022-02", "2022-03"]
