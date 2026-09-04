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
                        lambda order, context=False, fx=False:
                        "CASCADE EPISODE WALK: momentum is accelerating into 2027")
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
    # the walk yield. The ceiling is a runaway tripwire above the measured worst spend.
    #
    # V2-5 RE-ANCHOR, AND IT IS THE SET THAT IS TIGHTER, NOT THE INEQUALITY. The old single line
    # `CW_TURN_CEILING >= 44 + CW_CAP` (60 >= 56) was an inequality against a literal that
    # DOUBLE-COUNTED the walk -- the round-3 refute's ~44 already contained CW_CAP. These four pin
    # every literal exactly, including the deep ceiling's own four-term derivation, and the last one
    # states the deep budget against the MEASURED worst pre-walk turn (25) rather than mixing the
    # off-regime ceiling with the deep cap.
    assert cq.CW_TURN_CEILING == 60 and cq.CW_CAP == 12
    assert cq.CW_PREWALK_MEASURED_WORST == 65
    assert cq.CW_DEEP_TURN_CEILING == 80 == 44 + cq.CW_DEEP_CAP + cq.CW_CONTEXT_CAP + 7
    assert cq.CW_DEEP_TURN_CEILING >= 25 + cq.CW_DEEP_CAP + cq.CW_CONTEXT_CAP     # 80 >= 54
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
    assert ('c.get("kind") not in ("context", "fx")'
            in inspect.getsource(cq._cw_board_row_closed))
    assert cq._cw_board_row_closed([{"status": "closed", "kind": "context"}]) is False   # declines
    assert cq._cw_board_row_closed([{"status": "closed", "kind": "fx"}]) is False        # V2-3
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
    # V2-5's own seam, the same three-part discipline: the flag reader, the request key at
    # `if _cw_focus:` scope (NOT inside the context branch -- see the behavioural pin below), and the
    # mandate gate in BOTH serving bodies. The seam NEVER writes V2-3's `xccy`, so the engine's
    # union is MEASURABLY inert in this build.
    # V2-3 RE-ANCHOR (tighter, never looser): the `deep` key now rides the RIDER UNION at that same
    # `if _cw_focus:` scope, because the cross-currency rider lifts children and therefore needs the
    # same regime; V2-3's own key is set beside it, and `replay` was HOISTED out of the context
    # branch to the union (L1 -- nested, it was DEAD on exactly the flip shape).
    assert ('if _cascade_xccy_on() or _cascade_deep_on():' in a_src
            and '_cw_req["deep"] = True' in a_src)
    assert 'if _cascade_xccy_on():' in a_src and '_cw_req["xccy"] = True' in a_src
    assert a_src.count("cascade_deep=_cascade_deep_block_on(vp),") == 2
    assert a_src.count("cascade_xccy=_cascade_xccy_block_on(vp),") == 2
    assert 'if _pr_kw and (_cascade_context_on() or _cascade_xccy_on()' in a_src
    assert a_src.count('_cw_req["replay"] = True') == 1     # ONE site, at the union
    # the mandate gate reads the marker BY ATTRIBUTE, never as a copied string (the tl.LINE_PREFIX
    # discipline: producer and gate build from ONE literal and cannot drift)
    assert '_cq.CW_THIRD_ORDER_MARKER in (volatile_prompt or "")' in a_src


def test_context_constants_and_map_pins():
    from leviathan.graphrag import answer as ans
    from leviathan.graphrag import tracekeys as tk
    assert cq.CW_CONTEXT_CAP == cq.CW_MAX_FIRINGS == 2
    # V2-5 pins IN CODE that it does NOT move the depth-in-time bound, and therefore does not drag
    # the V2-1 rider's cap through the lockstep lint at config_check.py's clause (f).
    assert not hasattr(cq, "CW_DEEP_MAX_FIRINGS")
    # ...and that there is NO trim ladder: CW_DEEP_CAP equals the maximal legitimate shape exactly,
    # so the cap cannot bind and a future edit that re-adds a trim must re-open the cap arithmetic.
    assert not hasattr(cq, "CW_DEEP_TRIM_ORDER") and "trims" not in cq._CW_DEEP_DECLINES
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
    assert not any("deep" in k for k in tk.TRACE_RECORD_KEYS)      # V2-5: same law, same ledger
    src = open(cq.__file__, encoding="utf-8").read()
    assert src.count(cq.CW_CONTEXT_TOKEN) == 1 and "os.environ" not in src   # one producer, no env
    assert cq.CW_CONTEXT_TOKEN not in open(ans.__file__, encoding="utf-8").read()
    # the two board-budget tests read the SELECTED LOCALS (V2-5)...
    assert "if spent + cells_planned * CW_READS_PER_CELL > cw_ceiling:" in src
    assert "if cells_planned * CW_READS_PER_CELL > cw_cap:" in src
    # V2-3 RE-ANCHOR (L3): the shipped inequality is REPLACED by the ONE slack helper that BOTH
    # riders call, so a third rider cannot admit on its own arithmetic. Three assertions where
    # there was one, and the old literal is pinned ABSENT.
    assert src.count("def _cw_slack() -> int:") == 1
    assert src.count("_cw_slack() < 1") == 2
    assert "spent + board_reads + ctx_admitted + 1 > CW_TURN_CEILING" not in src
    # ...AND SO DOES THE RIDER SLACK, from the V2-3 FIX PASS on (build-refute minor + build-review
    # minor, both adopted): the rider is budgeted against `cw_ceiling`, the SAME number the board
    # plan two lines above it was admitted against -- 80 under deep/xccy, 60 off. The bare-60 form
    # made CW_DEEP_TURN_CEILING's own 7-read rider allowance structurally unreachable while
    # config_check's NOTE asserted it. The V2-1 "regime-independent" wording is retired WITH the
    # arithmetic; nothing off-regime moves, because off-regime cw_ceiling IS CW_TURN_CEILING.
    assert "return CW_TURN_CEILING - (spent + board_reads + ctx_admitted + fx_admitted)" not in src
    assert "return cw_ceiling - (spent + board_reads + ctx_admitted + fx_admitted)" in src


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
    # V2-3 RE-ANCHOR: the tail-append law made EXPLICIT rather than shifted -- the new key lands at
    # the tail and the context key keeps its position one in from it.
    assert EV._CASCADE_EXPECT[-1] == "cw_xccy_rendered"
    assert EV._CASCADE_EXPECT[-2] == "cw_context_rendered"
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


# ══ V2-5 PHASE 1 -- THE TWO PATHS THE F1 GOLDEN BANK WAS BLIND TO (refute-v4 fatal-1) ═══════════════
#
# The golden bank (data/consequence_leg/v25_golden_bank.py) records every call this suite makes to the
# walk and G1 asserts the post-build FLAG-OFF path reproduces it byte for byte. Re-run at HEAD it
# recorded 89 calls with `raised` None on ALL of them: the R6 belt at cascade.py:7055-7062 -- the ONE
# function V2-5's deep stamp and timer actually edit -- never executed, so it had no baseline. The same
# blindness covered `no_declared_children`, the only root-scope decline reached before child
# enumeration: test_walk_declines_root_scope_on_the_live_graph asserts it ABSENT, nothing asserted it
# present. These two fixtures put both paths into the banked population, and they are pins in their own
# right: the belt's contract (payload shape, ledger rollback to the CALLER'S base, the one trace key)
# and the pre-read named decline.
def test_walk_belt_declines_and_rolls_back_when_the_leg_raises(monkeypatch):
    """The R6 belt, on the one path the golden could not see. `_cw_marker` is reached AFTER both
    board cells priced and both call records were minted (cascade.py:7035), so the raise proves the
    rollback is real -- and proves it rolls back to the CALLER'S base, never to zero."""
    def boom(*_a, **_k):
        raise RuntimeError("marker exploded")

    monkeypatch.setattr(cq, "_cw_marker", boom)
    pre = {"query": {"table": "silver_cot"}, "rows": [], "status": "ok"}
    calls = [pre]                                          # a NON-EMPTY ledger: base is 1, not 0
    sg, qfn = _w_sg(), _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows()})
    lines, payload = cq._cascade_walk_leg_or_nothing(sg, _w_graph([_w_edge()]),
                                                     {"focus_contract": ROOT}, qfn, ASOF_W, calls)
    assert lines == []
    assert payload == {"outcome": "declined",
                       "declines": [{"scope": "root", "reason": "error"}]}
    assert calls == [pre]                                  # review D2: the LEDGER rolls back too
    assert sg.trace["quantify_cascade_walk"] is payload     # the ONE registered key still written
    assert len(qfn.sql) == 4                               # the reads WERE paid before the raise


def test_no_declared_children_declines_by_name_at_zero_reads():
    """A covered, LABELLED root whose node declares no cross-links at all: a named decline before
    any read, with the K2 rectangle trivially true at zero on every term."""
    qfn = _WTape({ROOT: _w_tape_rows()})
    lines, payload, calls, _q, _s = _w_run(graph=_w_graph([]), qfn=qfn)
    assert lines == [] and payload["outcome"] == "declined"
    assert payload["declines"] == [{"scope": "root", "reason": "no_declared_children"}]
    assert payload["root"] == ROOT and payload["path"] == [] and payload["cells"] == []
    assert (payload["children_declared"] == payload["children_priced"]
            == payload["children_named"] == 0)
    assert payload["net_reads"] == 0 and qfn.sql == [] and calls == []


# ══ V2-5 -- THE DEEPER/WIDER REGIME (GRAPHRAG_CASCADE_DEEP, built dark 2026-09-04) ══════════════════
#
# THE FIRST LAW IS FLAG-OFF BYTE-IDENTITY, and it is NOT held by these pins: it is held by the banked
# HEAD golden (data/consequence_leg/v25_golden_bank.py -> scratchpad/v25_golden_head_v2.json, 91 calls
# over the whole of this suite, taken BEFORE any engine edit) and asserted by G1, which re-runs that
# producer with the flag off and joins key by key. What follows holds the ENGINE under the regime.
#
# THE FIXTURE VOCABULARY. Real slugs on distinct nodes, all covered and all USD, so the gates are the
# real registers exactly as the sitting-2 fixtures use them:
#   ROOT corn_cbot (2010-06-06) -> CHILD soft_red_winter_wheat_cbot (2010-06-06)
#                               -> GRAND soybean_meal_cbot (2010-06-06)
#                               -> GREAT soybean_oil_cbot (2010-06-06)   [PAID]
#   FREE_LEG hard_red_spring_wheat_mgex (2025-09-09) -- covered only AFTER the firing window, so on
#            this suite's 2021 firing it is the engine's own `pre_coverage` cell: rendered, declared,
#            ZERO reads. That is the real shape rv_beans_oil measures on palm.
GREAT = "soybean_oil_cbot"
FREE_LEG = "hard_red_spring_wheat_mgex"
KCBT = "hard_red_winter_wheat_kcbt"
PALM_FREE = "malaysian_crude_palm_oil_cme"
_D_NODES = {ROOT: "corn", CHILD: "srw_wheat", GRAND: "soymeal", GREAT: "soybean_oil",
            FREE_LEG: "hrs_wheat", KCBT: "hrw_wheat", PALM_FREE: "palm_oil",
            "canola_ice": "canola", "campinas_corn_reference_bmf": "corn"}


def _d_node(c):
    return _D_NODES.get(c, c)


def _d_graph(edges_by_seed, drivers=("heat",)):
    """A chain/breadth-shaped stub over the real slugs: {seed_slug: [edge, ...]}, filed by NODE the
    way graph.py files rev rows, so `rev_cross_links` answers for any slug of that node."""
    by_node: dict = {}
    for seed, edges in edges_by_seed.items():
        by_node.setdefault(_d_node(seed), []).extend(edges)
    return SimpleNamespace(
        contracts={ROOT: SimpleNamespace(drivers=[SimpleNamespace(id=d) for d in drivers])},
        rev_cross_links=lambda c, _b=by_node: [dict(r) for r in _b.get(_d_node(c), [])],
        contract_node=_d_node)


def _d_chain(great=GREAT):
    """ROOT -> CHILD -> GRAND -> `great`, every hop declared with the same clean '+' 0-lag edge."""
    return _d_graph({ROOT: [_w_edge()],
                     CHILD: [_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")],
                     GRAND: [_w_edge(seed=GRAND, contract=great, relation="crushed_into")]})


def _d_tape(*slugs):
    return _WTape({s: _w_tape_rows() for s in slugs})


def _d_run(graph, qfn=None, sg=None, request=None, calls=None):
    """The `_w_run` shape with the DEEP key set -- the request the answer.py seam builds when
    GRAPHRAG_CASCADE_DEEP is on and GRAPHRAG_CASCADE_CONTEXT is off (its prod state)."""
    req = request if request is not None else {"focus_contract": ROOT, "deep": True}
    calls = [] if calls is None else calls
    qfn = qfn if qfn is not None else _d_tape(ROOT, CHILD, GRAND, GREAT)
    sg = sg if sg is not None else _w_sg(kept=(GRAND, GREAT))
    lines, payload = cq._cascade_walk_leg_or_nothing(sg, graph, req, qfn, ASOF_W, calls)
    return lines, payload, calls, qfn, sg


def _rect_ok(payload):
    """G2's per-level rectangle, read off the payload the way eval.py projects it."""
    return all(r["declared"] == r["priced"] + r["named"] + r["free"]
               for r in payload["deep"]["hops"].values())


# ── the constants, and the arithmetic identities behind every one of them ───────────────────────────
def test_deep_constants_are_pinned_with_their_own_arithmetic():
    assert cq.CW_DEEP_MAX_CHILDREN == 6 and cq.CW_DEEP_MAX_ORDER == 3
    assert cq.CW_FREE_ALLOWANCE == 2
    # the cap IS the maximal legitimate shape, which is why there is no trim ladder anywhere
    assert cq.CW_DEEP_CAP == 27 == (1 + cq.CW_DEEP_MAX_CHILDREN + 1 + 1) * cq.CW_READS_PER_CELL
    assert cq.CW_DEEP_TURN_CEILING == 80 == 44 + cq.CW_DEEP_CAP + cq.CW_CONTEXT_CAP + 7
    assert cq.CW_DEEP_TURN_CEILING >= 25 + cq.CW_DEEP_CAP + cq.CW_CONTEXT_CAP
    # NOT ONE SHIPPED VALUE MOVES -- the deep regime is a SECOND set of constants
    assert (cq.CW_READS_PER_CELL, cq.CW_MAX_FIRINGS, cq.CW_MAX_CHILDREN, cq.CW_CAP,
            cq.CW_TURN_CEILING) == (3, 2, 3, 12, 60)
    assert cq._CW_ORDER_WORDS == {1: "first", 2: "second", 3: "third"}
    # the CI lint's own census, on the SHIPPED ladder: 6 is the value V2-3's cross-currency lift
    # measures on corn_cbot (v25_v4_remeasure_20260903.json); the ladder as shipped reaches 4.
    from leviathan.graphrag import config_check as cc
    assert cc.check_cascade_walk() == []


def test_the_two_decline_vocabularies_are_separate_and_disjoint():
    # v3 put `not_kept_subgraph` in the DECLINES tuple while forbidding it from payload['declines'] --
    # two vocabularies wearing one name. They are separate tuples and the pin says so.
    assert set(cq._CW_DEEP_DECLINES) == {"no_next_hop"}
    assert set(cq._CW_HOP_CANDIDATE_REASONS) == {
        "child_uncovered", "node_cycle", "cross_currency", "sign_undeclared", "sign_not_unanimous",
        "lag_gate", "relation_unmapped", "blurb_not_unanimous", "not_kept_subgraph"}
    assert not (set(cq._CW_DEEP_DECLINES) & set(cq._CW_HOP_CANDIDATE_REASONS))
    # `composer_narrated_pair` is in NEITHER, and still reaches payload['declines'] at scope 'child'
    # (the shipped quirk, pinned AS a quirk); so are the two other child-scope budget reasons.
    for r in ("composer_narrated_pair", "child_not_priced_budget", "width_belt"):
        assert r not in cq._CW_DEEP_DECLINES and r not in cq._CW_HOP_CANDIDATE_REASONS
    # THE TRANSITIVE RULE IS NOT BUILT (refute-v4 major-1: on the shipped graph the coverage floors
    # are non-decreasing down the only chain, so a free ancestor implies every descendant free and
    # the rule would have saved zero reads while deleting declared absence rows).
    assert "ancestor_pre_coverage" not in cq._CW_DEEP_DECLINES
    # the READER-FACING absence vocabulary is untouched: the free rule keeps `pre_coverage` on the
    # page and mints no new absence word at all.
    assert "ancestor_pre_coverage" not in cq._CW_ABSENCE_WHY
    assert "pre_coverage" in cq._CW_ABSENCE_WHY
    assert not hasattr(cq, "_cw_free_path") and not hasattr(cq, "_cw_free_any")


def test_the_marker_is_minted_once_from_the_prefix_and_never_copied():
    src = open(cq.__file__, encoding="utf-8").read()
    assert cq.CW_THIRD_ORDER_MARKER == cq.CW_MARKER_PREFIX + "third order)"
    # the CONSTRUCTION EXPRESSION, not the assembled literal: _cw_marker builds its head from an
    # f-string, so "CASCADE EPISODE WALK (third order)" appears ZERO times in the module.
    assert src.count('CW_MARKER_PREFIX + "third order)"') == 1
    assert src.count(cq.CW_THIRD_ORDER_MARKER) == 0


def test_the_third_order_marker_clause_clears_the_serve_fence_both_ways():
    from leviathan.graphrag import register as reg
    plain, ctx = cq._cw_marker("third"), cq._cw_marker("third", context=True)
    assert plain.startswith(cq.CW_THIRD_ORDER_MARKER)
    for m in (plain, ctx):
        assert "coincidence test between two boards" in m and "the reader's inference" in m
        assert cq.pace_register_ok(m) and reg.count_valuation_words(m) == 0
        assert reg.count_flow_words(m) == 0 and not any(ch.isdigit() for ch in m)
    assert cq._cw_register_fence([plain]) and cq._cw_register_fence([ctx])
    # the first/second and context literals stay byte-for-byte what they were: the clause is keyed
    # on the word 'third' alone.
    for order in ("first", "second"):
        assert "coincidence test" not in cq._cw_marker(order)
        assert "coincidence test" not in cq._cw_marker(order, context=True)


# ── the three shapes under the regime (the flag-OFF twins at :490-518 keep every byte) ──────────────
def test_deep_breadth_prices_four_children_where_the_shipped_path_drops_one():
    """THE WIDTH HALF, on the head shape it exists for. Four admissible children: off, CW_MAX_CHILDREN
    is 3 and the alphabetical truncation drops the last by name; on, all four are paid and rendered."""
    kids = [_w_edge(contract=c) for c in (CHILD, GRAND, GREAT, KCBT)]
    g = _d_graph({ROOT: kids})
    l_off, p_off, c_off, _q, _s = _d_run(g, qfn=_d_tape(ROOT, CHILD, GRAND, GREAT, KCBT),
                                         request={"focus_contract": ROOT})
    assert p_off["children_declared"] == 4 and p_off["children_priced"] == 3
    assert any(d["reason"] == "child_not_priced_budget" for d in p_off["declines"])
    assert len(c_off) == 4                                    # root + THREE children
    l_on, p_on, c_on, _q2, _s2 = _d_run(g, qfn=_d_tape(ROOT, CHILD, GRAND, GREAT, KCBT))
    assert p_on["children_declared"] == 4 == p_on["children_priced"]
    assert not any(d["reason"] == "child_not_priced_budget" for d in p_on["declines"])
    assert len(c_on) == 5                                     # root + FOUR children
    assert p_on["deep"]["cells_planned"] == p_on["deep"]["paid_cells"] == 5
    assert p_on["net_reads"] == 10 and p_on["deep"]["cap"] == 27   # 5 cells, 2.00 reads each measured
    assert p_on["order"] == "first" and p_on["deep"]["order_n"] == 1   # every edge is off the ROOT
    assert _rect_ok(p_on) and p_on["deep"]["hops"]["child"]["declared"] == 4


def test_deep_depth_runs_a_third_hop_and_labels_it_third_order():
    lines, payload, calls, _q, _s = _d_run(_d_chain())
    assert payload["outcome"] == "fired" and payload["order"] == "third"
    assert payload["deep"]["order_n"] == 3
    assert payload["path"] == [ROOT, CHILD, GRAND, GREAT]
    assert len(calls) == 4 and payload["net_reads"] == 8      # 4 cells, 2 reads each
    assert payload["deep"]["cells_planned"] == payload["deep"]["paid_cells"] == 4
    assert lines[-1].startswith(cq.CW_THIRD_ORDER_MARKER)
    assert cq._cw_register_fence(lines)                       # K5 on REAL rendered lines
    # the hop-3 cell is priced and VERDICTED under the SAME fences as hop 2
    great_cell = next(c for c in payload["cells"] if c["slug"] == GREAT)
    assert great_cell["status"] == "closed" and great_cell["verdict"] in ("aligned", "at_odds")
    assert great_cell["interval_ok"] is True and great_cell["tenor_ok"] is True
    assert any(ln.startswith("CONSEQUENCE HOP CBOT soybean meal and CBOT soybean oil")
               for ln in lines)
    # the rectangle at every level
    assert _rect_ok(payload)
    assert payload["deep"]["hops"]["grand"] == {"declared": 1, "priced": 1, "named": 0,
                                                "free": 0, "absent": 0}
    assert payload["deep"]["hops"]["great"] == {"declared": 1, "priced": 1, "named": 0,
                                                "free": 0, "absent": 0}
    # ...and the SAME graph with the flag OFF stops at the second hop, byte-for-byte as today
    _l2, p2, c2, _q2, _s2 = _d_run(_d_chain(), request={"focus_contract": ROOT})
    assert p2["order"] == "second" and p2["path"] == [ROOT, CHILD, GRAND] and len(c2) == 3
    assert "deep" not in p2


def test_deep_depth_in_time_is_unchanged_in_shape():
    win2 = [{"start": W_START, "end": W_END, "span": W_SPAN, "n": 7},
            {"start": "2021-04-01", "end": "2021-06-20", "span": "2021-04..2021-06", "n": 5}]
    _l, payload, calls, _q, _s = _d_run(_d_graph({ROOT: [_w_edge()]}),
                                        qfn=_d_tape(ROOT, CHILD), sg=_w_sg(windows=win2))
    assert payload["outcome"] == "fired" and len(payload["firings"]) == 2
    assert len(calls) == 4                                    # (root + child) x two firings
    assert payload["deep"]["cells_planned"] == 4 and _rect_ok(payload)


def test_the_no_next_hop_decline_is_named_and_the_rectangle_holds_at_zero():
    _l, payload, _c, _q, _s = _d_run(_d_graph(
        {ROOT: [_w_edge()], CHILD: [_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")]}),
        qfn=_d_tape(ROOT, CHILD, GRAND), sg=_w_sg(kept=(GRAND,)))
    assert payload["order"] == "second" and payload["deep"]["order_n"] == 2
    assert {"scope": "great", "reason": "no_next_hop"} in payload["declines"]
    assert payload["deep"]["hops"]["great"] == {"declared": 0, "priced": 0, "named": 0,
                                                "free": 0, "absent": 0}
    assert _rect_ok(payload)                                  # 0 == 0 + 0 + 0, and G2 says so


# ── the free cell: rendered, declared, ZERO reads, and it books no paid slot ────────────────────────
def test_a_free_child_rides_outside_the_paid_budget_and_still_renders_its_absence():
    """The pre_coverage child renders its hop header AND its absence line, is excluded from
    cells_planned, and consumes NO paid slot -- so a FOURTH board that can print gets one."""
    kids = [_w_edge(contract=c) for c in (CHILD, GRAND, GREAT, FREE_LEG)]
    tape = _d_tape(ROOT, CHILD, GRAND, GREAT)                 # FREE_LEG is never asked for
    lines, payload, calls, qfn, _s = _d_run(_d_graph({ROOT: kids}), qfn=tape)
    assert payload["children_declared"] == 4 and payload["children_priced"] == 3
    assert payload["deep"]["hops"]["child"]["free"] == 1      # FREE_LEG rides, books nothing
    assert payload["children_named"] == 0                     # a free child is FREE, never NAMED
    assert _rect_ok(payload)                                  # 4 == 3 + 0 + 1
    assert payload["deep"]["cells_planned"] == payload["deep"]["paid_cells"] == 4   # not 5
    assert payload["net_reads"] == 8 and len(calls) == 4      # the free cell paid NOTHING
    free_cell = next(c for c in payload["cells"] if c["slug"] == FREE_LEG)
    assert free_cell["status"] == "declined" and free_cell["reason"] == "pre_coverage"
    assert free_cell["reads"] == 0
    assert payload["deep"]["hops"]["child"]["absent"] == 1
    assert any(ln.startswith("CONSEQUENCE HOP CBOT corn and MGEX hrs wheat") for ln in lines)
    assert any(cq._CW_ABSENCE_WHY["pre_coverage"] in ln for ln in lines)
    assert not any(FREE_LEG in s for s in qfn.sql)            # never read, not merely discounted


def test_a_free_great_leg_renders_an_absence_and_the_order_label_stops_at_the_paid_hop():
    """THE ALL-LEGS RULE, on the shape rv_beans_oil measures: the third hop is free, so the block
    renders FOUR cells for THREE paid.

    AND THE ORDER LABEL STOPS AT HOP 2 (build-refute B4, adjudicated): the free hop-3 cell prints an
    ABSENCE, not a read, so a 'third order' marker -- and the deep mandate it gates, which tells the
    writer to state each hop 'with its own handle and its own read as printed' -- would be describing
    a row that does not exist. The rendered PATH still carries all four boards: the page really did
    show that absence."""
    lines, payload, calls, _q, _s = _d_run(_d_chain(great=FREE_LEG),
                                           qfn=_d_tape(ROOT, CHILD, GRAND),
                                           sg=_w_sg(kept=(GRAND, FREE_LEG)))
    assert payload["order"] == "second" and payload["deep"]["order_n"] == 2
    assert payload["path"] == [ROOT, CHILD, GRAND, FREE_LEG]  # RENDERED, absences included
    assert not lines[-1].startswith(cq.CW_THIRD_ORDER_MARKER)
    assert lines[-1] == cq._cw_marker("second")
    assert len(payload["cells"]) == 4 and len(calls) == 3     # 4 rendered, 3 paid
    assert payload["deep"]["paid_cells"] == 3 and payload["net_reads"] == 6
    assert payload["deep"]["hops"]["great"] == {"declared": 1, "priced": 0, "named": 0,
                                                "free": 1, "absent": 1}
    assert _rect_ok(payload)                                  # 1 == 0 + 0 + 1, the state v3 could
    assert cq._cw_register_fence(lines)                       #   not express
    # ...and the mandate's OWN GATE KEY is absent from the block, so _cascade_deep_block_on can
    # never fire on it however the flags are set (the gate is `CW_THIRD_ORDER_MARKER in prompt`)
    assert cq.CW_THIRD_ORDER_MARKER not in "\n".join(lines)


def test_the_free_aggregation_is_over_every_selected_firing():
    """THE DIRECTION THAT COSTS: a child free on ONE of two firings is NOT free -- it books a paid
    cell on BOTH, renders an absence on the one where it is free, and is counted `named` (it never
    priced), never `free`. Over-reservation is safe; under-reservation would not be."""
    from leviathan.silver import futures_eod_contracts as FC
    f_early = {"start": "2013-03-05", "end": "2013-06-25", "span": "2013-03..2013-06", "n": 7}
    f_late = {"start": W_START, "end": W_END, "span": W_SPAN, "n": 5}
    # KCBT's coverage floor (2014-01-02) sits BETWEEN the two firing starts -- read off the ONE
    # predicate directly, so the aggregation is pinned on the rule and not on a tape shape
    assert cq._cw_free(FC.PRICE_COVERAGE_START, KCBT, f_early) is True
    assert cq._cw_free(FC.PRICE_COVERAGE_START, KCBT, f_late) is False
    _l, payload, _c, _q, _s = _d_run(_d_graph({ROOT: [_w_edge(contract=KCBT)]}),
                                     qfn=_d_tape(ROOT, KCBT),
                                     sg=_w_sg(windows=[f_early, f_late]))
    assert len(payload["firings"]) == 2
    assert payload["deep"]["hops"]["child"]["free"] == 0      # free on ONE firing is not free
    assert payload["deep"]["cells_planned"] == 4              # 2 firings x (root + the child)
    assert payload["deep"]["hops"]["child"]["named"] == 0     # it PRICED on the firing it covers
    assert payload["deep"]["hops"]["child"]["priced"] == 1
    assert _rect_ok(payload)
    # ...and the ALL-firings direction is the one that costs: had the aggregation been per-firing,
    # this child would have booked no cell on the early window and the plan would read 3, not 4.
    assert payload["deep"]["paid_cells"] == 4


# ── the runtime width belt: the tripwire the CI lint cannot be ─────────────────────────────────────
def test_the_width_belt_declines_the_excess_by_name_and_counts_it(monkeypatch):
    """refute-v4 major-3. Free children ride OUTSIDE the paid budget, so rendered width has no
    fail-closed bound of its own -- and configs/graphrag is gitignored and rides the image tar, so a
    curation edit can mint extra children on a serving image the lint never ran against. UNREACHABLE
    on the shipped graph (max out-degree 4 against 6 + 2), so it is forced here by the knob."""
    monkeypatch.setattr(cq, "CW_DEEP_MAX_CHILDREN", 1)
    monkeypatch.setattr(cq, "CW_FREE_ALLOWANCE", 0)
    kids = [_w_edge(contract=c) for c in (CHILD, GRAND, GREAT)]
    _l, payload, _c, _q, _s = _d_run(_d_graph({ROOT: kids}),
                                     qfn=_d_tape(ROOT, CHILD, GRAND, GREAT))
    reasons = [d["reason"] for d in payload["declines"]]
    assert reasons.count("child_not_priced_budget") == 2      # the paid budget takes them first
    assert (payload["children_declared"] == 3
            == payload["children_priced"] + payload["children_named"])
    assert _rect_ok(payload)
    # ...and with every child FREE the paid budget cannot bite at all, so the BELT is the ONLY
    # bound left -- which is the whole reason it exists. Only one shipped USD board has a coverage
    # floor after this suite's 2021 firing, so the second free child is made by moving palm's floor.
    from leviathan.silver import futures_eod_contracts as FC
    monkeypatch.setitem(FC.PRICE_COVERAGE_START, PALM_FREE, "2025-01-01")
    monkeypatch.setattr(cq, "CW_DEEP_MAX_CHILDREN", 0)
    free_kids = [_w_edge(contract=c) for c in (FREE_LEG, PALM_FREE)]
    _l2, p2, _c2, q2, _s2 = _d_run(_d_graph({ROOT: free_kids}), qfn=_d_tape(ROOT))
    belted = [d for d in p2["declines"] if d["reason"] == "width_belt"]
    assert len(belted) == 2 and {d["child"] for d in belted} == {FREE_LEG, PALM_FREE}
    assert p2["children_named"] == 2 and p2["deep"]["hops"]["child"]["free"] == 0
    assert not any(FREE_LEG in s or PALM_FREE in s for s in q2.sql)   # belted, never read
    assert _rect_ok(p2)


# ── L2: the rectangle is closed at EVERY early return, not only on the render path ──────────────────
@pytest.mark.parametrize("belt, sg_kw, patch", [
    ("no_firing_window", {"windows": []}, None),
    ("turn_spend_unknown", {"drop_wave": True}, None),
    ("cap", {}, ("CW_DEEP_CAP", 0)),
    ("turn_budget_spent", {"trace_extra": {"quantify_wave_reads": 79}}, None),
])
def test_the_rectangle_is_closed_on_every_root_scope_decline(monkeypatch, belt, sg_kw, patch):
    """refute-v4 FATAL 2: with the stamp only at the end of the render loop, a decline with k free
    children read {declared 0, priced 0, named 0, free k} and the invariant was FALSE (0 == k) on
    exactly the states the counters exist to describe. Every belt now carries a closed rectangle AND
    the mirror onto the shipped ledger."""
    if patch:
        monkeypatch.setattr(cq, patch[0], patch[1])
    drop = sg_kw.pop("drop_wave", False)
    sg = _w_sg(**sg_kw)
    if drop:
        del sg.trace["quantify_wave_reads"]                   # absent is never zero -> unknown
    kids = [_w_edge(contract=c) for c in (CHILD, GRAND, FREE_LEG)]
    _l, payload, _c, qfn, _s = _d_run(_d_graph({ROOT: kids}), qfn=_d_tape(ROOT, CHILD, GRAND), sg=sg)
    assert any(d["reason"] == belt for d in payload["declines"]), payload["declines"]
    assert qfn.sql == []                                      # every one of these is PRE-read
    hops = payload["deep"]["hops"]
    assert _rect_ok(payload)
    # THE MIRROR: the hop-1 row can never silently disagree with the shipped ledger
    assert hops["child"]["declared"] == payload["children_declared"] == 3
    assert hops["child"]["priced"] == payload["children_priced"]
    assert hops["child"]["named"] == payload["children_named"]
    # `absent` counts RENDERED cells, so it is 0 on a pre-render decline -- which is why
    # declared == priced + named + free + absent also holds on every root-scope decline.
    for row in hops.values():
        assert row["absent"] == 0
        assert row["declared"] == row["priced"] + row["named"] + row["free"] + row["absent"]


def test_the_no_firing_window_belt_names_the_same_children_in_both_regimes():
    kids = [_w_edge(contract=c) for c in (CHILD, GRAND, GREAT, KCBT)]
    g = _d_graph({ROOT: kids})
    _l, off, _c, _q, _s = _d_run(g, sg=_w_sg(windows=[]), request={"focus_contract": ROOT})
    _l2, on, _c2, _q2, _s2 = _d_run(g, sg=_w_sg(windows=[]))
    assert off["children_declared"] == off["children_named"] == 4
    assert on["children_declared"] == on["children_named"] == 4     # the SAME children, SAME total
    assert on["deep"]["hops"]["child"]["free"] == 0                 # no firing to classify against
    assert _rect_ok(on)


# ── the two extractions: same ladder, one implementation ────────────────────────────────────────────
def test_cw_admissible_children_returns_three_arms_and_the_lint_calls_it():
    from leviathan.graphrag import config_check as cc
    cov = {ROOT: "2010-06-06", CHILD: "2010-06-06"}
    g = _w_graph([_w_edge()])
    adm, dec, rd = cq._cw_admissible_children(g, cov, g.contract_node, ROOT)
    assert rd is None and dec == [] and [a["child"] for a in adm] == [CHILD]
    # arm 2: a covered non-canonical focus -- every row filed under ANOTHER seed
    g2 = _w_graph([_w_edge(seed="campinas_corn_reference_bmf")])
    assert cq._cw_admissible_children(g2, cov, g2.contract_node, ROOT)[2] == "focus_not_node_seed"
    # arm 3: no declared cross-links at all
    g3 = _w_graph([])
    assert cq._cw_admissible_children(g3, cov, g3.contract_node, ROOT)[2] == "no_declared_children"
    # ...and the child-scope declines come back in the shipped ORDER and the shipped SHAPE
    g4 = _w_graph([_w_edge(contract="canola_ice"), _w_edge(sign="0")])
    _a, d4, _r = cq._cw_admissible_children(g4, dict(cov, canola_ice="2010-01-01"),
                                            g4.contract_node, ROOT)
    assert d4 == [{"scope": "child", "reason": "cross_currency", "child": "canola_ice"},
                  {"scope": "child", "reason": "sign_undeclared", "child": CHILD}]
    # THE SHARED-LADDER PIN: clause (ix) calls the ENGINE's ladder and re-implements no child gate
    c_src = open(cc.__file__, encoding="utf-8").read()
    ix = c_src[c_src.index("# (ix) V2-5"):c_src.index("# (x) V2-5")]
    assert "_cw_admissible_children" in ix
    for gate in ("cross_currency", "sign_undeclared", "blurb_not_unanimous", "lag_gate"):
        assert gate not in ix


def test_cw_next_hop_names_each_of_the_nine_candidate_rejections():
    """The extraction's one behavioural risk is the decomposed `and` chain, and this is its bound: a
    candidate failing each test in turn returns None with the matching NAME, and none of the nine
    ever reaches payload['declines']."""
    cov = {ROOT: "2010-06-06", CHILD: "2010-06-06", GRAND: "2010-06-06",
           "canola_ice": "2010-01-01"}
    path = {_d_node(ROOT), _d_node(CHILD)}
    cases = [
        ("not_kept_subgraph", [_w_edge(seed=CHILD, contract=GRAND)], set(), cov),
        ("child_uncovered", [_w_edge(seed=CHILD, contract=GRAND)], {GRAND},
         {ROOT: "2010-06-06", CHILD: "2010-06-06"}),
        ("sign_undeclared", [_w_edge(seed=CHILD, contract=GRAND, sign="0")], {GRAND}, cov),
        ("sign_not_unanimous", [_w_edge(seed=CHILD, contract=GRAND, sign="+"),
                                _w_edge(seed=CHILD, contract=GRAND, sign="-",
                                        relation="correlates_with")], {GRAND}, cov),
        ("lag_gate", [_w_edge(seed=CHILD, contract=GRAND, lag="2-4 quarters")], {GRAND}, cov),
        ("relation_unmapped", [_w_edge(seed=CHILD, contract=GRAND, relation="refined_into")],
         {GRAND}, cov),
        ("blurb_not_unanimous", [_w_edge(seed=CHILD, contract=GRAND, blurb="a"),
                                 _w_edge(seed=CHILD, contract=GRAND, blurb="b",
                                         relation="correlates_with")], {GRAND}, cov),
        ("cross_currency", [_w_edge(seed=CHILD, contract="canola_ice")], {"canola_ice"}, cov),
        ("node_cycle", [_w_edge(seed=CHILD, contract=ROOT)], {ROOT}, cov),
    ]
    for reason, edges, keep, c in cases:
        p = {"declines": [], "deep": {"hop_candidates": []}}
        out = cq._cw_next_hop(_d_graph({CHILD: edges}), c, _d_node, keep, set(), CHILD,
                              path, p, level="grand", verbose=True)
        assert out is None, reason
        assert [x["reason"] for x in p["deep"]["hop_candidates"]] == [reason], reason
        assert [x["level"] for x in p["deep"]["hop_candidates"]] == ["grand"]
        assert p["declines"] == []                            # NEVER the decline census
    assert {c[0] for c in cases} == set(cq._CW_HOP_CANDIDATE_REASONS)


def test_cw_next_hop_emits_the_composer_decline_verbatim_and_off_path_is_silent():
    cov = {ROOT: "2010-06-06", CHILD: "2010-06-06", GRAND: "2010-06-06"}
    g = _d_graph({CHILD: [_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")]})
    p = {"declines": []}                                      # NO 'deep' key: the off-path shape
    out = cq._cw_next_hop(g, cov, _d_node, {GRAND}, {frozenset((CHILD, GRAND))}, CHILD,
                          {_d_node(ROOT), _d_node(CHILD)}, p, level="grand", verbose=False)
    assert out is None
    # scope 'child' VERBATIM -- the shipped quirk, preserved rather than tidied, because tidying it
    # would move bytes on the off path
    assert p["declines"] == [{"scope": "child", "reason": "composer_narrated_pair", "child": GRAND}]
    # the generalised node-distinctness test agrees with the shipped three-node form
    assert cq._cw_next_hop(g, cov, _d_node, {GRAND}, set(), CHILD,
                           {_d_node(ROOT), _d_node(CHILD)}, {"declines": []},
                           level="grand", verbose=False)["child"] == GRAND
    assert cq._cw_next_hop(g, cov, _d_node, {GRAND}, set(), CHILD,
                           {_d_node(ROOT), _d_node(CHILD), _d_node(GRAND)}, {"declines": []},
                           level="grand", verbose=False) is None


def test_keep_is_not_hoisted_out_of_the_single_child_branch(monkeypatch):
    """The shipped behaviour: on a turn with more than one admissible child `_cw_kept_contracts` is
    never called at all. The extraction must not have hoisted it."""
    seen: list = []

    def _spy(sg):
        seen.append(1)
        return set()

    monkeypatch.setattr(cq, "_cw_kept_contracts", _spy)
    kids = [_w_edge(contract=c) for c in (CHILD, GRAND)]
    _d_run(_d_graph({ROOT: kids}), qfn=_d_tape(ROOT, CHILD, GRAND))
    assert seen == []


# ── the shared regime, the same-currency switch and the seam ────────────────────────────────────────
def test_the_regime_is_the_union_with_v23s_key_and_the_union_is_inert_here():
    src = open(cq.__file__, encoding="utf-8").read()
    assert 'bool((walk_request or {}).get("deep") or (walk_request or {}).get("xccy"))' in src
    # a request carrying ONLY V2-3's key selects the SAME regime -- that is what makes the seam a
    # contract rather than a comment. Nothing writes `xccy` in this build (pinned on answer.py).
    _l, payload, _c, _q, _s = _d_run(_d_chain(), request={"focus_contract": ROOT, "xccy": True})
    assert payload["deep"]["max_children"] == cq.CW_DEEP_MAX_CHILDREN
    assert payload["order"] == "third"


def test_the_shape_switch_reads_the_same_currency_count_not_the_list_length():
    src = open(cq.__file__, encoding="utf-8").read()
    assert ('same_ccy_n = sum(1 for a in admissible '
            'if _cw_currency(a["child"]) == _cw_currency(root))') in src
    # V2-3 (L9) RE-ANCHOR: the two next-hop legs live in ONE dict keyed by _CW_HOP_LEVELS, so the
    # switch reads that dict rather than a second hand-spelled local.
    assert "if same_ccy_n == 1:" in src
    # V2-3 FIX PASS: the PREDICATE MOVED, '> 1' -> '!= 1'. The depth-in-time shape exists only for a
    # root whose spine is a SINGLE same-currency child; `== 0` was unreachable before the rider and
    # is live now (a root whose only children are lifted), and it used to fall through to two
    # firings and pay a hop-less second root cell.
    assert 'if same_ccy_n > 1 or hop_legs["grand"] is not None:' not in src
    assert 'if same_ccy_n != 1 or hop_legs["grand"] is not None:' in src
    # ...and the SAME predicate is re-taken POST-belt against the population the render loop reads,
    # so the two can never disagree about the shape (build-review minor).
    assert 'if len(firings) > 1 and len(same_ccy) != 1:' in src
    # the depth child is the UNIQUE same-currency member, never admissible[0] (refute-v4 major-2):
    # today they are the same element; the day V2-3 admits an FX sibling they are not.
    assert 'child = next(a["child"] for a in admissible' in src
    assert "admissible[0]" not in src


def test_the_deep_locals_are_read_nowhere_a_shipped_constant_should_be():
    """The pin that stops a future edit reading a shipped global in one belt and a deep local in
    another. Over the leg's own source, the three shipped knobs appear ONLY in their selection lines
    -- with CW_TURN_CEILING additionally, and only, in the V2-1 rider's subordinate admission test,
    which is regime-independent by design."""
    import inspect
    src = inspect.getsource(cq._cascade_walk_legs)
    body = src[src.index('payload: dict = {'):]               # past the docstring
    code = [ln.strip() for ln in body.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]

    def _lines_with(tok):
        return [ln for ln in code if tok in ln]

    # every CODE line mentioning a shipped knob, enumerated: the four selection lines and the
    # off-path truncation. Nothing else -- and after the V2-3 fix pass NOT the rider's admission
    # test either, which now reads the regime LOCAL like every other budget in the leg.
    assert _lines_with("CW_MAX_CHILDREN") == [
        "cw_children = CW_DEEP_MAX_CHILDREN if deep_on else CW_MAX_CHILDREN",
        "named_budget = admissible[CW_MAX_CHILDREN:]",
        "admissible = admissible[:CW_MAX_CHILDREN]"]
    assert _lines_with("CW_CAP") == ["cw_cap = CW_DEEP_CAP if deep_on else CW_CAP"]
    # V2-3 FIX PASS: CW_TURN_CEILING now appears on the REGIME SELECTION LINE AND NOWHERE ELSE in
    # the leg -- `_cw_slack` reads `cw_ceiling`, so the whole leg budgets against ONE number chosen
    # in ONE place. The docstring line inside the helper is stripped by the comment/blank filter
    # below only if it is a comment, so the enumeration is taken over CODE lines mentioning the token.
    assert _lines_with("CW_TURN_CEILING") == [
        "cw_ceiling = CW_DEEP_TURN_CEILING if deep_on else CW_TURN_CEILING"]
    # ...and BOTH budget tests spell the local: the board plan's and the riders' -- ONE number,
    # chosen once, spent by every gate in the leg.
    assert "if spent + cells_planned * CW_READS_PER_CELL > cw_ceiling:" in code
    assert "return cw_ceiling - (spent + board_reads + ctx_admitted + fx_admitted)" in code
    assert "cw_order_max = CW_DEEP_MAX_ORDER if deep_on else 2" in src
    # ...and the two board belts read the LOCALS, never the globals
    assert "if cells_planned * CW_READS_PER_CELL > cw_cap:" in src
    assert "if spent + cells_planned * CW_READS_PER_CELL > cw_ceiling:" in src
    # the off-path truncation stayed in its shipped position, under its own guard
    assert "if not deep_on:" in src


def test_the_seam_places_deep_outside_the_context_branch(monkeypatch):
    """BEHAVIOURAL, not textual, and it is the pin that would have caught a silently inert arm: the
    v2 draft's placement ('beside _cw_req["context"] = True') would make GRAPHRAG_CASCADE_DEEP do
    NOTHING whenever GRAPHRAG_CASCADE_CONTEXT is off -- which is its prod state."""
    from leviathan.graphrag import answer as ans
    monkeypatch.delenv("GRAPHRAG_CASCADE_CONTEXT", raising=False)
    monkeypatch.setenv("GRAPHRAG_CASCADE_DEEP", "on")
    assert ans._cascade_deep_on() is True and ans._cascade_context_on() is False
    req = {"focus_contract": ROOT}
    if ans._cascade_context_on():                             # the seam's own two branches, in order
        req["context"] = True
    if ans._cascade_deep_on():
        req["deep"] = True
    assert req == {"focus_contract": ROOT, "deep": True}
    _l, payload, _c, _q, _s = _d_run(_d_chain(), request=req)
    assert payload["order"] == "third" and "deep" in payload and "context" not in payload
    monkeypatch.delenv("GRAPHRAG_CASCADE_DEEP", raising=False)
    assert ans._cascade_deep_on() is False                    # read PER CALL -> the flip is live


def test_the_deep_mandate_rides_the_flag_the_block_and_the_third_order_marker(monkeypatch):
    from leviathan.graphrag import answer as ans
    from leviathan.graphrag import register as reg
    monkeypatch.setenv("GRAPHRAG_CASCADE_WALK", "on")
    monkeypatch.setenv("GRAPHRAG_CASCADE_DEEP", "on")
    assert ans._cascade_deep_block_on("") is False                        # no block
    assert ans._cascade_deep_block_on("... " + cq._cw_marker("second") + " ...") is False
    vp = "... " + cq._cw_marker("third") + " ..."
    assert ans._cascade_deep_block_on(vp) is True
    monkeypatch.delenv("GRAPHRAG_CASCADE_DEEP", raising=False)
    assert ans._cascade_deep_block_on(vp) is False                        # flag off -> no mandate
    monkeypatch.setenv("GRAPHRAG_CASCADE_DEEP", "on")
    on = ans._system(cascade_walk=True, cascade_deep=True)
    assert ans._SYSTEM_CASCADE_DEEP in on and "third order" in on
    assert ans._SYSTEM_CASCADE_DEEP not in ans._system(cascade_walk=True)   # DEFAULT FALSE
    # PHRASED POSITIVELY (the J6 addendum doctrine): it says what to write and names no prohibition
    m = ans._SYSTEM_CASCADE_DEEP
    assert reg.count_flow_words(m) == 0 == reg.count_valuation_words(m)
    assert reg.internal_leaks(m) == [] and cq.pace_register_ok(m)
    for prohibition in ("never write", "do not claim", "must not", "never derive"):
        assert prohibition not in m


# ── the timer, and no regime mixing on the error path ───────────────────────────────────────────────
def test_the_walk_timer_stamps_every_path_under_the_regime_and_none_with_the_flag_off(monkeypatch):
    _l, p_fired, _c, _q, _s = _d_run(_d_chain())
    assert p_fired["outcome"] == "fired" and isinstance(p_fired["deep"]["elapsed_ms"], int)
    _l, p_dec, _c, _q, _s = _d_run(_d_chain(), sg=_w_sg(windows=[]))
    assert p_dec["outcome"] == "declined" and isinstance(p_dec["deep"]["elapsed_ms"], int)

    def _boom(*_a, **_k):
        raise RuntimeError("marker exploded")

    # the EXCEPTION belt carries the regime -- otherwise a treatment error row projects as a control
    monkeypatch.setattr(cq, "_cw_marker", _boom)
    _l, p_err, calls, _q, _s = _d_run(_d_chain())
    assert p_err["outcome"] == "declined" and p_err["deep"]["error"] is True
    assert isinstance(p_err["deep"]["elapsed_ms"], int) and calls == []
    assert p_err["declines"] == [{"scope": "root", "reason": "error"}]
    # ...and with the flag OFF that same path carries NO 'deep' key at all
    _l, off_err, _c, _q, _s = _d_run(_d_chain(), request={"focus_contract": ROOT})
    assert off_err == {"outcome": "declined", "declines": [{"scope": "root", "reason": "error"}]}


def test_the_eval_projections_read_the_deep_ledger_without_re_deriving_it():
    from leviathan.graphrag import eval as EV
    _l, p, _c, _q, _s = _d_run(_d_chain())
    rec = {"citations": [], "trace": {"quantify_cascade_walk": p}, "structured": None, "answer": ""}
    st = EV._cascade_stats(rec)
    assert st["cw_deep_on"] is True and st["cw_order_n"] == 3
    assert st["cw_cap_applied"] == 27 and st["cw_ceiling_applied"] == 80
    assert st["cw_max_children_applied"] == 6 and st["cw_max_order_applied"] == 3
    assert st["cw_cells_planned"] == st["cw_paid_cells"] == 4
    assert st["cw_plan_reads"] == 12 == 4 * cq.CW_READS_PER_CELL   # THE PLAN -- the barred quantity
    assert st["cw_board_reads"] == st["cw_reads"] == 8             # the rider is off: they agree
    assert st["cw_plan_reads"] <= cq.CW_DEEP_CAP
    assert st["cw_deep_identity_ok"] is True and st["cw_child_identity_ok"] is True
    assert st["cw_hops"]["great"]["priced"] == 1 and st["cw_children_free"] == 0
    assert st["cw_hop3_verdict"] in ("aligned", "at_odds")
    assert st["cw_hop2_declines"] == [] and st["cw_hop3_declines"] == []
    assert isinstance(st["cw_walk_elapsed_ms"], int)
    # a hop-3 decline lands in its OWN scope column, never in hop 2's
    _l2, p_nn, _c2, _q2, _s2 = _d_run(_d_graph(
        {ROOT: [_w_edge()], CHILD: [_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")]}),
        qfn=_d_tape(ROOT, CHILD, GRAND), sg=_w_sg(kept=(GRAND,)))
    nn = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p_nn},
                            "structured": None, "answer": ""})
    assert nn["cw_hop3_declines"] == ["no_next_hop"] and nn["cw_hop2_declines"] == []
    # walk-less and flag-off rows read True / None, never None-noise or KeyError
    empty = EV._cascade_stats({"citations": [], "trace": {}, "structured": None, "answer": ""})
    assert empty["cw_deep_on"] is False and empty["cw_deep_identity_ok"] is True
    assert empty["cw_plan_reads"] is None and empty["cw_children_free"] is None
    _l3, p_off, _c3, _q3, _s3 = _d_run(_d_chain(), request={"focus_contract": ROOT})
    off = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p_off},
                             "structured": None, "answer": ""})
    assert off["cw_deep_on"] is False and off["cw_deep_identity_ok"] is True
    assert off["cw_child_identity_ok"] is True and off["cw_plan_reads"] is None
    # _CASCADE_EXPECT is NOT edited: every new key is an ARTIFACT projection, never a deck word
    assert EV._CASCADE_EXPECT[-1] == "cw_xccy_rendered"        # V2-3 re-anchor
    assert EV._CASCADE_EXPECT[-2] == "cw_context_rendered"
    assert not any("deep" in k for k in EV._CASCADE_EXPECT)


# ── the order label: the equivalence and its DISCRIMINATING population ──────────────────────────────
def test_the_order_expression_agrees_with_the_shipped_one_on_every_rendered_shape():
    """The marquee case is the one a NODE-COUNT formula gets wrong: two edges BOTH from the root is
    'first' by hop count and 'second' by node count, and it is a shape the deck actually renders
    (rv_soyoil_palm_stress). The pin asserts the equivalence AND that the discriminating population
    is non-empty, so it can never pass vacuously.

    THE DEEP SIDE IS THE SHIPPED EXPRESSION ITSELF (build-review minor): `cq._cw_order_n` is the
    function the engine calls -- the earlier version of this pin re-implemented BOTH formulas
    locally, so an edit to the engine's depth loop passed it untouched. Only the OFF-path expression
    is re-typed here, and it is pinned to the engine's source line below."""
    import inspect

    def _shipped(root, pairs):
        return "second" if any(p != root for (p, _c) in pairs) else "first"

    # the off-path line, verbatim from the leg -- so `_shipped` cannot drift from it either
    assert ('payload["order"] = "second" if any(p != root for (p, _c) in rendered_pairs) '
            'else "first"') in inspect.getsource(cq._cascade_walk_legs)
    assert "order_n = _cw_order_n(root, rendered_pairs, _closed)" in \
        inspect.getsource(cq._cascade_walk_legs)

    def _deep(root, pairs):
        # every rendered board CLOSED -- the equivalence population is the hole-free one; the
        # holed shapes are pinned in test_the_order_label_walks_the_closed_chain_...
        closed = {root} | {c for (_p, c) in pairs}
        return cq._CW_ORDER_WORDS.get(cq._cw_order_n(root, pairs, closed), "third")

    shapes = [[],                                                    # nothing rendered -> 'first'
              [(ROOT, CHILD)],                                       # one hop -> 'first'
              [(ROOT, CHILD), (ROOT, GRAND)],                        # BREADTH -> 'first', not
              [(ROOT, CHILD), (ROOT, GRAND), (ROOT, GREAT)],         #   'second'
              [(ROOT, CHILD), (CHILD, GRAND)]]                       # depth -> 'second'
    n_rendered = 0
    for pairs in shapes:
        assert _deep(ROOT, pairs) == _shipped(ROOT, pairs), pairs
        n_rendered += bool(pairs)
    assert n_rendered == 4                                           # a real discriminating set
    # ...and the ONE place they differ is the third hop, which the shipped expression cannot express
    deep3 = [(ROOT, CHILD), (CHILD, GRAND), (GRAND, GREAT)]
    assert _deep(ROOT, deep3) == "third" and _shipped(ROOT, deep3) == "second"


def test_a_great_cell_whose_parent_declined_renders_undetermined_never_a_direction():
    """K3/K4 at hop 3: a great cell whose grand parent did not close can never carry a verdict --
    and the ORDER LABEL now stops at the last CLOSED hop, so a chain with a hole at hop 2 reads
    'first', not 'third' (build-refute B4). The rendered PATH is unchanged: the page showed the rows.
    """
    tape = _WTape({ROOT: _w_tape_rows(), CHILD: _w_tape_rows(), GREAT: _w_tape_rows()})
    lines, payload, _c, _q, _s = _d_run(_d_chain(), qfn=tape)     # GRAND is served NO rows
    cells = {c["slug"]: c for c in payload["cells"]}
    assert cells[GRAND]["status"] != "closed"
    assert cells[GREAT].get("verdict") in (None, "undetermined")
    assert payload["order"] == "first" and payload["deep"]["order_n"] == 1
    assert payload["path"] == [ROOT, CHILD, GRAND, GREAT]         # RENDERED, holes included
    assert cq.CW_THIRD_ORDER_MARKER not in "\n".join(lines)
    assert not any("moved with the declared relation" in ln and "soybean oil" in ln for ln in lines)
    assert _rect_ok(payload)


def test_the_order_label_walks_the_closed_chain_and_a_hole_at_hop_1_caps_it(monkeypatch):
    """THE REFUTER'S B4 SHAPE, reproduced on the engine: root closed, the CHILD cell declines
    `no_tape_rows`, and BOTH the grand and the great price and close. The old label derived from the
    rendered hop HEADERS, so it read 'third order', shipped CW_THIRD_ORDER_MARKER, and so shipped the
    deep mandate -- which instructs the writer to state each hop with 'its own handle and its own read
    as printed' when hop 1 printed an absence and nothing else. The chain of CLOSED cells breaks at
    hop 1, so the label is 'first' and the third-order marker never mints."""
    tape = _WTape({ROOT: _w_tape_rows(), GRAND: _w_tape_rows(), GREAT: _w_tape_rows()})
    lines, payload, _c, _q, _s = _d_run(_d_chain(), qfn=tape)     # CHILD is served NO rows
    cells = {c["slug"]: c for c in payload["cells"]}
    assert cells[ROOT]["status"] == "closed" and cells[CHILD]["status"] != "closed"
    assert cells[GRAND]["status"] == "closed" and cells[GREAT]["status"] == "closed"
    assert payload["deep"]["hops"]["grand"]["priced"] == 1        # they really did price
    assert payload["deep"]["hops"]["great"]["priced"] == 1
    assert payload["order"] == "first" and payload["deep"]["order_n"] == 1
    assert cq.CW_THIRD_ORDER_MARKER not in "\n".join(lines)
    assert lines[-1] == cq._cw_marker("first")
    assert _rect_ok(payload)
    # ...and the helper says the same thing directly, on the same three pairs
    pairs = [(ROOT, CHILD), (CHILD, GRAND), (GRAND, GREAT)]
    assert cq._cw_order_n(ROOT, pairs, {ROOT, GRAND, GREAT}) == 1      # hole at hop 1
    assert cq._cw_order_n(ROOT, pairs, {ROOT, CHILD, GREAT}) == 1      # hole at hop 2
    assert cq._cw_order_n(ROOT, pairs, {ROOT, CHILD, GRAND}) == 2      # hole at hop 3
    assert cq._cw_order_n(ROOT, pairs, {ROOT, CHILD, GRAND, GREAT}) == 3   # hole-free


# == V2-5 STEP-12 ADJUDICATED FIXES -- the review's and the refuter's findings, each with its pin ====
#
# Every pin below reproduces the state its finding NAMED before it asserts the remedy. Where a finding
# was "this column is structurally always empty / vacuously true", the pin drives the ENGINE into the
# state and reads the projection, never the source.


def test_the_free_predicate_has_exactly_one_implementation_in_the_leg():
    """build-review major: the render loop spelled `str(cov[child]) > t1` inline while `_cw_free`'s
    docstring claimed 'there is no second predicate anywhere in this leg'. They agreed only because
    t1 IS f["start"] -- and a divergence would leave a child in free_set (0 paid cells) and then
    PRICE it, i.e. realized reads above the plan the cap belt approved. One implementation now."""
    import inspect
    body = inspect.getsource(cq._cascade_walk_legs)
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))
    assert code.count("if _cw_free(cov, child, f):") == 1
    assert "str(cov[child]) > t1" not in code          # the finding's own string, in CODE
    # the free SET and the render loop call the SAME function -- one call site each, no third copy
    assert code.count("_cw_free(") == 2
    assert 'return str(cov[slug]) > str(firing["start"])' in inspect.getsource(cq._cw_free)


def test_cw_deep_max_order_binds_the_number_of_next_hop_calls(monkeypatch):
    """build-review minor: cw_order_max used to be read ONLY to stamp payload['deep']['max_order'];
    the real depth bound was 'there are two hand-written calls'. It is the LOOP bound now."""
    assert cq.CW_DEEP_MAX_ORDER - 1 == len(cq._CW_HOP_LEVELS) == 2
    assert cq._CW_HOP_LEVELS == ("grand", "great")
    seen: list = []
    _orig = cq._cw_next_hop

    def _spy(*a, **kw):
        seen.append(kw.get("level"))
        return _orig(*a, **kw)

    monkeypatch.setattr(cq, "_cw_next_hop", _spy)
    _l, p, _c, _q, _s = _d_run(_d_chain())
    assert seen == ["grand", "great"] and p["deep"]["order_n"] == 3      # 3 - 1 = TWO calls
    # ...turn the knob down and the SECOND call is not made at all -- the bound is the loop
    seen.clear()
    monkeypatch.setattr(cq, "CW_DEEP_MAX_ORDER", 2)
    _l2, p2, _c2, _q2, _s2 = _d_run(_d_chain())
    assert seen == ["grand"] and p2["deep"]["max_order"] == 2 and p2["order"] == "second"
    # ...and OFF it is one call at level 'grand', which is the shipped shape byte for byte
    seen.clear()
    monkeypatch.setattr(cq, "CW_DEEP_MAX_ORDER", 3)
    _l3, p3, _c3, _q3, _s3 = _d_run(_d_chain(), request={"focus_contract": ROOT})
    assert seen == ["grand"] and "deep" not in p3 and p3["order"] == "second"
    # the ledger's levels ARE the vocabulary, never a re-spelling
    _l4, p4, _c4, _q4, _s4 = _d_run(_d_chain())
    assert tuple(p4["deep"]["hops"]) == ("child",) + cq._CW_HOP_LEVELS


def test_the_hop2_miss_is_named_and_counted_like_the_hop3_miss():
    """build-refute major-3, MEASURED: deep on, ONE admissible child, no declared grandchild -- the
    most common deep shape -- recorded ZERO evidence that hop 2 was attempted, while the symmetric
    hop-3 miss WAS named. eval's cw_hop2_declines was structurally always [] and so unfalsifiable."""
    from leviathan.graphrag import eval as EV
    _l, p, _c, qfn, _s = _d_run(_d_graph({ROOT: [_w_edge()]}), qfn=_d_tape(ROOT, CHILD))
    assert {"scope": "grand", "reason": "no_next_hop"} in p["declines"]
    assert not any(d["scope"] == "great" for d in p["declines"])     # the walk STOPPED at the miss
    assert p["deep"]["hops"]["grand"] == {"declared": 0, "priced": 0, "named": 0,
                                          "free": 0, "absent": 0}
    assert _rect_ok(p) and p["order"] == "first"
    st_ = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p},
                             "structured": None, "answer": ""})
    assert st_["cw_hop2_declines"] == ["no_next_hop"] and st_["cw_hop3_declines"] == []
    # ZERO READS: the whole hop-2 ladder is graph reads, and the decline costs nothing
    assert len(qfn.sql) == 4                                        # root + child, 2 reads each
    # ...and with the flag OFF the same shape appends NOTHING (byte-identity, held by G1 too)
    _l2, off, _c2, _q2, _s2 = _d_run(_d_graph({ROOT: [_w_edge()]}), qfn=_d_tape(ROOT, CHILD),
                                     request={"focus_contract": ROOT})
    assert not any(d["reason"] == "no_next_hop" for d in off["declines"])


def test_the_hop3_composer_decline_carries_its_own_scope():
    """build-refute minor: the shipped quirk files `composer_narrated_pair` at scope 'child'. On the
    HOP-3 call that named a GREAT candidate under child scope, so payload['declines'] at scope
    'child' could name a slug that was never in children_declared. The scope is the LEVEL now --
    and the hop-2 call (the only one the off path makes) keeps the quirk verbatim."""
    cov = {ROOT: "2010-06-06", CHILD: "2010-06-06", GRAND: "2010-06-06", GREAT: "2010-06-06"}
    g = _d_graph({GRAND: [_w_edge(seed=GRAND, contract=GREAT, relation="crushed_into")]})
    p = {"declines": [], "deep": {"hop_candidates": []}}
    out = cq._cw_next_hop(g, cov, _d_node, {GREAT}, {frozenset((GRAND, GREAT))}, GRAND,
                          {_d_node(ROOT), _d_node(CHILD), _d_node(GRAND)}, p,
                          level="great", verbose=True)
    assert out is None
    assert p["declines"] == [{"scope": "great", "reason": "composer_narrated_pair",
                              "child": GREAT}]
    # ...and the hop-2 call keeps the shipped quirk's word, which is what the off path emits
    p2 = {"declines": [], "deep": {"hop_candidates": []}}
    g2 = _d_graph({CHILD: [_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")]})
    assert cq._cw_next_hop(g2, cov, _d_node, {GRAND}, {frozenset((CHILD, GRAND))}, CHILD,
                           {_d_node(ROOT), _d_node(CHILD)}, p2,
                           level="grand", verbose=True) is None
    assert p2["declines"] == [{"scope": "child", "reason": "composer_narrated_pair",
                              "child": GRAND}]


def test_cw_hop_candidates_projects_the_level_beside_the_reason():
    """build-refute minor: the artifact projected a bare reason, so an arm could not tell a hop-2
    rejection from a hop-3 one -- exactly the discrimination the nine-name vocabulary exists for."""
    from leviathan.graphrag import eval as EV
    g = _d_graph({ROOT: [_w_edge()],
                  CHILD: [_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")],
                  GRAND: [_w_edge(seed=GRAND, contract=GREAT, relation="crushed_into")]})
    _l, p, _c, _q, _s = _d_run(g, sg=_w_sg(kept=(GRAND,)))       # GREAT is NOT kept
    assert p["deep"]["hop_candidates"] == [{"level": "great", "child": GREAT,
                                            "reason": "not_kept_subgraph"}]
    st_ = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p},
                             "structured": None, "answer": ""})
    assert st_["cw_hop_candidates"] == [{"level": "great", "reason": "not_kept_subgraph"}]


def test_the_width_belt_reads_a_regime_local_like_every_other_budget():
    """build-refute minor: the width belt was the ONE budget reading a module GLOBAL where every
    other reads a local selected once at `deep_on` -- against the build's own stated law."""
    import inspect
    src = inspect.getsource(cq._cascade_walk_legs)
    code = [ln.strip() for ln in src.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    assert [ln for ln in code if "CW_FREE_ALLOWANCE" in ln][0].startswith(
        "cw_free_allow = CW_FREE_ALLOWANCE")
    assert len([ln for ln in code if "CW_FREE_ALLOWANCE" in ln]) == 1
    assert "_over = len(kept) - (cw_children + cw_free_allow)" in src
    _l, p, _c, _q, _s = _d_run(_d_chain())
    assert p["deep"]["free_allowance"] == cq.CW_FREE_ALLOWANCE == 2


def test_a_fenced_deep_block_projects_no_plan_no_order_and_no_hop3_verdict(monkeypatch):
    """build-refute minor B5, MEASURED: a fenced third-order block rolled every call back and shipped
    ZERO lines, yet still projected cw_order_n 3, cw_paid_cells 4, cw_plan_reads 12 and a hop-3
    verdict -- so an analyst filtering on cw_hop3_verdict without also filtering cw_outcome counted a
    block nobody read. The context rider already zeroed its own `rendered` here."""
    from leviathan.graphrag import eval as EV
    _l0, ok, _c0, _q0, _s0 = _d_run(_d_chain())
    assert ok["outcome"] == "fired" and ok["deep"]["order_n"] == 3       # the state before the fence
    monkeypatch.setattr(cq, "_cw_register_fence", lambda _lines: False)
    lines, p, calls, _q, _s = _d_run(_d_chain())
    assert p["outcome"] == "fenced" and lines == [] and calls == []
    assert p["deep"]["order_n"] is None and p["deep"]["cells_planned"] is None
    assert p["deep"]["paid_cells"] is None
    assert all(r["priced"] == 0 == r["absent"] for r in p["deep"]["hops"].values())
    assert _rect_ok(p)                                       # named took the priced terms
    # the TOP-LEVEL ledger folded the same way, so eval's hop-1 mirror cannot contradict the row
    assert p["children_priced"] == 0 == p["deep"]["hops"]["child"]["priced"]
    assert p["children_named"] == p["deep"]["hops"]["child"]["named"]
    st_ = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p},
                             "structured": None, "answer": ""})
    assert st_["cw_outcome"] == "fenced"
    assert st_["cw_order_n"] is None and st_["cw_plan_reads"] is None
    assert st_["cw_paid_cells"] is None and st_["cw_hop3_verdict"] is None
    # the config echoes STAY -- they were never claims about a shipped block
    assert st_["cw_cap_applied"] == 27 and st_["cw_max_order_applied"] == 3


def test_cw_hop3_verdict_is_none_on_every_row_without_a_third_hop():
    """build-review + build-refute major-1, MEASURED: `_cw_deepest` took the LAST non-root,
    non-context cell UNGATED BY ORDER, so a deep BREADTH row, a DEPTH-IN-TIME row and a FLAG-OFF
    CONTROL row all projected some child's verdict as the arm's headline hop-3 metric."""
    from leviathan.graphrag import eval as EV

    def _st(payload):
        return EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": payload},
                                  "structured": None, "answer": ""})

    # (a) FLAG OFF -- the control arm. The old code projected the last child's verdict here.
    _l, off, _c, _q, _s = _d_run(_d_chain(), request={"focus_contract": ROOT})
    assert off["order"] == "second" and off["cells"][-1].get("verdict") in ("aligned", "at_odds")
    assert _st(off)["cw_deep_on"] is False and _st(off)["cw_hop3_verdict"] is None
    # (b) DEEP BREADTH -- order 1, three children, every one verdicted
    kids = [_w_edge(contract=c) for c in (CHILD, GRAND, GREAT)]
    _l2, br, _c2, _q2, _s2 = _d_run(_d_graph({ROOT: kids}), qfn=_d_tape(ROOT, CHILD, GRAND, GREAT))
    assert br["deep"]["order_n"] == 1 and br["cells"][-1].get("verdict") in ("aligned", "at_odds")
    assert _st(br)["cw_hop3_verdict"] is None
    # (c) DEPTH IN TIME -- order 1, two firings, the last cell is a CHILD cell
    win2 = [{"start": W_START, "end": W_END, "span": W_SPAN, "n": 7},
            {"start": "2021-04-01", "end": "2021-06-20", "span": "2021-04..2021-06", "n": 5}]
    _l3, dt, _c3, _q3, _s3 = _d_run(_d_graph({ROOT: [_w_edge()]}), qfn=_d_tape(ROOT, CHILD),
                                    sg=_w_sg(windows=win2))
    assert dt["deep"]["order_n"] == 1 and _st(dt)["cw_hop3_verdict"] is None
    # (d) THE ONE ROW THAT SHOULD CARRY IT: a hole-free third-order chain, keyed off the GREAT slug
    _l4, d3, _c4, _q4, _s4 = _d_run(_d_chain())
    great_cell = next(c for c in d3["cells"] if c["slug"] == GREAT)
    assert _st(d3)["cw_order_n"] == 3
    assert _st(d3)["cw_hop3_verdict"] == great_cell["verdict"]
    assert great_cell["verdict"] in ("aligned", "at_odds")
    # (e) a HOLED chain is order 1 and carries no hop-3 verdict either, though a great cell closed
    tape = _WTape({ROOT: _w_tape_rows(), GRAND: _w_tape_rows(), GREAT: _w_tape_rows()})
    _l5, holed, _c5, _q5, _s5 = _d_run(_d_chain(), qfn=tape)
    assert _st(holed)["cw_order_n"] == 1 and _st(holed)["cw_hop3_verdict"] is None


def test_cw_deep_identity_ok_is_unknown_never_true_on_the_wrapper_belt(monkeypatch):
    """build-refute major-2, MEASURED: the belt seeds payload['deep'] = {'error': True} with NO
    'hops' key, and `all()` over an empty dict is VACUOUSLY TRUE -- so the one state the boolean
    exists to catch projected as clean. Unknown is not True."""
    from leviathan.graphrag import eval as EV

    def _boom(*_a, **_k):
        raise RuntimeError("marker exploded")

    monkeypatch.setattr(cq, "_cw_marker", _boom)
    _l, p, calls, _q, _s = _d_run(_d_chain())
    assert set(p["deep"]) == {"error", "elapsed_ms"} and p["deep"]["error"] is True
    assert "hops" not in p["deep"] and calls == []
    st_ = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p},
                             "structured": None, "answer": ""})
    assert st_["cw_deep_on"] is True                          # the belt carries the REGIME
    assert st_["cw_deep_identity_ok"] is None                 # ...and NOT True
    assert st_["cw_deep_error"] is True                       # the arm bars THIS at zero rows
    assert st_["cw_order_n"] is None and st_["cw_plan_reads"] is None
    # a clean deep row and a walk-less row both keep the boolean, so the column is not None-noise
    monkeypatch.undo()                                        # the marker works again
    _l2, clean, _c2, _q2, _s2 = _d_run(_d_chain())
    assert clean["outcome"] == "fired"
    assert EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": clean},
                              "structured": None, "answer": ""})["cw_deep_identity_ok"] is True
    empty = EV._cascade_stats({"citations": [], "trace": {}, "structured": None, "answer": ""})
    assert empty["cw_deep_identity_ok"] is True and empty["cw_deep_error"] is False


def test_g8s_bar_is_stated_on_quantities_that_can_fail(monkeypatch):
    """build-refute major-4: `cw_plan_reads <= CW_DEEP_CAP` is a THEOREM -- cascade declines 'cap'
    whenever the plan exceeds the cap BEFORE any read, so no row an arm can produce falsifies it.
    The bar is (a) the cap / turn_budget_spent decline census at zero rows and (b) cw_board_reads <=
    cw_plan_reads on every fired row, which CAN fail (the plan is computed before the render loop)."""
    from leviathan.graphrag import eval as EV

    def _st(payload):
        return EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": payload},
                                  "structured": None, "answer": ""})

    fired = [_d_run(_d_chain())[1],
             _d_run(_d_graph({ROOT: [_w_edge(contract=c) for c in (CHILD, GRAND, GREAT)]}),
                    qfn=_d_tape(ROOT, CHILD, GRAND, GREAT))[1],
             _d_run(_d_chain(great=FREE_LEG), qfn=_d_tape(ROOT, CHILD, GRAND),
                    sg=_w_sg(kept=(GRAND, FREE_LEG)))[1]]
    for payload in fired:
        s = _st(payload)
        assert s["cw_outcome"] == "fired"
        assert s["cw_board_reads"] <= s["cw_plan_reads"]       # THE MEASUREMENT, not the theorem
        assert "cap" not in s["cw_declines"]                   # (a), row by row
        assert "turn_budget_spent" not in s["cw_declines"]
    # ...and the two states (a) counts really are reachable and really do show up in cw_declines
    monkeypatch.setattr(cq, "CW_DEEP_CAP", 0)
    cap = _st(_d_run(_d_chain())[1])
    assert "cap" in cap["cw_declines"] and cap["cw_outcome"] == "declined"
    monkeypatch.undo()
    spent = _st(_d_run(_d_chain(), sg=_w_sg(kept=(GRAND, GREAT),
                                            trace_extra={"quantify_wave_reads": 79}))[1])
    assert "turn_budget_spent" in spent["cw_declines"]
    # the theorem is still TRUE -- it is simply not the bar
    assert _st(_d_run(_d_chain())[1])["cw_plan_reads"] <= cq.CW_DEEP_CAP


def test_deep_and_context_ride_together_and_neither_counts_the_other():
    """build-refute minor: no engine call in this suite carried BOTH keys -- the seam pin asserts the
    REQUEST DICT only. The rectangles close, the context cell is NOT a hop at any level, and the
    board plan the rider measures its slack against is the DEEP plan."""
    from leviathan.graphrag import eval as EV
    g = _d_graph({ROOT: [_w_edge()],
                  CHILD: [_w_edge(seed=CHILD, contract=GRAND, relation="crushed_into")],
                  GRAND: [_w_edge(seed=GRAND, contract=GREAT, relation="crushed_into")]},
                 drivers=("poultry_expansion",))
    tape = _WTape({ROOT: _c_tape_rows(), CHILD: _c_tape_rows(), GRAND: _c_tape_rows(),
                   GREAT: _c_tape_rows(), "chicken_usd_t": _c_pink()})
    sg = _w_sg(windows=[{"start": C_START, "end": C_END, "span": C_SPAN, "n": 20}],
               node="poultry_expansion", kept=(GRAND, GREAT))
    calls: list = []
    lines, p = cq._cascade_walk_leg_or_nothing(
        sg, g, {"focus_contract": ROOT, "deep": True, "context": True}, tape, ASOF_C, calls)
    assert p["outcome"] == "fired" and p["order"] == "third" and p["deep"]["order_n"] == 3
    assert _rect_ok(p)
    # the rider measures its slack against the DEEP board plan, and says so in its own ledger
    assert p["deep"]["cells_planned"] == 4
    assert p["context"]["board_reads_planned"] == 12 == 4 * cq.CW_READS_PER_CELL
    assert p["context"]["rendered"] == 1 and p["context"]["reads"] == 1
    # A CONTEXT CELL IS NOT A HOP: it is in `cells` with kind 'context', in NO hops row, and out of
    # the closed chain the order label walks
    ctx = next(c for c in p["cells"] if c.get("kind") == "context")
    assert ctx["status"] == "closed"
    assert sum(r["declared"] for r in p["deep"]["hops"].values()) == 3     # child + grand + great
    assert all(r["declared"] == r["priced"] for r in p["deep"]["hops"].values())
    assert p["path"] == [ROOT, CHILD, GRAND, GREAT]                       # the context slug is not
    assert ctx.get("slice") not in p["path"]                              #   a path member
    # net_reads carries the rider's read; the BOARD spend does not
    st_ = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p},
                             "structured": None, "answer": ""})
    assert st_["cw_reads"] == p["net_reads"] == 9 and st_["cw_board_reads"] == 8
    assert st_["cw_board_reads"] <= st_["cw_plan_reads"] == 12
    assert st_["cw_context_rendered"] == 1


def test_config_check_banks_the_measured_max_out_degree_and_prints_it(capsys):
    """build-review minor: clause (ix) ERRORs only ABOVE CW_DEEP_MAX_CHILDREN 6 and clause (x) merely
    PRINTED the measured maximum, so a curation edit taking corn_cbot from 4 to 6 would land with no
    red, no WARN and no re-measure -- silently consuming the whole headroom the constant was sized
    on. The banked pair is (4, 'corn_cbot')."""
    from leviathan.graphrag import config_check as cc
    assert cc.check_cascade_walk() == []
    out = capsys.readouterr().out
    assert "Max shipped hop-1 out-degree 4 ('corn_cbot')" in out
    assert "measured max hop-1 out-degree moved" not in out          # the tripwire is silent
    src = open(cc.__file__, encoding="utf-8").read()
    from leviathan.graphrag import config_check as _cc
    assert _cc.CW_MEASURED_MAX_OUT_DEGREE == (4, "corn_cbot")   # by attribute, module scope


def test_the_walk_timer_is_the_one_nondeterministic_field_and_is_documented_as_such():
    """build-review minor: elapsed_ms is a wall clock, so no flag-ON artifact is byte-comparable
    across runs. The sentence belongs where the next artifact comparison will read it."""
    from leviathan.graphrag import eval as EV
    _l, a, _c, _q, _s = _d_run(_d_chain())
    _l2, b, _c2, _q2, _s2 = _d_run(_d_chain())
    assert a["deep"].pop("elapsed_ms") is not None
    assert b["deep"].pop("elapsed_ms") is not None
    assert a == b                                    # equal on EVERY other byte, once popped
    ev_src = open(EV.__file__, encoding="utf-8").read()
    i = ev_src.index('"cw_walk_elapsed_ms": _cw_deep.get("elapsed_ms")')
    assert "POP cw_walk_elapsed_ms" in ev_src[i - 500:i]
    assert "NONDETERMINISTIC" in open(cq.__file__, encoding="utf-8").read()
    # the OFF regime never stamps it, which is why the flag-off golden is byte-stable at all
    _l3, off, _c3, _q3, _s3 = _d_run(_d_chain(), request={"focus_contract": ROOT})
    assert "deep" not in off


# -- G1 AS A SUITE PIN: the flag-off byte-identity gate, re-run against the banked HEAD golden -------
def test_g1_the_flag_off_population_reproduces_the_banked_head_golden():
    """THE FIRST LAW OF THIS BUILD, HELD IN THE SUITE (build-review major L1: G1 was a scratchpad
    script, so the flag-off byte-identity gate on a leg SERVING AT REV 126 did not stand for the next
    builder, for CI, or for the arm).

    It runs data/consequence_leg/v25_golden_bank.py -- which wraps the OUTER
    `_cascade_walk_leg_or_nothing` over every call this whole suite makes -- with
    GRAPHRAG_CASCADE_DEEP unset, and joins the result against
    data/consequence_leg/v25_golden_head_v2.json, banked at HEAD c6868034 BEFORE any engine byte
    moved.

    THE JOIN IS bank_sha256 PLUS PER-KEY CONTENT, RESTRICTED TO THE BANKED (flag-off) KEYS. Never the
    FILE digest: the bank doc embeds pytest's wall-clock tail, so two identical runs give different
    file digests. Never elapsed_ms either -- an off payload has no 'deep' key at all, which this pin
    ASSERTS rather than assumes. The post-build run has MORE keys than the bank (the V2-5 flag-ON
    fixtures); that is expected and is not a failure.

    RECURSION IS CLOSED BY A SENTINEL: the producer exports V25_GOLDEN_INNER=1 into the pytest
    subprocess it spawns, and this pin skips under it."""
    import hashlib
    import json
    import os
    import subprocess
    import sys
    import tempfile

    if os.environ.get("V25_GOLDEN_INNER") == "1":
        pytest.skip("inner golden-bank run -- the producer's own subprocess, never re-entered")
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    bank_path = os.path.join(repo, "data", "consequence_leg", "v25_golden_head_v2.json")
    producer = os.path.join(repo, "data", "consequence_leg", "v25_golden_bank.py")
    assert os.path.exists(bank_path) and os.path.exists(producer)
    out = os.path.join(tempfile.mkdtemp(prefix="v25g1_"), "post.json")
    env = dict(os.environ, V25_GOLDEN_OUT=out)
    env.pop("GRAPHRAG_CASCADE_DEEP", None)                 # THE FLAG IS OFF -- that is the gate
    proc = subprocess.run([sys.executable, producer], cwd=repo, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:]
    old = json.load(open(bank_path, encoding="utf-8"))
    new = json.load(open(out, encoding="utf-8"))
    ob, nb = old["bank"], new["bank"]
    _exit_note = (new.get("pytest_exitstatus"), (new.get("pytest_tail") or "")[-800:])   # diagnostic, asserted LAST
    assert len(ob) == 91
    missing = [k for k in ob if k not in nb]
    assert missing == [], missing
    # PER-KEY CONTENT, field by field, so a failure NAMES the drifted field
    diffs = [(k, f) for k in ob for f in ("lines", "payload", "calls_delta", "raised",
                                          "traced_is_payload", "request", "asof")
             if ob[k].get(f) != nb[k].get(f)]
    assert diffs == [], diffs[:5]
    # NO OFF-REGIME PAYLOAD CARRIES A 'deep' KEY -- on any path, the exception belt included. That
    # is also why "never elapsed_ms" is true here by construction.
    leaks = [k for k, n in nb.items()
             if isinstance(n.get("payload"), dict) and "deep" in n["payload"]
             and not ((n.get("request") or {}).get("deep") or (n.get("request") or {}).get("xccy"))]
    assert leaks == [], leaks
    assert not any("elapsed_ms" in json.dumps(ob[k]) for k in ob)
    # THE SHARPEST FORM: hash the post-build run RESTRICTED to the banked keys with the producer's
    # OWN serialization and compare to the banked whole-bank sha. Equal => byte-identical, not
    # merely field-equal.
    sub = {k: nb[k] for k in ob}
    sub_sha = hashlib.sha256(json.dumps(sub, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()
    assert sub_sha == old["bank_sha256"]
    assert sub_sha == "e0dc1e5dcc2354baa542d1e4e3b96cd4486c7bedec38cc81873ef0c07630f3a6"
    # the nested run's own status is context, not the gate: an unrelated red elsewhere in the walk
    # suite must not fail a test named for the BANK join (post-fix re-review minor 3)
    assert _exit_note[0] == 0, _exit_note[1]


# -- G1d AS A SUITE PIN: the DEEP-ON / XCCY-OFF gate, banked BEFORE the V2-3 cross-currency build --
def test_g1d_the_deep_on_xccy_off_population_reproduces_the_banked_deep_golden():
    """THE SECOND BYTE-IDENTITY LAW (V2-3 law L10). G1 above holds the leg still with the deep flag
    OFF, and is BLIND to the regime V2-3 edits inside: the cross-currency build refactors the three
    budget inequalities into one `_cw_slack` helper, re-collects the hop ledger as a dict keyed by
    _CW_HOP_LEVELS, and threads a new request key through the same selection line. Each of those can
    move a deep-on turn while every flag-off turn stays byte-identical.

    IT JOINS TWO BANKED POPULATIONS, from data/consequence_leg/v23_golden_deep_bank.py:

      bank_native (46 keys) -- the calls the fixtures themselves make with `deep` set, from a GREEN
      run: breadth on four children, the third-order chain, the free cell, the width belt, the hop-3
      verdict rows, the closed rectangle on every root-scope decline.

      bank_forced (140 keys, 100 of them forced) -- every non-xccy call re-asked with deep=True,
      which IS the regime prod takes when GRAPHRAG_CASCADE_DEEP=on: under that flag every served
      turn is a deep turn, the odd shapes included (root declines, the palm free leg, the fenced
      block, the price-replay belt, the exception belt, the context rider). Forcing reds this
      suite's flag-off assertions (15 at HEAD 1085f03d), and a red test stops making calls, so that
      pass is a SUBSET by construction -- which is why the native pass exists to cover the five deep
      calls it truncates away (hop-3 verdict rows, breadth-4).

    XCCY IS EXCLUDED FROM BOTH BANKS BY CONSTRUCTION -- the cross-currency path is the ONE path V2-3
    is allowed to change, and a golden that banked it would be a golden that had to be re-banked,
    which is not a gate. The producer erases payload['deep']['elapsed_ms'] to a KIND TOKEN (never
    pops it), so the comparison is total on every other byte and never on the one wall clock.

    A DIFF IS NOT AUTOMATICALLY A REGRESSION, AND IS NEVER WAVED THROUGH: law L9 deliberately ADDS
    payload['deep']['order_n_rendered'] to this regime. Re-anchor the bank on the (key, field) list
    this pin prints, with the reason written down beside it; never loosen the join.

    THE NATIVE PASS MUST BE GREEN; the forced pass's exitstatus is recorded, not gated (it is red by
    construction). RECURSION IS CLOSED BY THE V2-5 SENTINEL: the producer exports V25_GOLDEN_INNER=1
    and both golden pins skip under it. COST: two suite runs, ~4 minutes, $0, offline, no AWS."""
    import hashlib
    import json
    import os
    import subprocess
    import sys
    import tempfile

    if os.environ.get("V25_GOLDEN_INNER") == "1":
        pytest.skip("inner golden-bank run -- a producer's own subprocess, never re-entered")
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    bank_path = os.path.join(repo, "data", "consequence_leg", "v23_golden_deep_on.json")
    producer = os.path.join(repo, "data", "consequence_leg", "v23_golden_deep_bank.py")
    assert os.path.exists(bank_path) and os.path.exists(producer)
    out = os.path.join(tempfile.mkdtemp(prefix="v23g1d_"), "post.json")
    env = dict(os.environ, V23_GOLDEN_OUT=out)
    env.pop("GRAPHRAG_CASCADE_DEEP", None)      # the REQUEST key carries the regime, never the env:
    env.pop("GRAPHRAG_CASCADE_CONTEXT", None)   # the producer strips GRAPHRAG_* anyway, and these
    #                                             two pops say which reads would have mattered
    proc = subprocess.run([sys.executable, producer], cwd=repo, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:]
    old = json.load(open(bank_path, encoding="utf-8"))
    new = json.load(open(out, encoding="utf-8"))
    _native_exit = (new["native"]["pytest_exitstatus"],
                    (new["native"].get("pytest_tail") or "")[-800:])   # asserted LAST
    # RE-ANCHORED BY THE V2-3 FIX PASS (2026-09-04), on a NAMED single-cause measurement, printed by
    # data/consequence_leg/v23_golden_diff.py against the pre-fix bank:
    #   bank_native  46 -> 49 keys, ZERO field diffs on all 46 carried-over keys (the 3 new keys are
    #                the fix group's own deep calls; a superset is never a diff on this join).
    #   bank_forced 140 -> 143 keys, ONE key changed and TWO dropped, all from ONE test:
    #                test_context_budget_is_subordinate_never_the_block. #0's context cell now
    #                ADMITS where it declined budget_cap -- `_cw_slack` reads the REGIME's ceiling
    #                (80 under the forcing) instead of the bare 60, which is fix 4 itself -- so
    #                context.admitted/reads/rendered 0 -> 1, net_reads 4 -> 5, the ROW-1C line and
    #                its call appear, and the budget_cap decline disappears. #1 and #2 then vanish
    #                because that test's FIRST assertion fails under forcing and a red test stops
    #                making calls: the SUBSET-BY-CONSTRUCTION property this bank's own docstring
    #                declares, not a lost shape (native keeps all three, un-forced and green).
    #   excluded_xccy_keys 1 -> 40: the pre-fix bank predated the V2-3 fixture group, so it recorded
    #                the V2-5 union call alone. The exclusion is measured, never assumed.
    # The producer was run TWICE before re-banking; both runs produced identical section shas.
    for section, n_keys, banked_sha in (
            ("bank_native", 49,
             "d43c743557a64d361340d579ed32cde0bd153fc001923fd1f4d6255e0b1e2065"),
            ("bank_forced", 143,
             "16a040f0371b84eac88ee15e0d2c07de8c5a7b05618f6c99154dd936d4673beb")):
        ob, nb = old[section], new[section]
        assert len(ob) == n_keys, (section, len(ob))
        missing = [k for k in ob if k not in nb]
        assert missing == [], (section, missing)
        # PER-KEY CONTENT, field by field, so a failure NAMES the drifted field
        diffs = [(k, f) for k in ob for f in ("lines", "payload", "calls_delta", "raised",
                                              "forced", "traced_is_payload", "request", "asof")
                 if ob[k].get(f) != nb[k].get(f)]
        assert diffs == [], (section, diffs[:5])
        # EVERY banked call is deep-on and xccy-off -- the population the bank claims to be
        assert all((v.get("request") or {}).get("deep") for v in ob.values())
        assert not any((v.get("request") or {}).get("xccy") for v in ob.values())
        # the wall clock is ERASED, not popped: the field is present on every deep payload and
        # carries the kind token, so a build that stopped stamping it is a diff, not a silence
        assert all(isinstance(v["payload"], dict) and v["payload"]["deep"]["elapsed_ms"]
                   == "__INT_MS__" for v in ob.values())
        # THE SHARPEST FORM: hash the post-build run RESTRICTED to the banked keys with the
        # producer's OWN serialization. Equal => byte-identical, not merely field-equal.
        sub = {k: nb[k] for k in ob}
        sub_sha = hashlib.sha256(json.dumps(sub, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode("utf-8")).hexdigest()
        assert sub_sha == old[section.split("_")[1]]["bank_sha256"], section
        assert sub_sha == banked_sha, section
    # EVERY xccy call in this suite is excluded from both banks BY NAME -- the exclusion is a
    # MEASUREMENT, not an accident: the cross-currency path is the one path V2-3 is allowed to
    # change, and a golden that banked it would be a golden that had to be re-banked. The pre-fix
    # bank named ONE key (it predated the V2-3 fixture group); the fix pass re-measured it at 40.
    _excl = old["native"]["excluded_xccy_keys"]
    assert _excl == old["forced"]["excluded_xccy_keys"] and len(_excl) == 40
    assert all(k.startswith("tests/unit/test_cascade_walk.py::") for k in _excl)
    assert ("tests/unit/test_cascade_walk.py::"
            "test_the_regime_is_the_union_with_v23s_key_and_the_union_is_inert_here#0") in _excl
    # ...and the FRESH run excludes the same population, so a fixture that silently stopped asking
    # for the rider would move this number rather than quietly shrinking the measured lane
    assert new["native"]["excluded_xccy_keys"] == _excl
    # the forced pass is RED BY CONSTRUCTION (it forces the regime onto flag-off fixtures), so its
    # status is context, never the gate; the NATIVE pass is the one that must be green
    assert new["forced"]["pytest_exitstatus"] != 0
    assert _native_exit[0] == 0, _native_exit[1]


# ================================================================================================
# V2-3 CROSS-CURRENCY RIDER (built dark 2026-09-04). THE FIRST LAW IS FLAG-OFF BYTE-IDENTITY -- the
# walk serves live at rev 126 -- and it is held by TWO goldens above (G1 flag-off, G1d deep-on) plus
# the producer pins in this group. Everything below runs the SHIPPED leg on fixtures; nothing here
# touches the substrate.
# ================================================================================================
X_CNY = "rapeseed_oil_zce"          # CNY, coverage floor 2015-10-08
X_CAD = "canola_ice"                # CAD, coverage floor 2018-12-24
X_BRL = "brazilian_arabica_coffee"     # BRL CASH INDEX -- the ordering law's own board
#                                        (campinas_corn_reference_bmf is the OTHER one; it shares
#                                        corn's node, so node_cycle would decline it one rung
#                                        earlier and the ordering law would go untested)


def _x_fx_rows(v0=1.0, v1=1.05, t1="2021-02-15", t2="2021-08-15", unit="CNY per USD"):
    """Daily exchange-rate prints in the MEASURED silver_fred_fx row shape: value + a date under the
    knowledge alias. The rate steps from v0 to v1 halfway through, so last/first - 1 is exact."""
    d, end = _dt.date.fromisoformat(t1), _dt.date.fromisoformat(t2)
    mid = _dt.date.fromisoformat(t1) + (end - _dt.date.fromisoformat(t1)) / 2
    out = []
    while d <= end:
        out.append({"value": (v0 if d <= mid else v1), "knowledge_date": d.isoformat(),
                    "unit": unit})
        d += _dt.timedelta(days=1)
    return out


def _x_graph(children=(X_CNY,), sign="+", **kw):
    return _w_graph([_w_edge(contract=c, sign=sign) for c in children], **kw)


def _x_tape(children=(X_CNY,), fx=None, root_rows=None, child_rows=None):
    rows = {ROOT: root_rows if root_rows is not None else _w_tape_rows()}
    for c in children:
        rows[c] = child_rows if child_rows is not None else _w_tape_rows()
    for metric, frows in (fx or {"cny_usd": _x_fx_rows()}).items():
        rows[metric] = frows
    return _WTape(rows)


def _x_run(children=(X_CNY,), request=None, sg=None, graph=None, qfn=None, calls=None,
           sign="+", fx=None):
    graph = graph if graph is not None else _x_graph(children, sign=sign)
    qfn = qfn if qfn is not None else _x_tape(children, fx=fx)
    req = request if request is not None else {"focus_contract": ROOT, "xccy": True}
    return _w_run(sg=sg, graph=graph, qfn=qfn, calls=calls, request=req)


def _x_ledger(payload):
    return payload.get("xccy") or {}


def _x_fx_cell(payload):
    return next((c for c in payload["cells"] if c.get("kind") == "fx"), None)


def _x_rect(payload):
    """THE FX RECTANGLE, the form that holds on EVERY path including the belts."""
    x = _x_ledger(payload)
    return (int(x.get("fx_planned") or 0)
            == int(x.get("fx_rendered") or 0) + int(x.get("fx_cache_hits") or 0)
            + len(x.get("declines") or []))


# -- CONSTANTS, VOCABULARY, ONE PRODUCER -------------------------------------------------------------
def test_v23_constants_and_one_producer_pins():
    from leviathan.graphrag import answer as ans
    src = open(cq.__file__, encoding="utf-8").read()
    assert cq.CW_XCCY_USD == "USD"
    assert cq.CW_FX_CAP == 3 and cq.CW_FX_CAP <= cq.CW_DEEP_MAX_CHILDREN
    assert cq.CW_FX_READS_PER_CELL == 1 and cq.CW_FX_MIN_OBS >= 2
    assert cq.CW_FX_TOKEN.startswith("] ") and src.count(cq.CW_FX_TOKEN) == 1
    assert cq.CW_FX_TOKEN not in open(ans.__file__, encoding="utf-8").read()
    assert cq.CW_XCCY_CLAUSE.startswith(cq.CW_XCCY_CLAUSE_MARK)
    # the LINT-ONLY regex: it matches the producer's own row and NOT a retrieved bracketed heading
    assert cq.CW_FX_LINE_RX.search("- [N7] EXCHANGE RATE euros per US dollar measured on") is not None
    assert cq.CW_FX_LINE_RX.search("- [1] EXCHANGE RATE TABLE for the quarter") is None
    # the shipped knobs the rider does NOT move
    assert cq.CW_CONTEXT_CAP == cq.CW_MAX_FIRINGS == 2 and cq.CW_TURN_CEILING == 60
    assert cq.CW_DEEP_MAX_CHILDREN == 6 and cq.CW_DEEP_CAP == 27
    # the pre-admit tuple is the rectangle's own vocabulary, and it is a SUBSET of the full one
    assert set(cq._CW_FX_PRE_ADMIT) <= set(cq._CW_FX_DECLINES)
    # V2-3 FIX PASS: 'cache_declined' is rung 2's ZERO-READ arm and therefore PRE-ADMIT (it takes
    # the cache hit's place in the first rectangle); 'block_fenced' is a BELT TRIP on cells that
    # WERE admitted and paid, so it joins the full tuple only -- counting it pre-admit would double
    # them. Both directions are what keeps the two rectangles closable from the artifact alone.
    # fix re-review major 1: 'read_error' is the POST-read name (a paid read that came back
    # status=error) and is NOT pre-admit; rungs 6/6b carry their own pre-read names.
    assert set(cq._CW_FX_PRE_ADMIT) == {"replay", "fx_cap", "budget_cap", "no_card", "no_metric",
                                        "cache_declined"}
    assert "read_error" in cq._CW_FX_DECLINES and "read_error" not in cq._CW_FX_PRE_ADMIT
    assert "block_fenced" in cq._CW_FX_DECLINES and "block_fenced" not in cq._CW_FX_PRE_ADMIT


def test_v23_words_are_words_and_the_maps_agree_with_the_boards():
    from leviathan.graphrag import display as dp
    from leviathan.graphrag import register as reg
    from leviathan.silver import futures_eod_contracts as FC
    # owner decision #5, DECLARED BLAST RADIUS: silver_fred_fx is already a live citing surface, so
    # every existing FX citation takes this label too. The card attributes the data to the ECB.
    assert dp.table_label("silver_fred_fx") == "ECB reference rates"
    board_ccy = {(FC.CONTRACT_MAP.get(s) or {}).get("currency") for s in cq._CW_BOARD_LABEL}
    assert set(cq._CW_CURRENCY_WORD) == {c for c in board_ccy if c}
    assert set(cq._CW_CURRENCY_WORD) == {"USD", "CNY", "CAD", "EUR", "ZAR"}
    assert set(cq._CW_FX_CROSS) == set(cq._CW_CURRENCY_WORD) - {"USD"}
    for c, w in cq._CW_CURRENCY_WORD.items():
        assert w and all(ch.isalpha() or ch == " " for ch in w) and not reg.internal_leaks(w)
        assert cq._cw_currency_words(c) == w
    assert cq._cw_currency_words(None) == "" and cq._cw_currency_words("BRL") == ""
    # no metric is a fixed-lag change column (the wrong-clock ban)
    assert not any(m.endswith("_pct_change_90d") for (m, _l) in cq._CW_FX_CROSS.values())


def test_v23_absence_vocabulary_is_observation_words_only():
    from leviathan.graphrag import register as reg
    for reason in ("cross_currency_no_pair_rate", "cross_currency_unmapped", "cash_index_board",
                   "fx_flips_sign"):
        why = cq._CW_ABSENCE_WHY[reason]
        line = cq._cw_absence("CBOT corn", reason)
        assert not any(ch.isdigit() for ch in why)
        assert cq.pace_register_ok(line) and reg.count_valuation_words(line) == 0
        assert reg.count_flow_words(line) == 0 and not reg.internal_leaks(line)
    assert "cross_currency" in cq._CW_ABSENCE_WHY          # the flag-off reason is RE-SCOPED, not deleted


# -- THE PURE HELPERS ---------------------------------------------------------------------------------
def test_cw_fx_metric_truth_table():
    assert cq._cw_fx_metric("USD", "CNY") == ("cny_usd", "Chinese yuan per US dollar")
    assert cq._cw_fx_metric("CNY", "USD") == ("cny_usd", "Chinese yuan per US dollar")
    assert cq._cw_fx_metric("USD", "USD") is None          # equal -> not a cross
    assert cq._cw_fx_metric("CNY", "CAD") is None          # NEITHER side USD -> never constructed
    assert cq._cw_fx_metric("CAD", "EUR") is None
    assert cq._cw_fx_metric(None, "CNY") is None and cq._cw_fx_metric("USD", "") is None
    assert cq._cw_fx_metric("USD", "BRL") is None          # no card column -> no pair rate


def test_cw_cash_index_refuses_on_the_unknown():
    assert cq._cw_cash_index(X_BRL) is True
    assert cq._cw_cash_index("campinas_corn_reference_bmf") is True
    assert cq._cw_cash_index(ROOT) is False and cq._cw_cash_index(X_CNY) is False
    assert cq._cw_cash_index("not_a_board_at_all") is True   # unknown -> REFUSE


# -- THE ADMISSION LADDER: ORDER IS LOAD-BEARING ------------------------------------------------------
def test_the_ladder_is_the_pre_rider_bytes_with_the_flag_off():
    from leviathan.silver import futures_eod_contracts as FC
    g = _x_graph((X_CNY,))
    adm, dec, rd = cq._cw_admissible_children(g, FC.PRICE_COVERAGE_START, g.contract_node, ROOT)
    assert rd is None and adm == []
    assert dec == [{"scope": "child", "reason": "cross_currency", "child": X_CNY}]


def test_the_ladder_admits_the_cross_and_carries_its_pair_rate():
    from leviathan.silver import futures_eod_contracts as FC
    g = _x_graph((X_CNY,))
    adm, dec, rd = cq._cw_admissible_children(g, FC.PRICE_COVERAGE_START, g.contract_node, ROOT,
                                              xccy=True)
    assert rd is None and dec == [] and len(adm) == 1
    assert adm[0]["xccy"] == ("USD", "CNY")
    assert adm[0]["fx"] == ("cny_usd", "Chinese yuan per US dollar")
    # a SAME-currency child carries None on both keys, which is what makes every downstream
    # predicate inert by construction rather than by argument
    g2 = _w_graph([_w_edge()])
    adm2, _d2, _r2 = cq._cw_admissible_children(g2, FC.PRICE_COVERAGE_START, g2.contract_node,
                                                ROOT, xccy=True)
    assert adm2[0]["xccy"] is None and adm2[0]["fx"] is None


def test_the_cash_index_test_comes_before_the_fx_column_test():
    """F1's ORDERING LAW, held two ways. (a) SOURCE: the cash-index branch precedes the FX-column
    branch inside the ladder. (b) BEHAVIOUR: with a BRL column FORCED onto the map -- the only way
    the two orders can disagree, since BRL has no real column -- the cash-index reason still wins."""
    import inspect

    from leviathan.silver import futures_eod_contracts as FC
    src = inspect.getsource(cq._cw_admissible_children)
    assert src.index("_cw_cash_index(child)") < src.index("_cw_fx_metric(cur_r, cur_c)")
    g = _x_graph((X_BRL,))
    cov = dict(FC.PRICE_COVERAGE_START)
    _adm, dec, _rd = cq._cw_admissible_children(g, cov, g.contract_node, ROOT, xccy=True)
    assert dec == [{"scope": "child", "reason": "cash_index_board", "child": X_BRL}]


def test_the_ladder_names_the_missing_pair_rate_and_the_missing_currency(monkeypatch):
    from leviathan.silver import futures_eod_contracts as FC
    g = _x_graph((X_CNY,))
    monkeypatch.setattr(cq, "_CW_FX_CROSS", {})            # no column for ANY cross
    _adm, dec, _rd = cq._cw_admissible_children(g, FC.PRICE_COVERAGE_START, g.contract_node, ROOT,
                                                xccy=True)
    assert dec == [{"scope": "child", "reason": "cross_currency_no_pair_rate", "child": X_CNY}]
    monkeypatch.setattr(cq, "_cw_currency", lambda s: (None if s == X_CNY else "USD"))
    _a2, dec2, _r2 = cq._cw_admissible_children(g, FC.PRICE_COVERAGE_START, g.contract_node, ROOT,
                                                xccy=True)
    assert dec2 == [{"scope": "child", "reason": "cross_currency_unmapped", "child": X_CNY}]


def test_k0_admission_numbers_on_the_live_graph():
    """K0 as a BUILD-STOP number, recomputed from the SHIPPED ladder against the LIVE graph -- a
    curation change that moves a count fails the build rather than drifting."""
    from leviathan.graphrag import graph as G
    from leviathan.silver import futures_eod_contracts as FC
    g = G.CausalGraph.load()
    cov, node = FC.PRICE_COVERAGE_START, g.contract_node
    roots = sorted({str(r.get("seed")) for nd in g.rev_cross_link_seeds()
                    for r in g.rev_cross_links(nd)})
    base = on = 0
    reasons: dict = {}
    for r in roots:
        if r not in cov or r not in cq._CW_BOARD_LABEL:
            continue
        a_off, _d_off, rd_off = cq._cw_admissible_children(g, cov, node, r)
        a_on, d_on, rd_on = cq._cw_admissible_children(g, cov, node, r, xccy=True)
        base += len(a_off) if rd_off is None else 0
        if rd_on is None:
            on += len(a_on)
            for d in d_on:
                reasons.setdefault(d["reason"], []).append(f"{r}->{d['child']}")
    assert (base, on, on - base) == (23, 45, 22)
    assert sorted(reasons.get("cross_currency_no_pair_rate") or []) == [
        "canola_ice->french_rapeseed_matif", "canola_ice->rapeseed_meal_zce",
        "french_rapeseed_matif->canola_ice", "rapeseed_meal_zce->french_rapeseed_matif",
        "rapeseed_oil_zce->french_rapeseed_matif"]
    assert sorted(reasons.get("cash_index_board") or []) == [
        "robusta_coffee->brazilian_arabica_coffee", "soybeans_cbot->campinas_corn_reference_bmf"]
    assert reasons.get("cross_currency_unmapped") is None   # MEASURED UNREACHABLE, kept as a belt
    assert "south_african_yellow_maize_jse" in cq._CW_BOARD_LABEL     # the COUPLED label row


# -- THE ENGINE ENFORCES xccy => deep ------------------------------------------------------------------
def test_the_engine_enforces_xccy_implies_deep():
    """v3 refute major-3: the implication used to live only at the answer.py seam, so ANY request
    built without that seam -- a unit fixture, a future caller -- would run the rider at the narrow
    constants and drop lifted children with no decline naming the loss."""
    src = open(cq.__file__, encoding="utf-8").read()
    assert ('deep_on = bool((walk_request or {}).get("deep") '
            'or (walk_request or {}).get("xccy"))') in src
    _l, p, _c, _q, _s = _x_run(request={"focus_contract": ROOT, "xccy": True})
    assert p["deep"]["max_children"] == cq.CW_DEEP_MAX_CHILDREN == 6
    assert p["deep"]["cap"] == cq.CW_DEEP_CAP == 27 and p["deep"]["ceiling"] == 80
    assert "xccy" in p                                     # ...and the rider's own ledger is stamped


# -- FLAG-OFF BYTE IDENTITY ------------------------------------------------------------------------
def test_v23_producers_are_byte_identical_with_the_keyword_defaults():
    hop = cq._cw_hop_header("CBOT corn", "CBOT srw wheat", ["compete for the same demand"],
                            "b", "heat")
    assert hop == cq._cw_hop_header("CBOT corn", "CBOT srw wheat",
                                    ["compete for the same demand"], "b", "heat", xccy=None)
    assert hop.endswith("the rows for this hop.") and cq.CW_XCCY_CLAUSE_MARK not in hop
    for v in ("aligned", "at_odds", "undetermined"):
        line = cq._cw_verdict_line("CBOT corn", "CBOT srw wheat", v)
        assert line == cq._cw_verdict_line("CBOT corn", "CBOT srw wheat", v, xccy=None, reason=None)
        assert line.endswith("never extended beyond it.")
        assert "settlement currency" not in line and "exchange-rate" not in line
    assert cq._cw_marker("first") == _PLAIN_MARKER == cq._cw_marker("first", fx=False)
    assert cq._cw_marker("first", context=True) == cq._cw_marker("first", context=True, fx=False)
    assert "EXCHANGE RATE" not in cq._cw_marker("first", context=True)


def test_v23_flag_off_leg_carries_no_ledger_and_no_fx_cell():
    lines, payload, calls, qfn, _s = _w_run()
    assert "xccy" not in payload and payload["outcome"] == "fired"
    assert not any(c.get("kind") == "fx" for c in payload["cells"])
    assert not any(cq.CW_FX_TOKEN in ln or cq.CW_XCCY_CLAUSE_MARK in ln for ln in lines)
    assert not any("fred_fx" in (s or "") for s in qfn.sql)


# -- THE FX ADMISSION LADDER, RUNG BY RUNG -----------------------------------------------------------
def test_the_fx_entry_rung_never_fires_on_a_same_currency_hop():
    """RUNG 1. Without it BELT A ran on every closed SAME-currency child too, where the record's
    `fx` is None, and would have minted an FX record on a None metric."""
    _l, p, _c, qfn, _s = _w_run(request={"focus_contract": ROOT, "xccy": True})
    x = _x_ledger(p)
    assert p["outcome"] == "fired" and x["fx_planned"] == 0 and x["rendered"] == 0
    assert x["fx_admitted"] == 0 and x["declines"] == [] and x["pairs"] == []
    assert _x_fx_cell(p) is None and not any("fred_fx" in (s or "") for s in qfn.sql)
    assert _x_rect(p)


def test_the_cross_currency_hop_prices_the_rate_once_and_renders_both_rows():
    lines, p, calls, qfn, _s = _x_run()
    x = _x_ledger(p)
    assert p["outcome"] == "fired" and x["rendered"] == 1 and x["pairs"] == ["USD>CNY"]
    assert x["fx_planned"] == x["fx_admitted"] == x["fx_rendered"] == x["fx_reads"] == 1
    assert x["fx_cache_hits"] == 0 and x["declines"] == [] and _x_rect(p)
    rec = _x_fx_cell(p)
    assert rec["status"] == "closed" and rec["metric"] == "cny_usd" and rec["reads"] == 1
    assert rec["move_pct"] == 5.0 and rec["cross"] == "USD>CNY"
    row = next(ln for ln in lines if cq.CW_FX_TOKEN in ln)
    assert "Chinese yuan per US dollar" in row and "+5 %" in row and W_SPAN in row
    assert "ECB reference rates" in row                        # the display label rides the tag
    words = next(ln for ln in lines if ln.startswith(cq.CW_FX_WORDS_PREFIX))
    assert "Chinese yuan" in words and "US dollars" in words and "CNY" not in words
    assert not any(ch.isdigit() for ch in words)
    # the HOP header and the READ line both name the two currencies, unconditionally
    hop = next(ln for ln in lines if ln.startswith("CONSEQUENCE HOP"))
    assert cq.CW_XCCY_CLAUSE_MARK in hop and "US dollars and Chinese yuan" in hop
    read = next(ln for ln in lines if ln.startswith("CONSEQUENCE READ"))
    assert "exchange-rate move between US dollars and Chinese yuan" in read
    # ...and the WHOLE block still passes the register fence, one clock per ROW-1
    assert cq._cw_register_fence(lines)
    assert lines[-1] == cq._cw_marker(p["order"], fx=True) and "EXCHANGE RATE" in lines[-1]
    assert len(calls) == 3                                     # root + child + the rate


def test_the_fx_cache_pays_once_per_cross_per_turn():
    """RUNG 2. Two children on ONE cross would otherwise burn two of the three FX admissions and
    render the same rate twice under two handles."""
    kids = (X_CNY, "rapeseed_meal_zce")
    lines, p, calls, qfn, _s = _x_run(children=kids)
    x = _x_ledger(p)
    assert p["outcome"] == "fired" and x["rendered"] == 2 and x["pairs"] == ["USD>CNY", "USD>CNY"]
    assert x["fx_planned"] == 2 and x["fx_admitted"] == 1 and x["fx_cache_hits"] == 1
    assert x["fx_rendered"] == 1 and x["fx_reads"] == 1 and _x_rect(p)
    assert sum(1 for ln in lines if cq.CW_FX_TOKEN in ln) == 1        # ONE row, ONE handle
    assert sum(1 for s in qfn.sql if "cny_usd" in (s or "")) == 1
    # the cached hop adds NO second words line: the rate is already on the page under its handle
    assert sum(1 for ln in lines if ln.startswith(cq.CW_FX_WORDS_PREFIX)) == 1
    assert sum(1 for ln in lines if cq.CW_XCCY_CLAUSE_MARK in ln) == 2   # both hops name both


def test_the_replay_rung_declines_at_zero_reads():
    lines, p, _c, qfn, _s = _x_run(request={"focus_contract": ROOT, "xccy": True, "replay": True})
    x = _x_ledger(p)
    assert x["fx_planned"] == 1 and x["fx_admitted"] == 0 and x["fx_reads"] == 0
    assert x["declines"] == [{"cross": "USD>CNY", "span": W_SPAN, "reason": "replay"}]
    assert not any("cny_usd" in (s or "") for s in qfn.sql) and _x_rect(p)
    # the WORDS still ride, free, and say plainly that the rate is not priced here
    words = next(ln for ln in lines if ln.startswith(cq.CW_FX_WORDS_PREFIX))
    assert "not priced on this page" in words and cq._cw_register_fence(lines)


def test_the_fx_cap_rung_binds_on_distinct_crosses(monkeypatch):
    monkeypatch.setattr(cq, "CW_FX_CAP", 1)
    fx = {"cny_usd": _x_fx_rows(), "cad_usd": _x_fx_rows(v1=1.10, unit="CAD per USD")}
    lines, p, _c, _q, _s = _x_run(children=(X_CAD, X_CNY), fx=fx)
    x = _x_ledger(p)
    assert x["cap"] == 1 and x["fx_planned"] == 2 and x["fx_admitted"] == 1
    assert [d["reason"] for d in x["declines"]] == ["fx_cap"]
    assert sum(1 for ln in lines if cq.CW_FX_TOKEN in ln) == 1 and _x_rect(p)


def test_the_budget_rung_calls_the_one_slack_helper():
    """RUNG 5 / L3: the FX cell and the V2-1 context cell now see EACH OTHER's admissions. The
    board plan here is 2 cells x 3 reads = 6, so a wave spend of (the REGIME's ceiling) - 6 leaves
    ZERO slack and the FX cell declines budget_cap -- at zero FX reads, with the block still
    shipping.

    RE-ANCHORED ON THE V2-3 FIX PASS: the boundary is CW_DEEP_TURN_CEILING, not CW_TURN_CEILING,
    because `xccy` implies `deep` and `_cw_slack` now budgets against the regime's OWN ceiling --
    the same number the board plan two lines above it was admitted against. The old bare-60 form
    made the 7 rider reads CW_DEEP_TURN_CEILING reserves structurally unreachable. The SHAPE of the
    pin is unchanged: one read short of the ceiling declines, one read of slack admits."""
    _ceil = cq.CW_DEEP_TURN_CEILING
    assert _ceil == 80 and cq.CW_TURN_CEILING == 60      # the boundary really is the deep one
    tight = _w_sg(trace_extra={"quantify_wave_reads": _ceil - 6})
    lines, p, _c, qfn, _s = _x_run(sg=tight)
    x = _x_ledger(p)
    assert p["outcome"] == "fired" and x["fx_admitted"] == 0 and x["fx_reads"] == 0
    assert [d["reason"] for d in x["declines"]] == ["budget_cap"] and _x_rect(p)
    assert not any("cny_usd" in (s or "") for s in qfn.sql)
    slack = _w_sg(trace_extra={"quantify_wave_reads": _ceil - 7})
    _l2, p2, _c2, _q2, _s2 = _x_run(sg=slack)
    assert _x_ledger(p2)["fx_admitted"] == 1 and _x_ledger(p2)["fx_reads"] == 1
    # ...and the OLD boundary now ADMITS, which is the whole point of the fix: a spend that left
    # zero slack against the bare 60 leaves 20 against the regime's own 80.
    old = _w_sg(trace_extra={"quantify_wave_reads": cq.CW_TURN_CEILING - 6})
    _l3, p3, _c3, _q3, _s3 = _x_run(sg=old)
    assert _x_ledger(p3)["fx_admitted"] == 1 and _x_ledger(p3)["declines"] == []


def test_the_read_error_rung_declines_an_unreadable_card(monkeypatch):
    monkeypatch.setattr(cq, "_registry", lambda: (_ for _ in ()).throw(RuntimeError("no card")))
    lines, p, _c, qfn, _s = _x_run()
    x = _x_ledger(p)
    assert p["outcome"] == "fired" and [d["reason"] for d in x["declines"]] == ["no_card"]
    assert x["fx_reads"] == 0 and not any("cny_usd" in (s or "") for s in qfn.sql)
    assert _x_rect(p)


def test_a_raising_fx_read_leaves_the_child_row_intact_and_never_leaks_a_record(monkeypatch):
    """BELT A + the v3 refute's leaked-name class. A raise on the SECOND hop's FX read must not
    leave the FIRST hop's rate bound: `fxrec` is set to None immediately before the try."""
    _real = cq._cw_fx_cell

    def _boom(qfn, rec, *a, **kw):
        if rec["metric"] == "cny_usd":       # the SECOND hop, alphabetically
            raise RuntimeError("fx cell exploded")
        return _real(qfn, rec, *a, **kw)

    monkeypatch.setattr(cq, "_cw_fx_cell", _boom)
    rows = {ROOT: _w_tape_rows(), X_CNY: _w_tape_rows(), X_CAD: _w_tape_rows(),
            "cny_usd": _x_fx_rows(), "cad_usd": _x_fx_rows(unit="CAD per USD")}
    lines, p, calls, _q, _s = _x_run(children=(X_CAD, X_CNY), qfn=_WTape(rows),
                                     graph=_x_graph((X_CAD, X_CNY)))
    x = _x_ledger(p)
    assert p["outcome"] == "fired"
    assert [d["reason"] for d in x["declines"]] == ["error"]
    assert [d["cross"] for d in x["declines"]] == ["USD>CNY"] and _x_rect(p)
    # BOTH children still carry their ROW-1, their [N] handle and their verdict -- BELT A appends
    # nothing, so a raise inside it can orphan nothing (the D2 class)
    for kid in (X_CAD, X_CNY):
        cell = next(c for c in p["cells"] if c.get("slug") == kid)
        assert cell["status"] == "closed" and cell["handle"] and cell["verdict"]
    # THE LEAK PIN: the CAD rate closed and rendered, and the CNY hop did NOT inherit it -- its OWN
    # record declined by name, it holds NO flip input, and that population is COUNTED.
    cad = next(c for c in p["cells"] if c.get("kind") == "fx" and c.get("cross") == "USD>CAD")
    cny = next(c for c in p["cells"] if c.get("kind") == "fx" and c.get("cross") == "USD>CNY")
    assert cad["status"] == "closed" and cad.get("handle") and x["fx_rendered"] == 1
    assert cny["status"] == "declined" and cny["reason"] == "error" and "handle" not in cny
    assert x["fx_unpriced_verdicts"] == 1 and x["fx_gate_checked"] == 1
    assert cq._cw_register_fence(lines)


# -- THE DOMINANCE GATE ------------------------------------------------------------------------------
def test_the_gate_fires_only_when_the_rate_moved_further_AND_the_same_way():
    """L4 / v3's M1. MEASURED on 142 verdictable cross window-pairs: the co-signed predicate fires
    4 times and matches the redenominated truth 142 of 142; the bare magnitude test fires 20, of
    which 16 are false positives -- about one verdict in seven thrown away for nothing."""
    # the board legs both move +15 %; a +20 % rate is LARGER and CO-SIGNED -> the sign flips under a
    # common denomination, so the record declines to read a direction
    fx_up = {"cny_usd": _x_fx_rows(v0=1.0, v1=1.20)}
    lines, p, _c, _q, _s = _x_run(fx=fx_up)
    x = _x_ledger(p)
    kid = next(c for c in p["cells"] if c.get("slug") == X_CNY)
    assert kid["verdict"] == "undetermined" and kid["verdict_reason"] == "fx_flips_sign"
    assert x["fx_flips_sign"] == 1 and x["fx_gate_checked"] == 1 and x["fx_unpriced_verdicts"] == 0
    read = next(ln for ln in lines if ln.startswith("CONSEQUENCE READ"))
    assert "moved further over this window" in read and "it moved the same way" in read
    # ...and the line does NOT then claim a direction WAS read (v3 refute major-5)
    assert "the direction is read on each board" not in read
    assert "stays a move inside its own settlement currency" in read
    assert cq._cw_register_fence(lines)
    # a LARGER but OPPOSITELY SIGNED rate does NOT fire -- v2's predicate would have stripped it
    fx_dn = {"cny_usd": _x_fx_rows(v0=1.20, v1=1.0)}
    _l2, p2, _c2, _q2, _s2 = _x_run(fx=fx_dn)
    kid2 = next(c for c in p2["cells"] if c.get("slug") == X_CNY)
    assert kid2["verdict"] == "aligned" and "verdict_reason" not in kid2
    assert _x_ledger(p2)["fx_flips_sign"] == 0 and _x_ledger(p2)["fx_gate_checked"] == 1
    # a SMALLER co-signed rate does not fire either
    fx_sm = {"cny_usd": _x_fx_rows(v0=1.0, v1=1.02)}
    _l3, p3, _c3, _q3, _s3 = _x_run(fx=fx_sm)
    assert _x_ledger(p3)["fx_flips_sign"] == 0


def test_the_non_usd_leg_is_read_from_the_admissible_record_never_a_loop_variable():
    """The MINOR's fix, held behaviourally: with the ROOT on the non-USD side the gate must compare
    the rate against the PARENT record, not the child's. Same numbers, mirrored roles."""
    import inspect
    src = inspect.getsource(cq._cascade_walk_legs)
    assert '_nonusd = (parent_rec if (_x and _x[0] != CW_XCCY_USD) else crec)' in src
    assert "cur_r" not in src                              # the leaked loop name is not in the leg


def test_an_fx_declined_hop_still_verdicts_and_the_population_is_counted():
    """Owner decision #4, DECLARED: the sign test is currency-free by construction, so a hop whose
    FX cell declined still verdicts -- and `fx_unpriced_verdicts` makes that population readable
    from every artifact row."""
    _l, p, _c, _q, _s = _x_run(request={"focus_contract": ROOT, "xccy": True, "replay": True})
    x = _x_ledger(p)
    kid = next(c for c in p["cells"] if c.get("slug") == X_CNY)
    assert kid["verdict"] == "aligned" and "verdict_reason" not in kid
    assert x["fx_unpriced_verdicts"] == 1 and x["fx_gate_checked"] == 0


# -- M7: THE CLAUSE EXISTS ONLY ON A CLOSED CELL -------------------------------------------------------
def test_a_declining_lifted_child_gets_the_plain_header_and_no_seam_literal(monkeypatch):
    rows = {ROOT: _w_tape_rows(), "cny_usd": _x_fx_rows()}        # the CHILD tape is EMPTY -> declines
    lines, p, _c, qfn, _s = _x_run(qfn=_WTape(rows))
    x = _x_ledger(p)
    hop = next(ln for ln in lines if ln.startswith("CONSEQUENCE HOP"))
    assert cq.CW_XCCY_CLAUSE_MARK not in hop and hop.endswith("the rows for this hop.")
    assert any(ln.startswith("CONSEQUENCE ABSENCE") for ln in lines)
    assert x["rendered"] == 0 and x["fx_planned"] == 0 and _x_rect(p)
    assert not any("cny_usd" in (s or "") for s in qfn.sql)      # no rate for a hop with no figure
    from leviathan.graphrag import answer as ans
    monkeypatch.setenv("GRAPHRAG_CASCADE_XCCY", "on")
    monkeypatch.setenv("GRAPHRAG_CASCADE_WALK", "on")
    assert ans._cascade_xccy_block_on("\n".join(lines)) is False


def test_the_xccy_seam_gate_needs_all_three_legs(monkeypatch):
    from leviathan.graphrag import answer as ans
    monkeypatch.setenv("GRAPHRAG_CASCADE_WALK", "on")
    monkeypatch.setenv("GRAPHRAG_CASCADE_XCCY", "on")
    vp_full = cq.CW_MARKER_PREFIX + "first order): x" + cq.CW_XCCY_CLAUSE_MARK
    assert ans._cascade_xccy_block_on(vp_full) is True
    assert ans._cascade_xccy_block_on(cq.CW_MARKER_PREFIX + "first order): x") is False  # no clause
    assert ans._cascade_xccy_block_on(cq.CW_XCCY_CLAUSE_MARK) is False                   # no walk block
    monkeypatch.delenv("GRAPHRAG_CASCADE_XCCY")
    assert ans._cascade_xccy_block_on(vp_full) is False
    # the gate keys on the CLAUSE MARK, never on the row regex -- a words-only hop has no row
    import inspect
    gsrc = inspect.getsource(ans._cascade_xccy_block_on)
    body = gsrc.split(chr(34) * 3)[-1]                 # past the docstring, which NAMES the regex
    #                                                    it deliberately does not use
    assert "_cq.CW_XCCY_CLAUSE_MARK in (volatile_prompt" in body
    assert "CW_FX_LINE_RX" not in body and "CW_FX_LINE_RX" in gsrc


# -- L1: THE REPLAY HOIST ------------------------------------------------------------------------------
def test_the_replay_key_rides_the_rider_union_not_the_context_branch(monkeypatch):
    """L1, the sharpest defect in the lane: nested under context, the replay bool was DEAD on
    exactly the flip shape (xccy on, context off), so a price_replay turn would have read
    fill-forward backfilled exchange-rate rows that did not exist at the replayed as-of."""
    from leviathan.graphrag import answer as ans
    monkeypatch.delenv("GRAPHRAG_CASCADE_CONTEXT", raising=False)
    monkeypatch.delenv("GRAPHRAG_CASCADE_DEEP", raising=False)
    monkeypatch.setenv("GRAPHRAG_CASCADE_XCCY", "on")
    assert ans._cascade_xccy_on() is True and ans._cascade_context_on() is False
    _pr_kw = {"price_replay": True}                      # the seam's own already-resolved bool
    req = {"focus_contract": ROOT}
    if ans._cascade_context_on():
        req["context"] = True
    if ans._cascade_xccy_on():
        req["xccy"] = True
    if ans._cascade_xccy_on() or ans._cascade_deep_on():
        req["deep"] = True
    if _pr_kw and (ans._cascade_context_on() or ans._cascade_xccy_on() or ans._cascade_deep_on()):
        req["replay"] = True
    assert req == {"focus_contract": ROOT, "xccy": True, "deep": True, "replay": True}
    _l, p, _c, qfn, _s = _x_run(request=req)
    assert [d["reason"] for d in _x_ledger(p)["declines"]] == ["replay"]
    assert not any("fred_fx" in (s or "") for s in qfn.sql)      # ZERO reads on the FX table
    # ...and with every rider off the request is the shipped dict, key for key
    monkeypatch.delenv("GRAPHRAG_CASCADE_XCCY")
    req2 = {"focus_contract": ROOT}
    if ans._cascade_context_on():
        req2["context"] = True
    if ans._cascade_xccy_on():
        req2["xccy"] = True
    if ans._cascade_xccy_on() or ans._cascade_deep_on():
        req2["deep"] = True
    if _pr_kw and (ans._cascade_context_on() or ans._cascade_xccy_on() or ans._cascade_deep_on()):
        req2["replay"] = True
    assert req2 == {"focus_contract": ROOT}


# -- L5: THE LIFTED CHILDREN RIDE THE FIRST FIRING -----------------------------------------------------
def test_lifted_children_ride_the_first_firing_and_the_spine_rides_both():
    """L5, MEASURED as the only zero-loss configuration: riding EVERY firing re-creates the very
    second-window loss the switch exists to stop, and declining by name costs two reachable hops."""
    win2 = [{"start": C_START, "end": C_END, "span": C_SPAN, "n": 20},
            {"start": "2025-06-01", "end": "2025-12-20", "span": "2025-06..2025-12", "n": 9}]
    steps = ("2025-06-01", C_START)
    rows = {ROOT: _c_tape_rows(steps), CHILD: _c_tape_rows(steps), X_CNY: _c_tape_rows(steps),
            "cny_usd": _x_fx_rows(t1="2025-01-01", t2="2026-10-01")}
    g = _w_graph([_w_edge(contract=CHILD), _w_edge(contract=X_CNY)])
    calls: list = []
    lines, p = cq._cascade_walk_leg_or_nothing(_w_sg(windows=win2), g,
                                               {"focus_contract": ROOT, "xccy": True},
                                               _WTape(rows), ASOF_C, calls)
    assert p["outcome"] == "fired" and len(p["firings"]) == 2      # the SECOND window survives
    same = [ln for ln in lines if "CBOT srw wheat" in ln and ln.startswith("CONSEQUENCE HOP")]
    lift = [ln for ln in lines if "ZCE rapeseed oil" in ln and ln.startswith("CONSEQUENCE HOP")]
    assert len(same) == 2 and len(lift) == 1                       # spine both, lifted first only
    assert _x_ledger(p)["rendered"] == 1 and _x_ledger(p)["fx_reads"] == 1
    # the PLAN counts what the loop renders: firing 1 = root + 2 kids, firing 2 = root + 1 kid
    assert p["deep"]["cells_planned"] == p["deep"]["paid_cells"] == 5
    assert p["net_reads"] == 5 * 2 + 1                          # 2 reads per closed cell + 1 rate
    assert cq._cw_register_fence(lines)


# -- L9: THE HOP-LEG DICT AND THE RENDERED ORDER -------------------------------------------------------
def test_the_hop_legs_are_one_dict_and_the_rendered_order_is_stamped():
    src = open(cq.__file__, encoding="utf-8").read()
    assert "hop_legs: dict = {L: None for L in _CW_HOP_LEVELS}" in src
    assert "hop_legs[_lvl] = _hop" in src
    assert "zip(_CW_HOP_LEVELS, (grand, great))" not in src        # the re-spelled tuple is GONE
    assert '"great" if a is great else' not in src                 # ...and so is the dispatch chain
    _l, p, _c, _q, _s = _d_run(_d_chain(), qfn=_d_tape(ROOT, CHILD, GRAND, GREAT),
                               sg=_w_sg(kept=(GRAND, GREAT)))
    assert p["deep"]["order_n"] == 3 and p["deep"]["order_n_rendered"] == 3
    # a HOLE caps order_n at the last CLOSED hop while the RENDERED depth still says what the page
    # showed -- the two numbers are different findings and used to look the same
    _l2, p2, _c2, _q2, _s2 = _d_run(_d_chain(great=FREE_LEG),
                                    qfn=_d_tape(ROOT, CHILD, GRAND),
                                    sg=_w_sg(kept=(GRAND, FREE_LEG)))
    assert p2["deep"]["order_n"] == 2 and p2["deep"]["order_n_rendered"] == 3


# -- THE LEDGER ZEROES WITH THE BLOCK ------------------------------------------------------------------
def test_all_three_early_returns_zero_the_xccy_ledger(monkeypatch):
    # (a) the REGISTER FENCE trip
    monkeypatch.setattr(cq, "_cw_marker",
                        lambda order, context=False, fx=False:
                        "CASCADE EPISODE WALK: momentum is accelerating into 2027")
    _l, p, calls, _q, _s = _x_run()
    assert p["outcome"] == "fenced"
    assert _x_ledger(p)["rendered"] == 0 and _x_ledger(p)["fx_rendered"] == 0
    assert _x_ledger(p)["pairs"] == []
    monkeypatch.undo()
    # (b) the DORMANT-ROW belt: no board cell closes -> the block ships nothing
    rows = {"cny_usd": _x_fx_rows()}
    _l2, p2, _c2, _q2, _s2 = _x_run(qfn=_WTape(rows))
    assert p2["outcome"] == "declined" and _x_ledger(p2)["rendered"] == 0
    # (c) the source pin for the THIRD return, which is measured-unreachable and reset anyway
    src = open(cq.__file__, encoding="utf-8").read()
    assert src.count('payload["xccy"].update(rendered=0, fx_rendered=0, pairs=[])') == 3


def test_a_root_scope_decline_still_carries_a_closed_xccy_rectangle():
    _l, p, _c, qfn, _s = _x_run(sg=_w_sg(windows=[]))
    assert any(d["reason"] == "no_firing_window" for d in p["declines"])
    x = _x_ledger(p)
    assert x == {"rendered": 0, "pairs": [], "fx_planned": 0, "fx_admitted": 0, "fx_rendered": 0,
                 "fx_reads": 0, "fx_cache_hits": 0, "fx_flips_sign": 0, "fx_unpriced_verdicts": 0,
                 "fx_gate_checked": 0, "cap": cq.CW_FX_CAP, "declines": []}
    assert qfn.sql == []


# -- THE CALL RECORD, THE UNIT AND THE LOCATOR ---------------------------------------------------------
def test_the_fx_call_carries_the_reader_unit_the_right_table_and_the_machine_metric():
    _l, p, calls, _q, _s = _x_run()
    rec = _x_fx_cell(p)
    call = next(c for c in calls if c["query"].get("table") == cq._CW_FX_TABLE)
    assert call["query"]["metric"] == "exchange rate change"        # reader words in the ledger
    assert call["query"]["commodity"] == "Chinese yuan per US dollar"
    assert call["rows"][0]["source_metric"] == "cny_usd"            # the machine id on the LOCATOR
    assert call["rows"][0]["unit"] == "percent change in Chinese yuan per US dollar"
    assert "FRED" not in call["rows"][0]["unit"] and "CNY" not in call["rows"][0]["unit"]
    assert call["rows"][0]["knowledge_date"] == rec["last_date"]


def test_the_fx_row_is_never_the_row_that_licenses_a_marker():
    assert cq._cw_board_row_closed([{"status": "closed", "kind": "fx"}]) is False
    assert cq._cw_board_row_closed([{"status": "closed", "kind": "fx"},
                                    {"status": "closed", "slug": ROOT}]) is True


# -- THE PERSONA -----------------------------------------------------------------------------------
def test_the_walk_mandate_takes_the_positive_currency_needle_unconditionally():
    from leviathan.graphrag import answer as ans
    """DECLARED live prompt change (owner decision #3): the clause is POSITIVE, carries no negative,
    and is TRUE of every walk block -- today every hop is same-currency and both rows name US
    dollars -- so it is vacuously correct on flag-off turns."""
    m = ans._SYSTEM_CASCADE_WALK_MANDATE
    assert "each figure is a move inside the currency its own row names" in m
    assert "write each on its own handle as a fact about that board" in m
    assert "name the dated firing window in words exactly as the hop names it" in m
    needle = ("their [N] handles and figures copied as DIGITS exactly as printed -- each figure is "
              "a move inside the currency its own row names; write each on its own handle as a "
              "fact about that board -- name the dated firing window ")
    assert needle in m                                       # the POSITIVE pin on the needle itself
    for banned in ("never", "not ", "avoid"):                # the clause itself carries no negative
        assert banned not in needle.lower(), banned


def test_the_xccy_mandate_is_positive_only_and_appends_after_the_deep_one(monkeypatch):
    from leviathan.graphrag import answer as ans
    x = ans._SYSTEM_CASCADE_XCCY
    for banned in ("never", "do not", "don't", "must not", "avoid"):
        assert banned not in x.lower(), banned
    assert "TWO BOARDS SETTLE IN DIFFERENT CURRENCIES" in x
    a_src = open(ans.__file__, encoding="utf-8").read()
    assert a_src.index("_SYSTEM_CASCADE_DEEP = (") < a_src.index("_SYSTEM_CASCADE_XCCY = (")
    assert a_src.index("base = base + _SYSTEM_CASCADE_DEEP") < \
        a_src.index("base = base + _SYSTEM_CASCADE_XCCY")
    monkeypatch.setenv("GRAPHRAG_CASCADE_WALK", "on")
    monkeypatch.setenv("GRAPHRAG_CASCADE_XCCY", "on")
    on = ans._system(cascade_walk=True, cascade_xccy=True)
    off = ans._system(cascade_walk=True, cascade_xccy=False)
    assert x in on and x not in off
    assert on.replace(x, "") == off                            # a PURE append, nothing rewritten
    monkeypatch.delenv("GRAPHRAG_CASCADE_XCCY")
    assert ans._system(cascade_walk=True, cascade_xccy=True) == off


# -- GOVERNANCE: THE LINT, THE REGISTER, THE TRACE KEY -------------------------------------------------
def test_the_widened_lint_is_green_and_has_teeth(monkeypatch):
    from leviathan.graphrag import config_check as cc
    assert cc.check_cascade_walk() == []
    assert cc.check_cascade_context() == [] and cc._check_synthesized_price_legs() == []
    # clause (i) in the MISSING direction: the board-label row and the gate edit are COUPLED
    monkeypatch.setattr(cq, "_CW_BOARD_LABEL",
                        {k: v for k, v in cq._CW_BOARD_LABEL.items()
                         if k != "south_african_yellow_maize_jse"})
    assert any("south_african_yellow_maize_jse" in e and "_CW_BOARD_LABEL" in e
               for e in cc.check_cascade_walk())
    monkeypatch.undo()
    # clause (xii) in the STALE direction (the only one it can measure)
    monkeypatch.setattr(cq, "_CW_FX_CROSS", dict(cq._CW_FX_CROSS,
                                                 JPY=("jpy_usd", "Japanese yen per US dollar")))
    assert any("_CW_FX_CROSS entry 'JPY'" in e for e in cc.check_cascade_walk())
    # ...and the R4c FOLD has teeth from inside the FENCE, never a door beside it
    assert any("outside the ratified allow-list" in e for e in cc._check_synthesized_price_legs())


def test_the_curation_rows_that_the_widened_ladder_makes_lint_required():
    """Both edits are LINT-REQUIRED the moment the ladder widens; restoring either one reds the
    clause it belongs to, so they cannot silently drift back."""
    from leviathan.graphrag import config_check as cc
    from leviathan.graphrag import graph as G
    g = G.CausalGraph.load()
    edges = [r for nd in g.rev_cross_link_seeds() for r in g.rev_cross_links(nd)]
    canola = [r for r in edges if r.get("seed") == "soybeans_cbot"
              and r.get("contract") == "canola_ice" and str(r.get("sign")) == "+"]
    assert canola and all("drags" not in str(r.get("blurb")) for r in canola)
    assert any("lifts canola" in str(r.get("blurb")) for r in canola)
    zce = [r for r in edges if r.get("seed") == "soybean_oil_cbot"
           and r.get("contract") == "rapeseed_oil_zce"]
    assert zce and all("abundant" not in str(r.get("mechanism")).lower() for r in zce)
    assert any("conversely" in str(r.get("mechanism")) for r in zce)
    assert all("Abundant soyoil" not in str(r.get("blurb")) for r in zce)
    assert cc.check_cascade_walk() == []


def test_v23_registers_one_trace_key_and_the_ledger_rides_inside_it():
    from leviathan.graphrag import tracekeys as tk
    assert tk.TRACE_RECORD_KEYS[-1] == "quantify_wave_reads"
    assert tk.TRACE_RECORD_KEYS[-2] == "quantify_cascade_walk"
    assert not any("xccy" in k or "fx" in k or "deep" in k for k in tk.TRACE_RECORD_KEYS)


def test_the_eval_projections_read_the_xccy_ledger_without_re_deriving_it():
    from leviathan.graphrag import eval as EV
    _l, p, _c, _q, _s = _x_run()
    st_ = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p},
                             "structured": None, "answer": ""})
    assert st_["cw_xccy_on"] is True and st_["cw_xccy_rendered"] == 1
    assert st_["cw_xccy_pairs"] == ["USD>CNY"] and st_["cw_fx_reads"] == 1
    assert st_["cw_fx_planned"] == st_["cw_fx_admitted"] == st_["cw_fx_rendered"] == 1
    assert st_["cw_fx_declines"] == [] and st_["cw_fx_cache_hits"] == 0
    assert st_["cw_fx_flips_sign"] == 0 and st_["cw_fx_gate_checked"] == 1
    assert st_["cw_order_rendered"] == p["deep"]["order_n_rendered"]
    # the FX cell is NOT a board cell on either counter
    assert st_["cw_cells_declared"] == 2 and st_["cw_cells_measured"] == 2
    # walk-less and flag-off rows read the flag-off shape, never KeyError
    empty = EV._cascade_stats({"citations": [], "trace": {}, "structured": None, "answer": ""})
    assert empty["cw_xccy_on"] is False and empty["cw_xccy_rendered"] == 0
    assert empty["cw_fx_declines"] == [] and empty["cw_order_rendered"] is None
    # ...and the expect key reads the counter its own key names, both branches
    e = {"citations": [], "trace": {}, "structured": None, "answer": ""}
    assert EV._cascade_asserts({"expect": {"cw_xccy_rendered": False}}, e)["cw_xccy_rendered"]
    assert not EV._cascade_asserts({"expect": {"cw_xccy_rendered": True}}, e)["cw_xccy_rendered"]
    # the artifact HARD-WHITELIST projection carries every counter (the Z7 lesson: without them the
    # arm's own verdicts reach NO artifact row)
    esrc = open(EV.__file__, encoding="utf-8").read()
    for k in ("cw_xccy_on", "cw_xccy_rendered", "cw_xccy_pairs", "cw_fx_planned",
              "cw_fx_admitted", "cw_fx_rendered", "cw_fx_reads", "cw_fx_cache_hits",
              "cw_fx_declines", "cw_fx_flips_sign", "cw_fx_unpriced_verdicts",
              "cw_fx_gate_checked", "cw_order_rendered"):
        assert esrc.count("\"" + k + "\"" + ": cs.get(" + "\"" + k + "\"" + ")") == 1, k


# -- L8: THE PALM EOD ROSTER ROW -----------------------------------------------------------------------
def test_the_palm_board_joins_the_eod_fresh_levels_roster():
    """L8: the V2-4 docket's own condition -- palm's canonical CME USD bytes are registered and
    serving at rev 126 -- so the row lands, off the same coverage every other row came from."""
    from leviathan.graphrag import config_check as cc
    from leviathan.graphrag import display as dp
    from leviathan.silver import futures_eod_contracts as FC
    row = cq._RV_EOD_FRESH["malaysian_crude_palm_oil_cme"]
    assert row == ("settle", "CME palm oil") == (row[0], dp._contract_label(
        "malaysian_crude_palm_oil_cme"))
    assert (FC.CONTRACT_MAP["malaysian_crude_palm_oil_cme"] or {})["currency"] == "USD"
    assert "malaysian_crude_palm_oil_cme" in FC.PRICE_COVERAGE_START
    assert len(cq._RV_EOD_FRESH) == 9
    assert all(m == "settle" for (m, _l) in cq._RV_EOD_FRESH.values())
    assert cc._check_synthesized_price_legs() == []       # the same R4c register entry binds it


# ================================================================================================
# V2-3 FIX PASS (2026-09-04). The STEP-12 review + refute were both SOUND_WITH_FIXES and every
# finding was adopted. THESE ARE THE PINS FOR THE FIXES -- one group, at the tail, so the fix set
# is readable as a unit and the sitting it belongs to is named.
# ================================================================================================
_X_W2 = {"start": "2021-02-20", "end": "2021-05-10", "span": "2021-02..2021-05", "n": 5}
#        ^ a SECOND firing window inside the same fixture tape (both root cells close on it), so a
#          two-firing shape is constructible without a window the tape cannot serve.


def _x_two_windows():
    return _w_sg(windows=[{"start": W_START, "end": W_END, "span": W_SPAN, "n": 7}, _X_W2])


# -- FIX 1: THE FX RECTANGLE ON THE FENCED PATH --------------------------------------------------
def test_the_block_fence_names_every_rendered_fx_cell_and_keeps_the_rectangle(monkeypatch):
    """BUILD-REFUTE MAJOR-1, MEASURED: the whole-block register-fence rollback zeroed rendered /
    fx_rendered / pairs and appended NOTHING, so a fenced block reported fx_planned 1, fx_rendered
    0, fx_cache_hits 0, declines [] -- 1 != 0 -- with fx_reads 1 GENUINELY PAID and named by
    nothing. The rollback now appends one {cross, span, reason: block_fenced} per FX cell that had
    rendered, and this is `_x_rect` applied to a fenced path carrying fx_planned > 0 (the suite's
    other fenced pin asserts fx_planned == 0 and so could never see it)."""
    monkeypatch.setattr(cq, "_cw_marker",
                        lambda order, context=False, fx=False:
                        "CASCADE EPISODE WALK: momentum is accelerating into 2027")
    _l, p, calls, _q, _s = _x_run()
    x = _x_ledger(p)
    assert p["outcome"] == "fenced" and calls == []          # the whole block rolled back
    assert x["fx_planned"] == 1 and x["fx_reads"] == 1       # the read was PAID
    assert x["rendered"] == 0 and x["fx_rendered"] == 0 and x["pairs"] == []
    assert x["declines"] == [{"cross": "USD>CNY", "span": W_SPAN, "reason": "block_fenced"}]
    assert _x_rect(p)                                        # 1 == 0 + 0 + 1
    # the reason is in the FULL tuple and NOT in the pre-admit one: those cells were admitted and
    # paid, so counting them pre-admit would double them in the first rectangle
    assert "block_fenced" in cq._CW_FX_DECLINES
    assert (x["fx_planned"] == x["fx_admitted"] + x["fx_cache_hits"]
            + sum(1 for d in x["declines"] if d["reason"] in cq._CW_FX_PRE_ADMIT))
    # ...and the FX cell itself carries no handle after the rollback, like every other cell
    assert all(c.get("handle") is None for c in p["cells"])


# -- FIX 2: A ZERO-SAME-CURRENCY ROOT NEVER PAYS AN ORPHAN SECOND ROOT CELL ----------------------
def test_a_root_whose_children_are_all_lifted_never_pays_a_second_root_cell():
    """BUILD-REFUTE MAJOR-2, MEASURED. `same_ccy_n == 0` was unreachable before the rider and is
    live now: rapeseed_meal_zce (CNY, 2 lifted children) and french_wheat_matif (EUR, 3) are the
    live roots. It fell through to `firings[:CW_MAX_FIRINGS]`, and on firing 2 the per-firing legs
    are `same_ccy` == [] -- so the engine paid a second root cell and rendered a bare ROW-1 that no
    CONSEQUENCE HOP, READ or ABSENCE ever referred to. The switch reads `!= 1` now."""
    kids = (X_CNY, "rapeseed_meal_zce")                      # BOTH lifted: same_ccy_n == 0
    lines, p, calls, _q, _s = _x_run(children=kids, sg=_x_two_windows())
    assert p["outcome"] == "fired"
    assert len(p["firings"]) == 1 and p["firings"][0]["span"] == W_SPAN
    assert sum(1 for c in p["cells"] if c.get("slug") == ROOT) == 1
    assert sum(1 for ln in lines if ln.startswith("- [N") and "CBOT corn" in ln) == 1
    # every rendered ROW-1 is referred to by a hop: one root + two lifted children + the ONE rate
    assert sum(1 for ln in lines if ln.startswith("- [N")) == 4
    assert sum(1 for ln in lines if ln.startswith("CONSEQUENCE HOP")) == 2
    assert cq._cw_register_fence(lines) and _x_rect(p)
    # and the two-firing shape is still REACHABLE -- the fix narrows the switch, it does not close it
    _l2, p2, _c2, _q2, _s2 = _w_run(sg=_x_two_windows())
    assert len(p2["firings"]) == 2                           # one same-currency child, no grand leg


# -- FIX 6: ONE POPULATION FOR THE SHAPE SWITCH AND THE PER-FIRING LEGS --------------------------
def test_the_post_belt_population_decides_the_firing_shape(monkeypatch):
    """BUILD-REVIEW MINOR, adopted. The switch runs BEFORE the paid-cell selection -- it must,
    because `free_set` is defined over the SELECTED firings -- so it read the PRE-belt count while
    the render loop read the POST-belt list. THE POPULATION THAT DECIDES IS `same_ccy`: the same
    `!= 1` predicate is re-taken against the children that survived, and payload[firings] is
    truncated with it. Here the lone same-currency child loses the single paid slot to the
    alphabetically-earlier lifted one, so `same_ccy` is empty while two firings were planned."""
    monkeypatch.setattr(cq, "CW_DEEP_MAX_CHILDREN", 1)
    lines, p, _c, _q, _s = _x_run(children=(X_CNY, CHILD), sg=_x_two_windows())
    assert any(d.get("reason") == "child_not_priced_budget" and d.get("child") == CHILD
               for d in p["declines"])                       # the same-currency child WAS dropped
    assert p["outcome"] == "fired" and len(p["firings"]) == 1
    assert sum(1 for c in p["cells"] if c.get("slug") == ROOT) == 1
    assert sum(1 for ln in lines if ln.startswith("CONSEQUENCE HOP")) == 1
    assert p["deep"]["cells_planned"] == 2                   # ONE firing: root + the lifted child
    assert cq._cw_register_fence(lines) and _x_rect(p)


# -- FIX 3: THE EXCEPTION BELT CARRIES THE XCCY REGIME -------------------------------------------
def test_the_exception_belt_carries_the_xccy_regime_and_eval_projects_it(monkeypatch):
    """BUILD-REFUTE MAJOR-3, MEASURED: the belt re-stamped payload[deep] under the rider UNION but
    nothing for xccy, so eval's `cw_xccy_on` (xccy in _cw) projected False. Under the flip
    GRAPHRAG_CASCADE_DEEP stays OFF and `deep` is set BY `xccy` -- so a treatment error row was
    indistinguishable from a deep-only CONTROL row."""
    from leviathan.graphrag import eval as EV

    def _boom(*_a, **_kw):
        raise RuntimeError("leg exploded")

    monkeypatch.setattr(cq, "_cascade_walk_legs", _boom)
    calls = ["a-prior-call"]
    lines, p = cq._cascade_walk_leg_or_nothing(_w_sg(), _x_graph(),
                                               {"focus_contract": ROOT, "xccy": True},
                                               _x_tape(), ASOF_W, calls)
    assert lines == [] and calls == ["a-prior-call"]         # the ledger rolls back, nothing else
    assert p["outcome"] == "declined" and p["declines"] == [{"scope": "root", "reason": "error"}]
    assert p["xccy"] == {"error": True} and p["deep"]["error"] is True
    st_ = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p},
                             "structured": None, "answer": ""})
    assert st_["cw_xccy_on"] is True and st_["cw_xccy_error"] is True
    assert st_["cw_deep_error"] is True and st_["cw_deep_identity_ok"] is None
    assert st_["cw_fx_planned"] == 0 and st_["cw_fx_declines"] == []
    # ...and a DEEP-ONLY belt row carries NO xccy key at all, so the two regimes stay separable
    calls2: list = []
    _l2, p2 = cq._cascade_walk_leg_or_nothing(_w_sg(), _x_graph(),
                                              {"focus_contract": ROOT, "deep": True},
                                              _x_tape(), ASOF_W, calls2)
    assert p2["deep"]["error"] is True and "xccy" not in p2
    st2 = EV._cascade_stats({"citations": [], "trace": {"quantify_cascade_walk": p2},
                             "structured": None, "answer": ""})
    assert st2["cw_xccy_on"] is False and st2["cw_xccy_error"] is False
    # the companion reaches the ARTIFACT row, or the arm's own verdict reaches no row at all (Z7)
    esrc = open(EV.__file__, encoding="utf-8").read()
    assert esrc.count('"cw_xccy_error": cs.get("cw_xccy_error")') == 1


# -- FIX 4: THE RIDER SLACK IS BUDGETED AGAINST THE REGIME'S OWN CEILING --------------------------
def test_the_rider_slack_reads_the_regimes_own_ceiling():
    """BUILD-REFUTE MINOR + BUILD-REVIEW MINOR, both adopted. `_cw_slack` read the bare 60 in both
    regimes while the board plan was admitted against 80, which made the 7 reads
    CW_DEEP_TURN_CEILING reserves for the riders STRUCTURALLY UNREACHABLE -- and V2-3 makes the deep
    regime the FX rider's unconditional state, so that was the default rather than an edge case.
    The behavioural half is test_the_budget_rung_calls_the_one_slack_helper; this is the arithmetic
    config_check's NOTE prints, asserted against the constants it names."""
    import inspect
    src = inspect.getsource(cq._cascade_walk_legs)
    assert "return cw_ceiling - (spent + board_reads + ctx_admitted + fx_admitted)" in src
    assert "CW_TURN_CEILING - (spent" not in src
    assert cq.CW_DEEP_TURN_CEILING - (44 + cq.CW_DEEP_CAP + cq.CW_CONTEXT_CAP) == 7
    assert cq.CW_CONTEXT_CAP + cq.CW_FX_CAP <= 7             # both riders' caps fit the reserve
    assert cq.CW_TURN_CEILING - (44 + cq.CW_CAP) >= 0        # ...and the off regime is unchanged


# -- FIX 5: THE ORDER LABEL'S CLOSED SET EXCLUDES FX CELLS ---------------------------------------
def test_the_order_label_closed_set_excludes_fx_cells():
    """BUILD-REVIEW MINOR, adopted. An FX cell carries NO `slug` key, so the un-widened kind filter
    seeded a bare None into the membership set `_cw_order_n` reads -- the one place the new kind was
    missed, while _cw_board_row_closed and both eval cell filters were widened correctly."""
    import inspect
    src = inspect.getsource(cq._cascade_walk_legs)
    assert 'if c.get("kind") not in ("context", "fx") and c.get("status") == "closed"' in src
    assert 'if c.get("kind") != "context" and c.get("status") == "closed"' not in src
    _l, p, _c, _q, _s = _x_run()
    assert _x_fx_cell(p)["status"] == "closed"               # a CLOSED fx cell is on the payload
    assert p["deep"]["order_n"] == p["deep"]["order_n_rendered"] == 1
    assert None not in {c.get("slug") for c in p["cells"]
                        if c.get("kind") not in ("context", "fx") and c.get("status") == "closed"}


# -- FIX 8: A CACHE HIT ON A DECLINED RATE IS NOT A FREE PASS ------------------------------------
def test_a_cache_hit_on_a_declined_rate_declines_by_name():
    """BUILD-REFUTE MINOR, adopted. `fx_by_cross[_ck]` is written in rung 7 BEFORE the status test,
    so a second hop on a cross whose first read DECLINED counted fx_cache_hits and nothing else --
    the ledger under-counted the hops that shipped with no priced rate by one per extra hop. Rung 2
    now splits: a CLOSED record is a free pass and counts a cache hit; a declined one DECLINES BY
    NAME at zero reads. cache_declined is PRE-ADMIT, so both rectangles still close."""
    kids = (X_CNY, "rapeseed_meal_zce")                      # ONE cross, TWO hops
    thin = {"cny_usd": _x_fx_rows(t1="2021-04-01", t2="2021-04-01")}   # one print -> grain_thin
    lines, p, _c, qfn, _s = _x_run(children=kids, fx=thin)
    x = _x_ledger(p)
    assert p["outcome"] == "fired" and x["fx_planned"] == 2 and x["fx_admitted"] == 1
    assert x["fx_rendered"] == 0 and x["fx_cache_hits"] == 0
    assert [d["reason"] for d in x["declines"]] == ["grain_thin", "cache_declined"]
    assert [d["cross"] for d in x["declines"]] == ["USD>CNY", "USD>CNY"]
    assert sum(1 for s in qfn.sql if "cny_usd" in (s or "")) == 1      # STILL one read per cross
    assert x["fx_reads"] == 1 and x["fx_unpriced_verdicts"] == 2
    assert _x_rect(p)                                                  # 2 == 0 + 0 + 2
    assert (x["fx_planned"] == x["fx_admitted"] + x["fx_cache_hits"]
            + sum(1 for d in x["declines"] if d["reason"] in cq._CW_FX_PRE_ADMIT))
    # both hops still carry the unpriced words -- the page never claims a rate it does not hold
    assert sum(1 for ln in lines if ln.startswith(cq.CW_FX_WORDS_PREFIX)) == 2
    assert all("not priced on this page" in ln for ln in lines
               if ln.startswith(cq.CW_FX_WORDS_PREFIX))
    # ...and a CLOSED first read still buys the second hop its free pass, unchanged
    _l2, p2, _c2, _q2, _s2 = _x_run(children=kids)
    assert _x_ledger(p2)["fx_cache_hits"] == 1 and _x_ledger(p2)["declines"] == []


# -- FIX 9: THE LADDER CHECKS THE CARD DECLARES THE MAPPED METRIC BEFORE PAYING -------------------
def test_the_ladder_declines_an_undeclared_metric_before_paying_the_read(monkeypatch):
    """BUILD-REFUTE MINOR, adopted. Rung 6 tested only `_fx_declared is None`; rung 7 then paid a
    read and handed `_cw_fx_cell` a card_metric of None for a missing column. All four
    _CW_FX_CROSS metrics exist on the live card today, so this is LATENT -- but the day a column is
    dropped the engine spent CW_FX_CAP on a cell that could only error."""
    class _Card:
        metrics = {"brl_usd": SimpleNamespace(unit="BRL per USD (ECB via Frankfurter)")}

    monkeypatch.setattr(cq, "_registry", lambda: SimpleNamespace(get=lambda _t: _Card()))
    lines, p, _c, qfn, _s = _x_run()
    x = _x_ledger(p)
    assert p["outcome"] == "fired"                           # the BLOCK still ships
    assert [d["reason"] for d in x["declines"]] == ["no_metric"]
    assert x["fx_planned"] == 1 and x["fx_admitted"] == 0 and x["fx_reads"] == 0
    assert not any("cny_usd" in (s or "") for s in qfn.sql)  # THE READ WAS NEVER PAID
    assert _x_rect(p) and cq._cw_register_fence(lines)


# -- FIX 7: THE MEASURED CALIBRATION CASE, AS A FIXTURE -------------------------------------------
_XC_PALM, _XC_ZCE = "malaysian_crude_palm_oil_cme", X_CNY
_XC_START, _XC_END, _XC_SPAN = "2022-01-01", "2022-08-01", "2022-01..2022-08"
_XC_T0, _XC_T1 = "2021-10-01", "2022-10-15"
# X = the endpoint month of the firing window = 2022-08. Palm's forward_month_floor is 1, so it
# lands on X+1 = 2022-09; ZCE's is 0, so it lands on X itself -- ADJACENT months, which is exactly
# what the MAJOR-8 tenor fence admits, so the pair verdicts rather than declining.
_XC_LIFE = {"2022-08": (_XC_T0, "2022-08-31"),
            "2022-09": (_XC_T0, "2022-09-30"),
            "2022-10": (_XC_T0, _XC_T1)}


def _xc_rows(priced_month, px0, px1, unit, currency):
    d, end = _dt.date.fromisoformat(_XC_T0), _dt.date.fromisoformat(_XC_T1)
    out = []
    while d <= end:
        iso = d.isoformat()
        for cm, (first, last) in _XC_LIFE.items():
            if not (first <= iso <= last):
                continue
            settle = (px0 if iso <= _XC_START else px1) if cm == priced_month else 400.0
            out.append({"value": settle, "knowledge_date": iso, "contract_month": cm,
                        "unit": unit, "currency": currency, "settle_kind": "settlement"})
        d += _dt.timedelta(days=1)
    return out


def _xc_fx_rows(v1):
    d, end = _dt.date.fromisoformat(_XC_T0), _dt.date.fromisoformat(_XC_T1)
    step = _dt.date.fromisoformat(_XC_START)
    out = []
    while d <= end:
        out.append({"value": (1.0 if d <= step else v1), "knowledge_date": d.isoformat(),
                    "unit": "CNY per USD"})
        d += _dt.timedelta(days=1)
    return out


def _xc_run(fx_v1):
    edge = _w_edge(seed=_XC_PALM, contract=_XC_ZCE, relation="substitutes_for", sign="+",
                   lag="0-2 quarters",
                   blurb="the two oils stand in for one another in the same uses")
    nodes = {_XC_PALM: "palm_oil", _XC_ZCE: "rapeseed_oil"}
    graph = SimpleNamespace(
        contracts={_XC_PALM: SimpleNamespace(drivers=[SimpleNamespace(id="heat")])},
        rev_cross_links=lambda c, _n=nodes: ([dict(edge)] if _n.get(c, c) == "palm_oil" else []),
        contract_node=lambda c, _n=nodes: _n.get(c, c))
    sg = _w_sg(windows=[{"start": _XC_START, "end": _XC_END, "span": _XC_SPAN, "n": 9}])
    qfn = _WTape({_XC_PALM: _xc_rows("2022-09", 100.0, 98.6978, "USD/metric ton", "USD"),
                  _XC_ZCE: _xc_rows("2022-08", 100.0, 104.5577, "CNY/metric ton", "CNY"),
                  "cny_usd": _xc_fx_rows(fx_v1)})
    calls: list = []
    lines, payload = cq._cascade_walk_leg_or_nothing(
        sg, graph, {"focus_contract": _XC_PALM, "xccy": True}, qfn, ASOF_W, calls)
    return lines, payload, calls, qfn


def test_the_dominance_gate_on_the_measured_palm_to_zce_calibration_case():
    """L4's OWN MEASUREMENT, as a fixture (build-review minor: the predicate was pinned on synthetic
    +15 %/+20 % legs, so the measurement that justified choosing the co-signed form over the bare
    magnitude test lived only in prose). THE REAL CASE, on the REAL slugs and the REAL window:

      CME palm oil -> ZCE rapeseed oil, 2022-01-01..2022-08-01
      palm  -1.3022 % (USD, its own currency)
      ZCE   +4.5577 % (CNY, its own currency)      -> own-currency verdict AT_ODDS
      CNY per US dollar  +6.2475 %                 -> larger AND co-signed with the non-USD leg
      ZCE redenominated  (1.045577/1.062475 - 1)   = -1.5904 %, which is ALIGNED with palm

    So the own-currency at_odds is an artefact of the denomination, and the gate refuses to print a
    direction rather than printing the wrong one. A constant edit that broke the calibration would
    have to flip one of these three numbers to stay green."""
    lines, p, calls, _q = _xc_run(1.062475)
    palm = next(c for c in p["cells"] if c.get("slug") == _XC_PALM)
    zce = next(c for c in p["cells"] if c.get("slug") == _XC_ZCE)
    fx = _x_fx_cell(p)
    assert p["outcome"] == "fired"
    assert palm["move_pct"] == -1.3022 and palm["contract_month"] == "2022-09"
    assert zce["move_pct"] == 4.5577 and zce["contract_month"] == "2022-08"
    assert fx["move_pct"] == 6.2475 and fx["cross"] == "USD>CNY" and fx["status"] == "closed"
    assert (zce["interval_ok"], zce["tenor_ok"]) == (True, True)     # the pair really is verdictable
    # THE GATE FIRES: the rate moved further than the non-USD board AND the same way
    assert abs(fx["move_pct"]) > abs(zce["move_pct"])
    assert (fx["move_pct"] > 0) == (zce["move_pct"] > 0)
    assert zce["verdict"] == "undetermined" and zce["verdict_reason"] == "fx_flips_sign"
    assert _x_ledger(p)["fx_flips_sign"] == 1 and _x_ledger(p)["fx_gate_checked"] == 1
    assert _x_rect(p) and cq._cw_register_fence(lines)
    # THE GROUND TRUTH THE GATE IS PROTECTING: in a common denomination the two moves AGREE
    assert round((1.045577 / 1.062475 - 1.0) * 100.0, 4) == -1.5904
    assert (round((1.045577 / 1.062475 - 1.0) * 100.0, 4) < 0) == (palm["move_pct"] < 0)
    # ...and WITHOUT the dominant rate the SAME pair prints at_odds -- the verdict the gate withheld
    _l2, p2, _c2, _q2 = _xc_run(1.005)
    zce2 = next(c for c in p2["cells"] if c.get("slug") == _XC_ZCE)
    assert zce2["verdict"] == "at_odds" and "verdict_reason" not in zce2
    assert _x_ledger(p2)["fx_flips_sign"] == 0 and _x_ledger(p2)["fx_gate_checked"] == 1


# -- FIX 10: THE CARD'S UNIT STRINGS AGREE WITH THE TABLE'S OWN LABEL -----------------------------
def test_the_fx_card_units_name_the_ecb_reference_rate_never_fred():
    """BUILD-REFUTE MINOR, adopted. display_names.yaml labels silver_fred_fx ECB reference rates
    while three incumbent metrics still carried (FRED) in their unit -- and citations.from_number
    renders SOURCE then UNIT on the same reader line, so a live CNY citation read ECB reference
    rates ... = 6.72 CNY per USD (FRED). Every row of the tape carries source == frankfurter, so
    (FRED) was the wrong half. The table ID keeps its documented legacy misnomer (ADR-003)."""
    from leviathan.graphrag import display as dp
    card = cq._registry().get(cq._CW_FX_TABLE)
    assert dp.table_label(cq._CW_FX_TABLE) == "ECB reference rates"
    metrics = getattr(card, "metrics", None) or {}
    for m, _lbl in cq._CW_FX_CROSS.values():
        unit = str(getattr(metrics[m], "unit", "") or "")
        assert unit and "FRED" not in unit and "ECB via Frankfurter" in unit
    assert not any("FRED" in str(getattr(v, "unit", "") or "") for v in metrics.values())


# -- THE CONSUMER OF _CW_FX_DECLINES -------------------------------------------------------------
def test_every_fx_decline_reason_this_group_can_produce_is_named_in_the_tuple(monkeypatch):
    """BUILD-REVIEW MINOR, adopted: `_CW_FX_DECLINES` had no engine or lint consumer, so the
    declines-are-NAMED-and-COUNTED law was documented rather than enforced -- a future rung emitting
    an unlisted reason would reach the artifact unnoticed. THIS IS THE CONSUMER. It runs the group's
    own fixtures and closes over every reason they produce."""
    seen: set = set()

    def _take(p):
        seen.update(str(d.get("reason")) for d in (_x_ledger(p).get("declines") or []))
        assert _x_rect(p), sorted(seen)

    _take(_x_run(request={"focus_contract": ROOT, "xccy": True, "replay": True})[1])   # replay
    _take(_x_run(children=(X_CNY, "rapeseed_meal_zce"),                                # grain_thin
                 fx={"cny_usd": _x_fx_rows(t1="2021-04-01", t2="2021-04-01")})[1])     # + cache_declined
    _take(_x_run(sg=_w_sg(trace_extra={                                                # budget_cap
        "quantify_wave_reads": cq.CW_DEEP_TURN_CEILING - 6}))[1])
    monkeypatch.setattr(cq, "CW_FX_CAP", 1)                                            # fx_cap
    _take(_x_run(children=(X_CAD, X_CNY),
                 fx={"cny_usd": _x_fx_rows(),
                     "cad_usd": _x_fx_rows(v1=1.10, unit="CAD per USD")})[1])
    monkeypatch.undo()
    monkeypatch.setattr(cq, "_registry",
                        lambda: (_ for _ in ()).throw(RuntimeError("no card")))        # read_error
    _take(_x_run()[1])
    monkeypatch.undo()
    monkeypatch.setattr(cq, "_cw_marker",                                              # block_fenced
                        lambda order, context=False, fx=False:
                        "CASCADE EPISODE WALK: momentum is accelerating into 2027")
    _take(_x_run()[1])
    monkeypatch.undo()
    assert seen >= {"replay", "grain_thin", "cache_declined", "budget_cap", "fx_cap",
                    "no_card", "block_fenced"}
    assert seen <= set(cq._CW_FX_DECLINES), sorted(seen - set(cq._CW_FX_DECLINES))


def test_the_context_rider_budgets_against_the_REGIME_ceiling_under_deep():
    """V2-3 fix re-review minor 6: FIX-4 made `_cw_slack` budget BOTH riders against the regime's
    own ceiling, and the deep golden's only moved fixture was the CONTEXT cell -- admitted where it
    used to decline budget_cap under forced deep. That move was recorded, not pinned. This is the
    pin, the exact mirror of test_context_budget_is_subordinate_never_the_block one regime up: with a
    2-cell board plan (6 reads) a wave spend of CW_DEEP_TURN_CEILING - 6 leaves zero slack and the
    context cell declines budget_cap at zero reads while the walk still fires; one read of slack
    admits it; and the OLD bare-60 boundary now ADMITS under deep, which is the whole point."""
    req = {"focus_contract": ROOT, "context": True, "deep": True}
    _ceil = cq.CW_DEEP_TURN_CEILING
    assert _ceil == 80 and cq.CW_TURN_CEILING == 60
    tight = _c_sg(trace_extra={"quantify_wave_reads": _ceil - 6})
    lines, payload, calls, qfn, _s = _c_run(request=req, sg=tight)
    assert payload["outcome"] == "fired"
    assert not any(d["reason"] == "turn_budget_spent" for d in payload["declines"])
    assert [d["reason"] for d in payload["context"]["declines"]] == ["budget_cap"]
    assert payload["context"]["reads"] == 0 and not any("chicken_usd_t" in s for s in qfn.sql)
    slack = _c_sg(trace_extra={"quantify_wave_reads": _ceil - 7})
    _l2, p2, _c2, _q2, _s2 = _c_run(request=req, sg=slack)
    assert p2["outcome"] == "fired" and p2["context"]["rendered"] == 1 and p2["context"]["reads"] == 1
    old = _c_sg(trace_extra={"quantify_wave_reads": cq.CW_TURN_CEILING - 6})
    _l3, p3, _c3, _q3, _s3 = _c_run(request=req, sg=old)
    assert p3["context"]["rendered"] == 1 and p3["context"]["declines"] == []

