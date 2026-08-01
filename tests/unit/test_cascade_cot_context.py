"""C1 / D1 -- the R9 CONTEXT LANE: the positioning door, and the proof it stays narrow.

Hermetic (no pg/Athena/LLM; a SQL-text-keyed qfn stub, the test_cascade_pace_live_path convention).

R9 used to ban `silver_cot` from cascade_map outright, which left `cascade.PACE_TABLES["silver_cot"]`
structurally unreachable -- a weekly-COT pace engine that was built and had no door. D1 (ratified
2026-08-01) splits the two things that blanket ban conflated: positioning FETCHED and narrated
past-tense as CONTEXT is admitted; positioning as an ENGINE ref that may drive a fork or a regime is
still refused, still at build time. This module pins the runtime half of that split:

  * `positioning_context_violations` -- the ONE shape definition, each clause tied to the fork/regime
    code path it closes (config_check's amended R9 reads the SAME function, so lint and engine cannot
    disagree about what "context" means);
  * the fail-closed gate in `quantify` -- a mis-shaped positioning row leaves the node qualitative,
    exactly as it is today, and the pace flag OFF keeps the door shut whatever the map says;
  * the RENDER -- a dated past-tense level with the full `[series: ...]` tag and a `shown` binding on
    every minted [N] row, like every other line the engine writes;
  * the leg is NOT a fork -- no reroute pair, no DIVERGENCE line, no cross-era delta;
  * the C1 ACCEPTANCE BOUND -- the rendered lines plus the narration addendum add ZERO raw
    flow-register hits. `tests/unit/test_register_corpus.py` carries the standing corpus half (the
    addendum string itself, plus the teeth cases that MUST flag if the leg ever turns forward-looking);
    this is the LIVE-render half, which follows the engine wherever the render goes.
"""
from __future__ import annotations

from types import SimpleNamespace

from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq

ASOF = "2026-07-31"
# The ratified context-leg shape (the plan's C1 step-1 row spec: table/metric/period_type/leg_mode/
# country_rule). silver_cot's commodity_col is leviathan_slug -- CONTRACT slugs -- so country_rule is
# `none` and the scope resolves to the slug alone.
_COT_ROW = {
    "table": "silver_cot", "metric": "mm_net", "agg": "latest", "period_type": "date",
    "leg_mode": "current", "country_rule": "none", "native_unit": "contracts",
    "narrate_unit": "contracts", "scale": 1,
}


def _node(contract="corn_cbot", ref="cot_mm_positioning", nid="managed_money_positioning"):
    """The live positioning-driver shape: a prior-only numbers-lane node (no dated evidence), which is
    the era-less case the context leg exists to serve."""
    return SimpleNamespace(contract=contract, id=nid, prior={"silver_ref": ref, "region": "US"},
                           evidence=[])


def _sg(nodes):
    return SimpleNamespace(nodes=nodes, trace={}, fired_regimes=[])


def _qfn(sql):
    """agg=latest -> the freshest weekly print; agg=series -> four ascending Tuesdays (change +2,400,
    a 3-week up-run) so both pace shapes render."""
    s = (sql or "").lower()
    if "desc" in s and "limit 1" in s:
        return [{"value": "118432", "report_date": "2026-07-28"}]
    return [{"value": str(111232 + 2400 * i), "report_date": f"2026-07-{7 + 7 * i:02d}"}
            for i in range(4)]


def _run(row=_COT_ROW, *, pace=True, qfn=_qfn, monkeypatch=None):
    monkeypatch.setattr(cq, "load_map", lambda: {"cot_mm_positioning": row})
    calls: list = []
    block, trace, rtrace = cq.quantify(_sg([_node()]), None, qfn=qfn, asof=ASOF, near=None,
                                       extra_number_calls=calls, pace=pace)
    return block, trace, rtrace, calls


# -- the shape rule: one definition, every clause tied to a code path --------------------------------
def test_the_ratified_context_shape_is_admitted():
    assert cq.positioning_context_violations(_COT_ROW) == []
    # OUTCOMES_JOIN D-OJ-18 (2026-08-01): the fence GREW by one id. `gold_cot_outcomes` is the J6 card --
    # the COT-keyed outcome rows -- and it is in here rather than outside because every leg of this fence
    # keys on the table id, so serving a positioning-derived number from a table outside the set would
    # satisfy R9's letter while vacating the context-shape rule, the never-a-chain-hop ban and the
    # never-a-relative-value-leg ban together. Pinned as an EQUALITY, not a membership, so a third id
    # cannot arrive here unnoticed; config_check.POSITIONING_TABLES must move in the same edit or the
    # drift pin fails the build.
    assert cq.POSITIONING_TABLES == frozenset({"silver_cot", "gold_cot_outcomes"})


def test_every_engine_shape_is_refused_with_a_reason():
    def why(**tweak):
        row = {**_COT_ROW, **tweak}
        return " ".join(cq.positioning_context_violations(row))

    # era legs ARE the cross-era fork backbone (_era_delta -> _divergence)
    assert "leg_mode" in why(leg_mode="era")
    assert "leg_mode" in why(leg_mode=None)
    # the marketing-year fan is that same fork's window machinery
    assert "marketing_year" in why(period_type="marketing_year")
    # a trade metric is what seeds an RF-3 reroute PAIR -- the OTHER fork
    assert "reroute" in why(metric="exports_mt")
    # a 0/1 row is a REGIME MARKER, not an observed level
    assert "REGIME MARKER" in why(narrate_unit="flag")
    # never raises, and an unreadable row reads as a violation (fail-closed)
    assert cq.positioning_context_violations(None)
    assert cq.positioning_context_violations({})


# -- the fail-closed engine gate ---------------------------------------------------------------------
def test_a_misshaped_positioning_row_leaves_the_node_qualitative(monkeypatch):
    block, trace, _rt, calls = _run({**_COT_ROW, "leg_mode": "era"}, monkeypatch=monkeypatch)
    assert block is None and trace == [] and calls == []


def test_a_trade_metric_positioning_row_is_refused_at_runtime_too(monkeypatch):
    block, _tr, _rt, calls = _run({**_COT_ROW, "metric": "exports_mt"}, monkeypatch=monkeypatch)
    assert block is None and calls == []


def test_pace_flag_off_keeps_the_door_shut_on_the_era_less_node(monkeypatch):
    # The ERA-LESS shape -- a prior-only positioning driver, which is the live one -- dies at quantify's
    # own selection gate when pace is OFF: a `leg_mode: current` node with no era windows survives only
    # `pace and _pace_grain(row) is not None`. So D1's "deterministic" claim is conditional on
    # GRAPHRAG_CASCADE_PACE_LEG being ON in the measured lane, and this is what that costs when it is not.
    block, _tr, _rt, calls = _run(pace=False, monkeypatch=monkeypatch)
    assert block is None and calls == []


def test_an_evidence_backed_positioning_node_renders_the_level_with_pace_off(monkeypatch):
    # ... and the OTHER half of the same fact: a positioning node that DOES carry dated evidence passes
    # the era gate on its own, so the context level (and its addendum) render with the pace flag off.
    # `leg_mode: current` still means no era legs are built, so there is nothing for a fork to read.
    monkeypatch.setattr(cq, "load_map", lambda: {"cot_mm_positioning": _COT_ROW})
    n = SimpleNamespace(contract="corn_cbot", id="managed_money_positioning",
                        prior={"silver_ref": "cot_mm_positioning", "region": "US"},
                        evidence=[{"date": "2012-06-01", "source": "usda_gain", "source_key": "k1",
                                   "text": "t"},
                                  {"date": "2012-08-01", "source": "usda_gain", "source_key": "k2",
                                   "text": "t"}])
    calls: list = []
    block, trace, rtrace = cq.quantify(_sg([n]), None, qfn=_qfn, asof=ASOF, near="2012",
                                       extra_number_calls=calls, pace=False)
    assert block is not None and cq.POSITIONING_CONTEXT_ADDENDUM in block
    assert trace and trace[0]["era_statuses"] == {} and trace[0]["divergence"] is False
    assert rtrace == [] and reg.count_flow_words(block) == 0


# -- the render: dated, past-tense, tagged, bound ----------------------------------------------------
def test_context_leg_renders_a_dated_level_with_the_series_tag(monkeypatch):
    block, trace, _rt, calls = _run(monkeypatch=monkeypatch)
    assert block is not None
    lines = [ln for ln in block.splitlines() if ln.startswith("- [N")]
    assert lines, "the context leg minted no [N] line"
    for ln in lines:
        # A1: the SOURCE segment is dp.table_label ("COT"), never the raw silver_* id.
        assert "[series: corn_cbot" in ln and "table: COT]" in ln, ln
        assert "silver_" not in ln, ln
    assert any("mm_net" in ln and "118432" in ln for ln in lines)      # the dated level itself
    assert any("as-of 2026-07-31" in ln for ln in lines)


def test_every_minted_row_carries_a_shown_binding(monkeypatch):
    _block, _tr, _rt, calls = _run(monkeypatch=monkeypatch)
    assert calls, "no [N] call was appended"
    for c in calls:
        assert "shown" in c, c                                        # the verifier's value binding
        assert (c.get("query") or {}).get("table") == "silver_cot"


def test_the_weekly_pace_shapes_render_past_tense(monkeypatch):
    block, _tr, _rt, _calls = _run(monkeypatch=monkeypatch)
    assert "change in mm_net from the prior week" in block            # window_change, past tense
    assert "rose in each of the last 3 weeks" in block                # streak, past tense
    for ln in block.splitlines():
        assert cq.pace_register_ok(ln), ln                            # no momentum-class vocabulary


# -- the leg is CONTEXT, never a fork ----------------------------------------------------------------
def test_the_context_leg_is_not_a_fork(monkeypatch):
    block, trace, rtrace, _calls = _run(monkeypatch=monkeypatch)
    assert rtrace == []                                               # no cross-country reroute pair
    assert "DIVERGENCE" not in block                                  # no cross-era fork line
    assert trace and all(t.get("divergence") is False for t in trace)
    assert all(t.get("era_statuses") == {} for t in trace)            # no era legs exist at all


# -- C1 ACCEPTANCE: the raw banned_flow bound, measured on the LIVE render ---------------------------
def test_rendered_lines_plus_addendum_add_zero_raw_flow(monkeypatch):
    block, _tr, _rt, _calls = _run(monkeypatch=monkeypatch)
    assert cq.POSITIONING_CONTEXT_ADDENDUM in block
    assert reg.count_flow_words(block) == 0                           # the C1 bound, whole-block
    assert reg.count_valuation_words(block) == 0
    assert reg.exec_leaks(block) == []
    for ln in block.splitlines():                                     # and per line, so a future line
        assert reg.count_flow_words(ln) == 0, ln                      # cannot hide inside the blob


def test_the_addendum_rides_only_a_leg_that_actually_rendered(monkeypatch):
    # honest absence: no rows -> no line, and therefore no narration addendum either
    block, _tr, _rt, _calls = _run(qfn=lambda s: [], monkeypatch=monkeypatch)
    assert block is None or cq.POSITIONING_CONTEXT_ADDENDUM not in block


def test_a_non_positioning_turn_never_carries_the_addendum(monkeypatch):
    monkeypatch.setattr(cq, "load_map", lambda: {"export": {
        "table": "silver_psd", "metric": "exports_mt", "agg": "latest",
        "period_type": "marketing_year", "narrate_unit": "MMT", "scale": 0.000001}})
    calls: list = []
    node = SimpleNamespace(contract="corn_cbot", id="export_ban",
                           prior={"silver_ref": "export", "region": "US"},
                           evidence=[{"date": "2012-06-01", "source": "usda_gain", "source_key": "k",
                                      "text": "t"}])
    block, _tr, _rt = cq.quantify(_sg([node]), None, qfn=lambda s: [{"value": "10000000",
                                                                    "market_year": 2012}],
                                  asof=ASOF, near="2012", extra_number_calls=calls, pace=True)
    assert block is None or cq.POSITIONING_CONTEXT_ADDENDUM not in block


# -- D1's OUTLOOK CARVE-OUT (F2): the context leg is FENCED-lane only --------------------------------
# D1 ratified the split "ONLY under the FENCED register", in terms it left no room to read past: "do NOT
# proceed on the outlook lane." That is not a shape rule and cannot be one -- the same row is admissible
# on a fenced turn and refused on an outlook one -- so it is a gate argument, threaded from the answer.py
# quantify seam where the outlook legs were already resolved.
#
# WHY IT MATTERS, measured rather than argued: register.py:689-694 releases the FLOW fence by design
# under OUTLOOK (_FLOW_PHRASES and both Lane-B arms sit inside `if not outlook:`), the outlook deck's
# `ol_soyoil_positioning_leg` pins max_banned_flow: 6 and its own comment ratifies the relaxation, and
# rep_outlook_r3.md:397 recorded a residual "crowded long" on THAT row with ZERO cot rows in the panel.
# The addendum is a PROMPT INSTRUCTION, not a fence; handing that sentence a dated number is exactly what
# D1 refused.
def test_an_outlook_turn_renders_no_positioning_row(monkeypatch):
    monkeypatch.setattr(cq, "load_map", lambda: {"cot_mm_positioning": _COT_ROW})
    calls: list = []
    block, trace, _rt = cq.quantify(_sg([_node()]), None, qfn=_qfn, asof=ASOF, near=None,
                                    extra_number_calls=calls, pace=True, outlook=True)
    assert block is None and trace == [] and calls == []
    # ... and the FENCED twin of the identical turn DOES render, so this is a LANE rule and not a
    # regression that silently killed the leg everywhere.
    fenced_block, fenced_trace, _rt2, fenced_calls = _run(monkeypatch=monkeypatch)
    assert fenced_block is not None and fenced_trace and fenced_calls


def test_the_outlook_gate_is_positioning_only(monkeypatch):
    """The carve-out fences POSITIONING out of the outlook lane -- it does not turn the cascade off. A PSD
    export leg on the same outlook turn renders exactly as it does on a fenced one."""
    monkeypatch.setattr(cq, "load_map", lambda: {"export": {
        "table": "silver_psd", "metric": "exports_mt", "agg": "latest",
        "period_type": "marketing_year", "narrate_unit": "MMT", "scale": 0.000001}})
    node = SimpleNamespace(contract="corn_cbot", id="export_ban",
                           prior={"silver_ref": "export", "region": "US"},
                           evidence=[{"date": "2012-06-01", "source": "usda_gain", "source_key": "k",
                                      "text": "t"}])
    calls: list = []
    block, _tr, _rt = cq.quantify(_sg([node]), None, qfn=lambda s: [{"value": "10000000",
                                                                    "market_year": 2012}],
                                  asof=ASOF, near="2012", extra_number_calls=calls, pace=True,
                                  outlook=True)
    assert block is not None and calls
