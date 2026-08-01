"""PRICE_OBSERVABILITY W4 -- v2 silver_cot (CFTC managed-money positioning) acceptance gates.

SYNTHETIC fixtures only; AWS-free, judge-free, no model calls. silver_cot is registered read-side under
the SAME leakage-safe numbers harness as PSD/WASDE/ESR/pink_sheet. This file locks the W4.1 card + F010
wiring + intent routing + the register/engine fences that ACTIVATE once silver_cot is a numbers table:

Covers: the W4.1 registry card shape + PIT knobs; every metric name resolves to a physical F010 column
(never invent a column); the wide-parity first-four ordering (non-vacuous corn_cbot panel); the signed
mm_pct_oi semantics + the sigma z-metrics; the publication-lag-6 as-of guard (data_date semantics) in SQL
AND in the apply_pit_filter oracle; R7 metric-desc register cleanliness + R9 no-engine-ref (check_cot_
register); reconcile + contract-check coupling (consumers=both, in NUMBERS_TABLES, in C002 scope);
the P1_TABLES / SAMPLE_COMMODITY / Branch-A wiring (corn_cbot is the CONTRACT slug -- the vacuous-panel
trap); the intent-lexicon positioning routing (numbers lane, WITHOUT breaking _REASON asks); and the four
W4 deck rows (every row an expected_intent pin; the engine-fork negative is a realizable cascade_fired:false).
"""
from __future__ import annotations

import yaml

from leviathan.graphrag import config_check as CC_LINT
from leviathan.graphrag import intent as IT
from leviathan.graphrag.numbers import contract_check as CC
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import load_registry

TID = "silver_cot"


def _ts():
    return load_registry().get(TID)


# -- SYNTHETIC positioning fixture (illustrative; golden real-parquet rows are a W4.1 rider). report_date is
#    a Tuesday DATA date; two reports straddle the ~6d publication lag. ----------------------------------------
COT_ROWS = [
    {"report_date": "2024-05-28", "leviathan_slug": "corn_cbot", "open_interest": 1_500_000,
     "mm_long": 300_000, "mm_short": 250_000, "mm_spread": 40_000, "mm_net": 50_000,
     "mm_pct_oi": 3.3, "mm_net_z_3yr": 1.2, "mm_pct_oi_z_3yr": 1.1},
    {"report_date": "2024-06-11", "leviathan_slug": "corn_cbot", "open_interest": 1_520_000,
     "mm_long": 260_000, "mm_short": 320_000, "mm_spread": 41_000, "mm_net": -60_000,
     "mm_pct_oi": -3.9, "mm_net_z_3yr": -0.8, "mm_pct_oi_z_3yr": -0.7},
]


def _pit(rows, ts, **q):
    return Q.apply_pit_filter(rows, Q.NumberQuery(**q), ts)


# ======================================================================================================
# W4.1 registry card shape + PIT knobs.
# ======================================================================================================
def test_cot_registered_shape_and_knobs():
    ts = _ts()
    assert ts.shape == "wide"
    assert ts.commodity_col == "leviathan_slug"                    # CONTRACT slugs (corn_cbot, ...)
    assert ts.country_col is None
    assert ts.period_type == "date" and ts.date_col == "report_date"
    assert ts.knowledge_semantics == "data_date"
    assert ts.knowledge_date_col == "report_date"
    assert ts.publication_lag_days == 6                            # S2.F6 (Tue data, Fri release, +6 holiday-safe)


def test_cot_metric_order_first_four_for_wide_parity():
    """The wide pg-parity sampler takes only the FIRST FOUR metrics (numbers_parity.py:97). All four are on
    the SAME corn_cbot rows, so the panel is non-vacuous (unlike a wrong base-name sample)."""
    ts = _ts()
    assert list(ts.metrics)[:4] == ["open_interest", "mm_long", "mm_short", "mm_spread"]
    assert len(ts.metrics) == 8


def test_cot_metric_columns_exist_aws_free():
    """Never invent a column: every declared metric must be a PHYSICAL column of the F010 card (a shape=wide
    registry-membership check, no DISTINCT probe)."""
    ts = _ts()
    cols = CC._f010_column_fn()(CC._physical(ts))
    assert cols, "F010 silver registry columns unavailable"
    missing = set(ts.metrics) - cols
    assert missing == set(), f"declared metrics absent from F010 physical columns: {sorted(missing)}"


def test_cot_mm_pct_oi_is_signed_percent_semantics():
    ts = _ts()
    m = ts.metrics["mm_pct_oi"]
    assert m.unit == "pct of OI (signed)"
    assert "SIGNED percent" in m.desc and "negative = net short" in m.desc   # S2.F9: never "pct of OI" bare


def test_cot_z_metrics_served_as_sigma():
    ts = _ts()
    for z in ("mm_net_z_3yr", "mm_pct_oi_z_3yr"):
        assert ts.metrics[z].unit == "sigma vs 3-yr mean"
    assert ts.metrics["open_interest"].unit == "contracts"
    assert ts.metrics["mm_net"].unit == "contracts"


# ======================================================================================================
# Publication-lag-6 as-of guard (data_date semantics) -- SQL text AND the apply_pit_filter oracle.
# ======================================================================================================
def test_cot_lag_6_offset_emitted_in_guard():
    """The as-of guard shifts back by publication_lag_days (asof 2024-06-14 - 6 = 2024-06-08), so a Tuesday
    positions report is not citable ~6 days early -- a PIT leak without it."""
    ts = _ts()
    sql = Q.build_sql(Q.NumberQuery(table=TID, metric="mm_net", asof="2024-06-14",
                                    commodity="corn_cbot"), ts)
    assert "CAST(report_date AS varchar) <= '2024-06-08'" in sql
    assert "leviathan_slug = 'corn_cbot'" in sql


def test_cot_pit_oracle_withholds_report_inside_the_lag():
    """A report_date within the ~6d lag of asof is NOT yet knowable; an older one IS. At asof 2024-06-14
    (cutoff 2024-06-08) the 2024-06-11 report is invisible and 2024-05-28 serves; at asof 2024-06-20
    (cutoff 2024-06-14) the June-11 report appears -- the oracle matches build_sql's cutoff literal."""
    ts = _ts()
    early = _pit(COT_ROWS, ts, table=TID, metric="mm_net", asof="2024-06-14", commodity="corn_cbot")
    assert [r["report_date"] for r in early] == ["2024-05-28"]     # June-11 not yet public -> never leaks
    later = _pit(COT_ROWS, ts, table=TID, metric="mm_net", asof="2024-06-20", commodity="corn_cbot")
    assert "2024-06-11" in {r["report_date"] for r in later}       # ...visible once the lag elapses


# ======================================================================================================
# R7 (metric-desc register cleanliness) + R9 (no engine ref) -- ACTIVE now that silver_cot is registered.
# ======================================================================================================
def test_cot_register_fence_green_r7_r9():
    """check_cot_register: R9 (no cascade_map ref at silver_cot) + R7 (no banned valuation/flow word in any
    metric desc). Vacuous until W4 registered the table -- now it FIRES and must be clean."""
    assert CC_LINT.check_cot_register() == []


def test_cot_metric_descs_carry_no_banned_register_words():
    from leviathan.graphrag import register as REG
    ts = _ts()
    for mname, m in ts.metrics.items():
        assert REG.count_valuation_words(m.desc) == 0, mname
        assert REG.count_flow_words(m.desc) == 0, mname


def test_cot_enters_no_ENGINE_lane():
    """R9 AS AMENDED (C1/D1, 2026-08-01): positioning is HISTORICAL CONTEXT ONLY, which is now a
    SPLIT rather than a blanket ban -- silver_cot may sit in cascade_map as the narrow past-tense
    context leg, and may never be a fork/regime-marker ref or a chain/complex/transmission hop. The
    assertion moves from `_check_no_engine_ref` (which would fail the build the day the context ref
    lands) to the lane check that encodes the split. `_check_no_engine_ref` itself is UNCHANGED and
    still carries R4/F047; see tests/unit/test_config_check.py for the amended lane's own cases.

    UPDATED 2026-08-01 when C1's ref actually landed. The old back-pointer half asserted
    `cascade_ref is None`, which encoded the PRE-split absolute ("cot enters no lane at all") and was
    true only while the map row was missing. The amended doctrine is not "no ref" but "ONE ref, of ONE
    shape", so the assertion is now that the back-pointer names THAT ref: a null would mean the context
    leg vanished, and any OTHER ref would mean a second, unratified positioning row exists."""
    from leviathan.graphrag.numbers import cascade as csc
    from leviathan.silver import registry as SR
    assert CC_LINT._check_positioning_lane() == []
    # the silver registry's back-pointer names the ONE admitted ref, and that ref is the CONTEXT shape
    assert SR.load_registry().table(TID).get("cascade_ref") == \
        "configs/graphrag/numbers/cascade_map.yaml#cot_mm_positioning"
    row = (csc.load_map() or {}).get("cot_mm_positioning")
    assert row is not None and row["table"] == TID
    assert csc.positioning_context_violations(row) == []           # ... it is context, not an engine leg
    assert row["leg_mode"] == "current"                            # no era legs -> the fork path is closed


def test_the_lane_check_still_reds_every_engine_lane(monkeypatch):
    """THE TEETH, kept explicit rather than implied by the green above: the amended R9 must still FAIL the
    build the moment positioning is given an engine position. Each case below is one lane, driven through
    the SAME `_check_positioning_lane` the build runs, so a relaxation anywhere reds here."""
    from leviathan.graphrag import complex_map as cxm
    from leviathan.graphrag.numbers import cascade as csc
    ctx = (csc.load_map() or {})["cot_mm_positioning"]

    def _errs():
        return CC_LINT._check_positioning_lane()

    # (a) cascade_map, WRONG SHAPE -- an era leg is the cross-era fork backbone
    monkeypatch.setattr(csc, "load_map", lambda: {"cot_mm_positioning": {**ctx, "leg_mode": "era"}})
    assert any("R9 cascade_map" in e for e in _errs())
    # ... a marketing-year window, a reroute trade metric, and a 0/1 regime marker are each refused too
    for tweak in ({"period_type": "marketing_year"}, {"metric": "exports_mt"}, {"narrate_unit": "flag"}):
        monkeypatch.setattr(csc, "load_map", lambda t=tweak: {"cot_mm_positioning": {**ctx, **t}})
        assert any("R9 cascade_map" in e for e in _errs()), tweak
    # (b) chain_map -- a hop is an engine position whatever shape the underlying row has
    monkeypatch.setattr(csc, "load_map", lambda: {"cot_mm_positioning": ctx})
    monkeypatch.setattr(csc, "load_chain_map",
                        lambda: [{"id": "c1", "hops": [{"ref": "cot_mm_positioning"}]}])
    assert any("R9 chain_map" in e for e in _errs())
    # (c) complex_map -- a relative-value leg, material or not
    monkeypatch.setattr(csc, "load_chain_map", lambda: [])
    pair = type("P", (), {"id": "p1", "side_a": {"ref": "cot_mm_positioning"}, "side_b": {"ref": "export"}})
    monkeypatch.setattr(cxm, "iter_all_pairs", lambda: [pair()])
    assert any("R9 complex_map" in e for e in _errs())
    # (d) transmission_map -- a link carrying that pair
    monkeypatch.setattr(csc, "load_transmission_map",
                        lambda: [{"id": "x1", "links": [{"pair_id": "p1"}]}])
    assert any("R9 transmission_map" in e for e in _errs())


# ======================================================================================================
# Reconcile + contract-check coupling (consumers=both, in NUMBERS_TABLES, in C002 scope).
# ======================================================================================================
def test_cot_in_numbers_tables_tuple_and_reconciles_clean():
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    assert TID in RC.NUMBERS_TABLES
    reg = SR.load_registry()
    divs = [d for d in RC.reconcile_numbers(reg) if d.table == TID]
    assert divs == [], [d.detail for d in divs]
    c = reg.table(TID)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert c["knowledge_semantics"] == "data_date" and c["publication_lag_days"] == 6
    assert c["freshness_sla"]["max_lag_days"] == 10


def test_cot_now_in_numbers_scope_for_contract_check():
    """Dropped from the feature-only set: silver_cot is now a numbers table, so contract_check sees it in
    scope (the FR-001 feature-only footer path no longer owns it)."""
    assert TID in CC._numbers_table_ids(load_registry())


# ======================================================================================================
# P1_TABLES / SAMPLE_COMMODITY / Branch-A wiring -- corn_cbot is the CONTRACT slug (the vacuous-panel trap).
# ======================================================================================================
def test_cot_in_pg_mirror_p1_tables():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert TID in P1_TABLES


def test_cot_parity_sample_is_the_contract_slug_not_bare_base():
    """S3.F4: silver_cot.commodity_col is leviathan_slug, which holds CONTRACT slugs (_MARKET_TO_SLUG). The
    parity sample MUST be corn_cbot -- bare 'corn' matches zero rows (the gold_weather_z vacuous-panel trap)."""
    from jobs.utils.numbers_parity import SAMPLE_COMMODITY
    assert SAMPLE_COMMODITY[TID] == "corn_cbot"
    assert SAMPLE_COMMODITY[TID] != "corn"


def test_cot_is_branch_a_twelfth_pg_mirror_table():
    from jobs.audit import silver_rebuild_gate as g
    from leviathan.silver import registry as SR
    silver = SR.load_registry()
    assert TID in g.PG_MIRROR_TABLES
    assert g.select_branch(TID, silver_reg=silver) == g.BRANCH_A
    # cot is the 12th pg-mirror table; silver_futures_prices (SEAM-C) is the 13th; WIRING WAVE-1 added
    # silver_noaa_iod + silver_conab_coffee (2026-07-23) as the 14th/15th, Card C
    # silver_sagis_weekly_exports as the 16th once its catalog ALTER landed (P1_TABLES wired it in),
    # and T2b gold_pattern_records (2026-07-24) as the 17th (ledger mirror, flag-off serving).
    assert len(g.PG_MIRROR_TABLES) == 17


# ======================================================================================================
# Intent-lexicon positioning routing (S3.F5/S2.F10): positioning asks reach the numbers lane WITHOUT
# breaking the existing _REASON asks.
# ======================================================================================================
def test_positioning_vocab_routes_numbers_lane():
    # each of the added positioning cues fires _NUM and NOT _REASON -> numbers_only (pure lookup).
    for q in ("What was managed-money net length in corn as of March 2024?",
              "What is managed-money positioning in corn right now?",
              "What is corn open interest?",
              "Are funds crowded in soybeans?"):
        d = IT.classify_intent(q)
        assert d["intent"] == "numbers_only", (q, d)
        assert d["needs_numbers"] and not d["needs_reasoning"], q


def test_net_long_short_stay_reasoning_capable_but_reach_numbers():
    # "net long"/"net short" are ALSO _REASON triggers, so they now fire BOTH cues -> hybrid: reasoning is
    # NOT dropped (an additive capability) and numbers is REACHED (needs_numbers). No LLM call needed.
    for q in ("Is corn managed money net long?", "How stretched is the net short in soybeans?"):
        d = IT.classify_intent(q)
        assert d["needs_numbers"], q                               # positioning reaches the numbers lane

    # REGRESSION: the additions must NOT hijack existing pure-reasoning / hybrid asks.
    assert IT.classify_intent("Why is a strong dollar bearish for soybeans?")["intent"] == "reasoning"
    assert IT.classify_intent("Given low ending stocks, is soybeans a buy?")["intent"] == "hybrid"
    assert IT.classify_intent("What were Argentina corn exports in 2023?")["intent"] == "numbers_only"
    # the trivial-turn backstop stays conservative (a positioning cue vetoes to fall-through, never mis-cans).
    assert IT.is_trivial("hi") == "greeting" and IT.is_trivial("managed money positioning") is None


def test_analogue_framing_positioning_routes_hybrid():
    # a reasoning cue + a positioning cue both fire -> hybrid (positioning cited as PAST-TENSE context).
    d = IT.classify_intent("How does today's managed-money positioning in corn compare with the 1988 drought analogue?")
    assert d["intent"] == "hybrid" and d["needs_numbers"] and d["needs_reasoning"]


# ======================================================================================================
# W4 deck rows -- every row an expected_intent pin; the engine-fork negative is a REALIZABLE cascade_fired:false.
# ======================================================================================================
def _deck():
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[1].parent / "configs" / "graphrag" / "eval_queries_v4_cascade.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))["queries"]


def test_w4_deck_rows_present_with_intent_pins():
    rows = {q["id"]: q for q in _deck()}
    ids = ("positioning_corn_net_length", "positioning_funds_crowded_soy",
           "positioning_corn_no_fork", "positioning_corn_analogue")
    for rid in ids:
        assert rid in rows, rid
        assert rows[rid].get("expected_intent"), rid              # W4.2: EVERY W4 row pins expected_intent
    # (a) dated level ask + (b) the R8 register trap route numbers_only with a raw banned_flow:0 pin.
    assert rows["positioning_corn_net_length"]["expected_intent"] == "numbers_only"
    assert rows["positioning_funds_crowded_soy"]["expect"]["banned_flow"] == 0
    # (d) analogue framing routes hybrid.
    assert rows["positioning_corn_analogue"]["expected_intent"] == "hybrid"


def test_w4_engine_fork_negative_is_realizable():
    """(c) a positioning ask pins cascade_fired:false and the pin is NON-STALE (check_pin_realizability
    green). TWO things changed under it on 2026-08-01 and the old form encoded both mistakes:

      * the row DECLARED `cot_mm_positioning`, which is a SILVER_REF and not a driver id -- corn's driver
        is `managed_money_positioning`, CARRYING that ref. `cascade_census._driver` matches on `d.id`, so
        the declaration resolved to nothing and `query_realizable` returned False for a reason that had
        nothing to do with the map. That was the fail-OPEN C1 item 4(b) closed: an unresolvable declared
        id now ERRORS rather than reading as "not fireable".
      * with the id fixed AND C1's context ref mapped, the driver IS topologically fireable, so
        `query_realizable` is now True. The pin stays FALSE because the row is `expected_intent:
        numbers_only` and the cascade engine never runs on that lane (`run_numbers_only` never reaches
        `_answer_l2`): the lint's stale-NEGATIVE arm compares pure topology to an OUTCOME, which is only
        a valid comparison where the engine can run.

    So this test now pins the NEW semantics: realizable-but-not-on-this-lane, still green."""
    from leviathan.graphrag.numbers import cascade_census as cc
    row = next(q for q in _deck() if q["id"] == "positioning_corn_no_fork")
    assert row["expect"]["cascade_fired"] is False
    assert row.get("cascade_drivers"), "cascade_fired pin requires a cascade_drivers declaration"
    assert row["cascade_drivers"] == ["managed_money_positioning"]   # a DRIVER id, never a silver_ref
    assert cc._driver(row["contract"], "managed_money_positioning") is not None
    assert cc._driver(row["contract"], "cot_mm_positioning") is None  # the old declaration, unresolvable
    assert cc.query_realizable(row) is True                      # topologically fireable since C1's ref
    assert row["expected_intent"] == "numbers_only"               # ... but the engine never runs here
    assert CC_LINT.check_pin_realizability() == []


def test_the_stale_positive_arm_is_not_weakened_by_the_lane_skip(monkeypatch):
    """The lane skip is NARROW and one-directional. A numbers_only row pinning `cascade_fired: TRUE` is
    still an error -- the more so, since the engine cannot fire there at all -- and an unresolvable
    declared driver id is an error on EVERY lane. Without this the F12 judgment call would read as a
    blanket exemption for numbers_only rows."""
    row = next(q for q in _deck() if q["id"] == "positioning_corn_no_fork")

    def _deck_of(q):
        return {"queries": [q]}

    # stale-POSITIVE on the same numbers_only row: pins true, but nothing is realizable -> still errors
    dead = {**row, "cascade_drivers": ["managed_money_positioning"],
            "expect": {**row["expect"], "cascade_fired": True}}
    monkeypatch.setattr(CC_LINT, "_load", lambda _n: _deck_of(dead))
    monkeypatch.setattr("leviathan.graphrag.numbers.cascade_census.query_realizable", lambda q: False)
    assert any("cascade_fired:true" in e for e in CC_LINT.check_pin_realizability())
    # an unresolvable declared id errors regardless of lane or pin direction
    monkeypatch.undo()
    bad = {**row, "cascade_drivers": ["cot_mm_positioning"]}
    monkeypatch.setattr(CC_LINT, "_load", lambda _n: _deck_of(bad))
    errs = CC_LINT.check_pin_realizability()
    assert any("resolves to NO driver" in e for e in errs), errs


# ======================================================================================================
# R7 (metric family) + R10 (suggester catalog source) go NON-VACUOUS now that silver_cot is registered.
# ======================================================================================================
def test_cot_r7_metrics_limited_to_level_or_z_families():
    """R7: every silver_cot metric is a DATED LEVEL (contract/OI count or signed pct-of-OI) or a Z-SCORE --
    never a forecast/percentile-projection family, and no forward-looking metric name."""
    from leviathan.graphrag.numbers import stats as ST
    ts = _ts()
    for mname, m in ts.metrics.items():
        assert not ST.is_banned_name(mname), mname
        assert (m.unit in CC_LINT._COT_LEVEL_UNITS or CC_LINT._is_cot_z_unit(m.unit)), (mname, m.unit)


def test_cot_r10_suggester_catalog_excludes_positioning():
    """R10: the suggester's answerable-fundamentals catalog source (server._SUGGEST_METRICS) is FOUND (the
    lint is non-vacuous) and names no positioning-table metric nor positioning vocabulary."""
    cat = CC_LINT._suggest_catalog_metric_text()
    assert cat, "R10 non-vacuous: _SUGGEST_METRICS catalog source must be discoverable"
    low = cat.lower()
    ts = _ts()
    for mname in ts.metrics:
        assert mname.lower() not in low and mname.replace("_", " ").lower() not in low, mname
    for tok in ("managed money", "managed-money", "net long", "net short", "positioning"):
        assert tok not in low, tok


def test_cot_register_r10_included_in_green_gate():
    """The consolidated check_cot_register (R9 + R7 + R10) is clean -- the shipping-gate assertion."""
    assert CC_LINT.check_cot_register() == []
