"""CYCLE-8 (2026-08-08) repair-integrity pins -- the blocking class gate-5 of the D-CW/D-PQ probe shipped.

Gate-5 (commit 6492e9f5) confirmed the cycle-7 fixes (P1/P3/P4 hold, the gate-4 over-mint class is dead,
zero dangling markers, 7/7 unlocks) and shipped a NEW blocking class: THE VERIFIER'S REPAIR PATH CORRUPTS
PROSE. Three answers reached the reader with a number the verifier itself invented:

    dcw_p1 dcw_us_ethanol_margin     "below the 5-year mean [N9]"      -> "below the 0.344931-year mean [N9]"
    dcw_p2 dcw_gas_nitrogen_squeeze  "moves above its 5-year mean"     -> "moves above its 453.1-year mean"
    dcw_p2 dcw_palm_stocks_print     "roughly 2 percent below the ..." -> "roughly 1,629,801 percent below ..."

THE RCA VERDICT (falsified, not assumed). `verify.py` is BYTE-IDENTICAL between gate-4 (b91181d5) and
gate-5 (6492e9f5), and `verify_citations` runs at answer.py:2080 -- BEFORE `_resolve_number_handles`
(answer.py:2102) -- so cycle-7's FIX-2 splice/adjacency work cannot reach the verifier's input at all.
Replaying every gate-4 and gate-5 draft through the SHIPPED code reproduces all three corruptions from the
gate-5 drafts and ZERO from the gate-4 drafts. The class is LATENT, not new: the trigger (a sentence whose
ONLY claim numeral is a digit-form duration, beside an [N] handle whose pool holds one value) simply did
not occur in the gate-4 bodies. Gate-4 DID write "5-year" (dcw pass1 `dcw_macro_on_soy`, pass2
`dcw_palm_stocks_print`) -- always alongside a second numeral, which sent those sentences to the
ambiguity refusal instead of the rewrite.

  FIX 1  (the SECOND sanctioned verify amendment, scope-limited to false-positive reduction in claim
         extraction) digit-form DURATION MODIFIERS and ORDINALS are not claim magnitudes.
  FIX 2  the repair path grows three fences: (a) never rewrite a NON-VALUE slot, (b) the unit-class fence
         reads the CARD's unit when the row carries none, (c) NO LAUNDERING -- a prose repair is counted
         and recorded, so a rewritten figure can never score as a clean row.
  FIX 3  the completion mint's 2-dp bucket stops bypassing the precision gate, and one stated value mints
         at most ONE row per call.
  FIX 4  the eval report states the LIVE denominator instead of silently shrinking it.

Every fixture is replayed from gate-4 / gate-5 evidence: the drafts, the `strip_audit` rows and the
`served_rows` projections of the five gate-5 runs.
"""
from __future__ import annotations

from leviathan.graphrag import citations as cit
from leviathan.graphrag import eval as ev
from leviathan.graphrag import orchestrator as orc
from leviathan.graphrag import verify as vf


def _call(table, metric, vals, unit=None, commodity=None, shown=None):
    """A served numbers call in the shape `verify` reads it."""
    c = {"query": {"table": table, "metric": metric, "commodity": commodity, "asof": "2026-08-06"},
         "status": "ok",
         "rows": [{"value": str(v), "unit": unit, "period": None, "knowledge_date": "2026-06-01"}
                  for v in vals]}
    if shown is not None:
        c["shown"] = shown
    return c


def _verify(tldr, mechanism, calls):
    st = {"tldr": tldr, "mechanism": mechanism, "sources": []}
    rep = vf.verify_citations(st, [], calls)
    return st, rep


# ======================================================================================================
# FIX 1 -- DURATION/ORDINAL SLOTS ARE NOT CLAIM MAGNITUDES (the second sanctioned amendment)
# ======================================================================================================

def test_fix1_five_year_mean_is_not_a_claim():
    """gate-5 dcw pass1 `dcw_us_ethanol_margin`, the exact draft line."""
    assert vf._claim_numbers_in("- **Natural gas prices**: currently below the 5-year mean [N9];") == []


def test_fix1_every_digit_duration_modifier_shape():
    """With and without the hyphen, singular and plural, across the whole duration vocabulary."""
    for s in ("the 5-year mean", "the 5 year mean", "a 3-month average", "a 12-week moving average",
              "the 30-day window", "a 2-quarter lag", "its 36-month history", "the 90-day change",
              "a 5-years mean", "the 2 quarters lookback", "the 4-qtr trailing figure"):
        assert vf._claim_numbers_in(s) == [], s


def test_fix1_ordinal_is_not_a_claim():
    assert vf._claim_numbers_in("the 3rd consecutive month of decline") == []
    assert vf._claim_numbers_in("in the 2nd half of the season") == []


def test_fix1_percentile_ordinals_stay_claims_the_measured_exclusion():
    """MEASURED, not defensive: this estate serves percentile_rank metrics, so '76.8th percentile' states
    the CITED ROW'S OWN VALUE. Exempting it cost 3 legitimately-cited handles across the gate-4/gate-5
    replay (gate-4 `ab_rec_malaysia_stocks` x2, gate-5 `dcw_urea_zscore` x1)."""
    assert vf._claim_numbers_in("at the 76.8th percentile of their historical range [N3]") == [76.8]
    assert vf._claim_numbers_in("in roughly the 66th percentile of its distribution [N4]") == [66.0]


def test_fix1_polarity_percent_claims_are_untouched():
    """The CAREFUL clause: a percent magnitude is a real quantitative claim and keeps stripping when wrong.
    The palm corruption is fixed at the REPAIR fence (FIX 2b), never by exempting percent."""
    assert vf._claim_numbers_in("output grew 5 percent year on year") == [5.0]
    assert vf._claim_numbers_in("running roughly 2 percent below the five-year average") == [2.0]
    assert vf._claim_numbers_in("the CNY/USD 90-day change was only -0.76%") == [0.76]   # 90 exempt, 0.76 not


def test_fix1_polarity_a_second_numeral_beside_the_duration_survives():
    """'5-year low of 9.48' -- the 9.48 is still a claim while the 5 is not."""
    assert vf._claim_numbers_in("a 5-year low of 9.48 MMT") == [9.48]
    assert vf._claim_numbers_in("with a 5-year z-score of -0.31 [N2]") == [0.31]


def test_fix1_duration_noun_in_HEAD_position_is_still_a_claim():
    """The deliberate limit. 'the last 5 months [N11]' citing a pace_streak row IS the streak's quantity --
    exempting it would un-verify the one lane where a duration numeral is genuinely checkable."""
    assert vf._claim_numbers_in("the anomaly has risen in each of the last 5 months [N11]") == [5.0]
    assert vf._claim_numbers_in("the CNY has moved only marginally over the past 90 days [N7]") == [90.0]
    assert vf._claim_numbers_in("risen for 5 consecutive months") == [5.0]


def test_fix1_leaves_every_pre_existing_exemption_and_charge_alone():
    assert vf._claim_numbers_in("exports hit 1950 MMT") == [1950.0]          # unit-suffixed year
    assert vf._claim_numbers_in("in January 2026, but") == []                # bare year
    assert vf._claim_numbers_in("the 1998-99 season") == []                  # year + range tail
    assert vf._claim_numbers_in("as of 25 July 2026") == []                  # date day
    assert vf._claim_numbers_in("a fabricated 23.5 MMT print") == [23.5]     # a magnitude still strips
    assert vf._claim_numbers_in("5 thousand tonnes") == [5.0]                # not an ordinal ('th' of 'thousand')
    assert vf._claim_numbers_in("85 th percentile") == [85.0]                # ordinal suffix must be GLUED


# ======================================================================================================
# FIX 2 -- THE REPAIR-PATH FENCES, ON THE THREE REAL CORRUPTION SHAPES
# ======================================================================================================

def test_fix2_corruption_1_ethanol_margin_no_rewrite():
    """gate-5 dcw pass1 `dcw_us_ethanol_margin`, report line ~573. The shipped code rewrote the '5' with
    [N9]'s row value; the served row is `silver_pink_sheet.natural_gas_us_usd_mmbtu_zscore_5yr`."""
    calls = [_call("silver_pink_sheet", "natural_gas_us_usd_mmbtu_zscore_5yr",
                   ["-0.344930511713658"])] * 9
    st, rep = _verify("", "- **Natural gas prices**: currently below the 5-year mean [N9];", calls)
    assert "0.344931" not in st["mechanism"]
    assert st["mechanism"] == "- **Natural gas prices**: currently below the 5-year mean [N9];"
    assert rep["repaired"] == 0 and rep["repairs"] == []
    assert rep["by_rule"] == {}


def test_fix2_corruption_2_gas_nitrogen_squeeze_no_rewrite():
    """gate-5 dcw pass2 `dcw_gas_nitrogen_squeeze` ~L156: '453.1-year mean' shipped from the urea level."""
    calls = [_call("silver_pink_sheet", "urea_usd_mt", ["453.1"])] * 11
    body = ("- **Urea z-score.** Watch whether urea [N11] moves above its 5-year mean alongside gas.")
    st, rep = _verify("", body, calls)
    assert "453.1-year" not in st["mechanism"] and st["mechanism"] == body
    assert rep["repaired"] == 0


def test_fix2b_corruption_3_palm_MT_may_not_enter_a_percent_slot():
    """gate-5 dcw pass2 `dcw_palm_stocks_print` ~L325 -- the unit-class breach AND the laundering.

    The served MPOB rows carry `unit: null`, so cycle-7's row-unit fence read nothing and failed OPEN.
    The card declares `silver_mpob.production_cpo_mt = MT`; the slot is a percent. The repair is refused,
    the sentence takes the fail-closed whole-drop, and the answer no longer scores strips=0."""
    calls = [_call("silver_mpob", "closing_stocks_palm_oil_mt", ["2309474.0"]),
             _call("silver_mpob", "production_cpo_mt", ["1629801.0"])]
    body = ("On output, MPOB data showed CPO production was running roughly 2 percent below the "
            "five-year average as of October 2024, though the April 2026 output figure itself [N2] "
            "should be read in seasonal context.")
    st, rep = _verify("", body, calls)
    assert "1,629,801 percent" not in st["mechanism"] and "1629801" not in st["mechanism"]
    assert rep["repaired"] == 0
    assert rep["stripped"] == 1 and rep["by_rule"] == {"number_mismatch": 1}


def test_fix2b_registry_unit_class_reads_the_card_when_the_row_is_bare():
    assert vf._registry_unit_class(_call("silver_mpob", "production_cpo_mt", ["1629801.0"])) == "mass"
    assert vf._registry_unit_class(
        _call("silver_pink_sheet", "natural_gas_eu_usd_mmbtu_zscore_5yr", ["-0.3"])) == "index"
    # fail-open at every step: an unknown table, an undeclared unit, a fixture query -> None, repair as before
    assert vf._registry_unit_class(_call("not_a_table", "not_a_metric", ["1"])) is None
    assert vf._registry_unit_class(_call("silver_wasde", "avg_farm_price", ["4.55"])) is None
    assert vf._registry_unit_class({}) is None


def test_fix2b_d2_a_percent_slot_is_fenced_WITHOUT_the_registry():
    """(d) fails open when the card is unreadable, which would restore the palm corruption verbatim. (d2)
    reads the call's own METRIC NAME: only a percent-denominated call may write a percent slot."""
    slot = "running roughly 2 percent below the average [N1]"
    assert vf._num_repair(slot, 1, [_call("no_such_table", "production_cpo_mt", ["1629801.0"])]) is None
    assert vf._num_repair(slot, 1, [_call("no_such_table", "", ["1629801.0"])]) is None
    # ...and a percent-denominated call still repairs its own slot
    pct = _call("no_such_table", "ending_stocks_mt_pct", ["5.11"])
    rep = vf._num_repair("stocks fell 4.2 percent on the year [N1]", 1, [pct])
    assert rep is not None and rep[2] == "5.11"


def test_fix2b_unit_class_lead_reads_the_head_of_a_unit_PHRASE():
    assert vf._unit_class_lead("sigma vs 5-yr mean") == "index"
    assert vf._unit_class_lead("BRL per USD (FRED)") == "money"
    assert vf._unit_class_lead("MT") == "mass"
    assert vf._unit_class_lead("") is None and vf._unit_class_lead("furlongs") is None


def test_fix2a_non_value_slot_fence_is_independent_of_the_extractor():
    """The second lock. Even with the claim numeral forced back into view (an env-varied pool, a future
    extractor widening), `_num_repair` refuses to write into a window/position/share slot."""
    z = _call("silver_pink_sheet", "natural_gas_us_usd_mmbtu_zscore_5yr", ["-0.344930511713658"])
    assert vf._num_repair("currently below the 5-year mean [N1]", 1, [z]) is None
    assert vf._num_repair("at the 3rd consecutive print [N1]", 1, [z]) is None
    assert vf._num_repair("2 percent of the crop [N1]", 1, [z]) is None


def test_fix2a_a_genuine_value_slot_still_repairs():
    """The fence is SCOPED. A count row named by a duration noun in HEAD position is a value slot and must
    keep repairing -- refusing it would send a repairable sentence to the whole-drop path."""
    streak = {"query": {"table": "gold_cascade", "metric": "oni_anom_pace_streak"}, "status": "ok",
              "shown": ["9"], "rows": [{"value": "9", "unit": "months"}]}
    rep = vf._num_repair("the anomaly has risen in each of the last 5 months [N1]", 1, [streak])
    assert rep is not None and rep[2] == "9"


def test_fix2c_a_prose_repair_is_counted_and_recorded_never_laundered():
    """A repair that legitimately fires carries an always-present, numerals-only record: `repaired` and
    `repairs`, neither gated on GRAPHRAG_STRIP_AUDIT.

    CYCLE-8 REVIEW (2026-08-08) MAJOR 5 -- RESTATED, and the reason is the finding. This pin originally used
    gate-4 `dcw_gas_nitrogen_squeeze`'s "if this crosses above +1 sigma" as its positive control, which is
    exactly the CONDITIONAL THRESHOLD the review found still corrupting prose (the rewrite made the sentence
    say "if this crosses above the value it already has"). That shape is now fail-closed, so it can no
    longer serve as the control for the RECORD path. The declarative twin -- same call, same handle, same
    single numeral, no conditional -- is a genuine repair and is what this pin exercises. The refusal of the
    conditional form is pinned separately below."""
    call = _call("agent_lane", "urea_z", ["-0.195159"])
    st, rep = _verify("", "- **Urea z-score [N1]:** the reading sits at 1 sigma right now.", [call])
    assert "0.195159" in st["mechanism"]                      # the repair DID happen
    assert rep["repaired"] == 1
    # CYCLE-9 REVIEW (2026-08-08), MAJOR 4: the row is NEGATIVE and the slot carries no sign of its own,
    # so the replacement now carries the row's ("0.195159" asserted a positive z-score the row denies).
    assert rep["repairs"] == [{"field": "mechanism", "rule": "number_mismatch_repaired",
                              "from": "1", "to": "-0.195159"}]
    assert rep["by_rule"]["number_mismatch_repaired"] == 1


def test_fix2c_the_carriers_are_always_present_and_empty_on_a_clean_answer():
    _st, rep = _verify("", "Nothing numeric here at all.", [])
    assert rep["repaired"] == 0 and rep["repairs"] == []


def test_fix2c_a_repair_swallowed_by_a_whole_sentence_drop_is_not_recorded():
    """`repairs` counts what the READER receives: an edit inside a coalesced drop span never ships."""
    a = _call("agent_lane", "m_a", ["7.0"])
    b = _call("agent_lane", "m_b", ["11.0"])
    st, rep = _verify("", "The level was 3 [N1] and separately 4 and 5 [N2].", [a, b])
    assert rep["repaired"] == 0 and rep["repairs"] == []


# ======================================================================================================
# FIX 3 -- THE 2-dp BUCKET MINT PATH
# ======================================================================================================

def _fx_call(vals):
    """gate-5 covenant `ab_enum_cotton_china` [N8]: the FRED BRL/USD daily window."""
    return {"query": {"table": "silver_fred_fx", "metric": "brl_usd", "commodity": "cotton",
                      "period": "2017-12-01..2018-03-01"}, "status": "ok",
            "rows": [{"value": v, "unit": "BRL per USD (FRED)", "period": None, "knowledge_date": k}
                     for v, k in vals]}


_FX_SPRAY = [("3.2666", "2017-12-01"), ("3.2733", "2017-12-08"), ("3.2743", "2018-01-02"),
             ("3.2675", "2018-02-08"), ("3.2705", "2018-02-22"), ("3.2651", "2018-03-01")]


def test_fix3_the_five_row_FX_spray_is_refused():
    """ONE stated value, 3.2651, minted FIVE letter-suffixed rows -- all five round to 3.27 at 2 dp, so the
    residual exact bucket admitted them and the d=0/reader-precision gating never ran. A 4-dp figure claims
    identity within +-0.00005; the smallest gap here is 0.0015 (30x) and the largest 0.0092 (184x)."""
    prose = ("The BRL/USD stood at 3.2651 per USD in the 2017-12-01..2018-03-01 window [N1] and at "
             "5.1153 per USD currently [N2].")
    stated = orc._stated_values(prose)
    got = cit.prose_completion_citations([_fx_call(_FX_SPRAY)], stated, seen=set(), cited={1})
    assert [c.label for c in got] == []


def test_fix3_matcher_rule7_the_bucket_no_longer_bypasses_the_window():
    class _N:                                             # the `stated.mint` numeral shape
        def __init__(self, v, d, u=None):
            self.value, self.decimals, self.unit = v, d, u
            self.claimed = self.percent = self.percent_level = False
    m = cit._mint_matcher([_N(3.2651, 4)], "BRL per USD (FRED)")
    assert cit._mint_bucket(3.2666) == cit._mint_bucket(3.2651)      # same bucket -- and still refused
    for v in ("3.2666", "3.2733", "3.2743", "3.2675", "3.2705"):
        assert m({"value": v}) is False, v
    assert m({"value": "3.2651"}) is True                            # the exact figure still mints
    assert m.which({"value": "3.2651"}).value == 3.2651


def test_fix3_rule8_one_row_per_stated_value_per_call():
    """Even where precision would admit several neighbours, ONE numeral names ONE fact -- the newest."""
    class _N:
        def __init__(self, v, d, u=None):
            self.value, self.decimals, self.unit = v, d, u
            self.claimed = self.percent = self.percent_level = False
    call = {"query": {"table": "silver_fred_fx", "metric": "brl_usd"}, "status": "ok",
            "rows": [{"value": v, "unit": "BRL per USD", "period": p, "knowledge_date": k}
                     for v, p, k in (("3.2", "2018-01", "2018-01-02"),
                                     ("3.2", "2018-02", "2018-02-08"),
                                     ("3.2", "2018-03", "2018-03-22"),
                                     ("9.9", "2018-04", "2018-04-30"))]}   # the headline, named by nobody
    m = cit._mint_matcher([_N(3.2, 1)], "BRL per USD")
    hits = [r for r in call["rows"] if m(r)]
    assert len(hits) == 3                                 # all three are admissible on precision
    stated = orc._stated_values(
        "The window closed at 9.9 [N1]. Through it the rate held at 3.2 on every monthly print.")
    got = cit.prose_completion_citations([call], stated, seen=set(), cited={1})
    assert len(got) == 1 and got[0].date == "2018-03-22"  # newest-first, exactly one


def test_fix3_the_farm_price_vintage_rows_all_still_mint():
    """gate-5 dcw `dcw_farm_price_vintage` [N1b]/[N1c]/[N1d]: THREE DIFFERENT stated values, three rows.
    This is the shape rule (8) must not touch and rule (7) must not narrow."""
    call = {"query": {"table": "silver_wasde", "metric": "avg_farm_price", "commodity": "corn",
                      "country": "united_states"}, "status": "ok",
            "rows": [{"value": v, "unit": "$/bu", "period": p, "revision_stamp": role,
                      "knowledge_date": k}
                     for v, p, role, k in (("4.55", "2023/24", "actual", "2026-04-09"),
                                           ("4.24", "2024/25", "actual", "2026-07-10"),
                                           ("4.15", "2025/26", "estimate", "2026-07-10"),
                                           ("4.4", "2022/23", "actual", "2025-04-09"),
                                           # the HEADLINE the reader already has (skipped, not minted)
                                           ("3.90", "2026/27", "projection", "2026-07-10"))]}
    # the handle sits on the HEADLINE clause -- a numeral glued to [N1] is `claimed` (rule 3) and mints
    # nothing, which is cycle-7's fence, not cycle-8's
    prose = ("The season-average farm price [N1] was 4.55 $/bu in MY2023/24, 4.24 $/bu in MY2024/25, "
             "and is projected at 4.15 $/bu for MY2025/26.")
    stated = orc._stated_values(prose)
    got = [c.label for c in cit.prose_completion_citations([call], stated, seen=set(), cited={1})]
    assert len(got) == 3
    assert all(any(v in lbl for lbl in got) for v in ("4.55", "4.24", "4.15"))
    # and the numbers_only extras lane -- a DIFFERENT predicate, deliberately untouched this cycle
    extras = [c.label for c in cit.extra_number_citations(call, 1, stated)]
    assert len([x for x in extras if any(v in x for v in ("4.55", "4.24", "4.15"))]) == 3


def test_fix3_the_conab_zero_dp_restatement_still_mints():
    """The one shape on this lane cycle-6's reader-precision arm was built for: '35,763' naming 35763.1."""
    class _N:
        def __init__(self, v, d, u=None):
            self.value, self.decimals, self.unit = v, d, u
            self.claimed = self.percent = self.percent_level = False
    m = cit._mint_matcher([_N(35763.0, 0)], "thousand bags")
    assert m({"value": "35763.1"}) is True
    assert m({"value": "35800"}) is False                  # ...and the binning refusal holds


# ======================================================================================================
# FIX 4 -- NO SILENT DENOMINATORS
# ======================================================================================================

def test_fix4_the_two_zero_claim_answers_are_diagnosed_not_guessed():
    """DIAGNOSIS (gate-5 covenant): `ab_rank_wheat_importers` and `ab_rec_malaysia_stocks` are
    intent=numbers_only turns. `run_numbers_only` returns a plain `answer` string with NO structured
    tldr/mechanism, and `verify_citations` reads only those two fields -- so claim_count/handles/strips
    are 0 by CONSTRUCTION, not by extraction failure, and both turns WERE verified, by
    `orchestrator._verify_numbers_answer` (`numbers_verifier`: stated 0 / stated 3 with 1 mismatch).
    Nothing to fix in extraction; the fix is report-side and additive."""
    rec = ev._per_answer_record({"q": {"id": "ab_rec_malaysia_stocks"},
                                 "out": {"answer": "Stocks sat at 2.31 million MT in April 2026.",
                                         "trace": {"numbers_verifier": {"stated": 3, "rows": 78,
                                                                        "mismatched": 1}}}}, "single")
    assert rec["citation_verifier_ran"] is False
    assert rec["claim_count"] == 0 and rec["strips"] == 0 and rec["repairs"] == 0
    assert rec["numbers_verifier"]["stated"] == 3


def test_fix4_the_panel_states_the_live_denominator_and_names_the_dark_turns():
    traces = [{"enabled": True, "checked": 4, "stripped": 1, "claim_count": 9, "corrected": 0,
               "repaired": 0, "repairs": [], "by_rule": {"number_mismatch": 1}},
              None,
              {"enabled": True, "checked": 2, "stripped": 0, "claim_count": 5, "corrected": 1,
               "repaired": 1,
               # CYCLE-8 REVIEW MINOR 8: the panel's headline number is the APPLIED-op record, not the
               # offending-handle counter, so the fixture must carry the record the verifier emits.
               "repairs": [{"field": "mechanism", "rule": "number_mismatch_repaired",
                            "from": "1", "to": "0.195159"}],
               "by_rule": {"number_mismatch_repaired": 1}}]
    ids = ["ab_hybrid_one", "ab_rank_wheat_importers", "ab_hybrid_two"]
    body = "\n".join(ev.verifier_panel(traces, ids))
    assert "live denominator: **2/3**" in body
    assert "ab_rank_wheat_importers" in body
    assert "prose repairs (number_mismatch rewrites): 1" in body
    assert "offending handles" not in body                 # the two agree here, so no divergence note
    assert "answers with >=1 strip or repair: 2/2" in body
    assert "strip RATE: 0.0714" in body                    # 1 / 14 -- the frozen metric, unmoved


def test_fix4_the_panel_is_unchanged_when_every_answer_ran_the_verifier():
    traces = [{"enabled": True, "checked": 4, "stripped": 1, "claim_count": 9, "corrected": 0,
               "repaired": 0, "by_rule": {}}]
    body = "\n".join(ev.verifier_panel(traces, ["only_one"]))
    assert "live denominator: **1/1** answers ran the citation verifier" in body
    assert "every answer" in body
    assert "not run on" not in body


def test_fix4_ids_are_optional_the_legacy_one_argument_call_still_works():
    traces = [{"enabled": True, "checked": 1, "stripped": 0, "claim_count": 3, "corrected": 0,
               "repaired": 0, "by_rule": {}}]
    body = "\n".join(ev.verifier_panel(traces))
    assert "live denominator: **1/1**" in body and "not run on" not in body


# ======================================================================================================
# THE WHOLE-PATH REPLAY: the three gate-5 corruptions, end to end, through verify_citations
# ======================================================================================================

def test_no_gate5_corruption_survives_the_full_verify_path():
    shapes = [
        # (mechanism, calls, the invented token that must never appear)
        ("- **Natural gas prices**: currently below the 5-year mean [N1];",
         [_call("silver_pink_sheet", "natural_gas_us_usd_mmbtu_zscore_5yr", ["-0.344930511713658"])],
         "0.344931"),
        ("Watch whether urea [N1] moves above its 5-year mean alongside gas.",
         [_call("silver_pink_sheet", "urea_usd_mt", ["453.1"])], "453.1-year"),
        ("CPO production was running roughly 2 percent below the five-year average, though the April "
         "2026 output figure itself [N1] should be read in seasonal context.",
         [_call("silver_mpob", "production_cpo_mt", ["1629801.0"])], "1,629,801"),
    ]
    for body, calls, invented in shapes:
        st, rep = _verify("", body, calls)
        assert invented not in st["mechanism"], body
        assert rep["repaired"] == 0, body
        # and if anything WAS mutated it would be on the record -- the no-laundering invariant
        assert (st["mechanism"] == body) or rep["stripped"] or rep["repaired"]


# ======================================================================================================
# CYCLE-8 ADVERSARIAL REVIEW (2026-08-08) -- one pin per finding closed.
#
# The review's verdict was BLOCK: the corruption class the build closed was real and independently
# reproduced, but the collateral was not swept for. Every pin below is a probe the reviewer ran against the
# working tree and got the WRONG answer from. They are grouped by finding id so a future regression names
# itself.
# ======================================================================================================

# ---- BLOCKER 1 -- the mint's relative ceiling destroyed correctly-rounded sub-unit restatements --------

def _mint_hit(prose, row_value, unit):
    """Does the completion matcher read `row_value` as the thing the prose's numeral names?"""
    st = orc._stated_values(prose)
    nums = [n for n in (getattr(st, "mint", ()) or ()) if not n.claimed]
    return cit._mint_matcher(nums, unit)({"value": str(row_value), "unit": unit})


def test_b1_a_correctly_rounded_two_dp_z_restatement_still_mints():
    """The estate's dominant numeral shape. The reader wrote 2 dp, so the half-unit window is +-0.005 and
    -0.20 IS the served -0.19515863509764528 -- but 0.005*|v| is 0.000976, and promoting that ceiling to an
    always-on clause refused it. Measured on the real served rows of gate-4/gate-5 `dcw_gas_nitrogen_squeeze`
    (urea / gas / potash 5-yr z), where it cost 5 of the 14 lost identity matches.
    (No `[N]` handle in the prose: rule (3) makes a handle-adjacent numeral CLAIMED, and a claimed numeral is
    not a completion candidate at all -- this pin is about the matcher's precision arm, not the entry fence.)
    """
    assert _mint_hit("Urea carries a z-score of -0.20 on the long distribution.", -0.19515863509764528, "z")
    assert _mint_hit("EU gas sits at -0.31 z.", -0.3063197017144927, "z")
    assert _mint_hit("Potash reads -0.36 z.", -0.3563388731532333, "z")
    # ... and the same shape in the small-percent band
    assert _mint_hit("Stocks fell 0.35 percent.", 0.3468, "%")


def test_b1_the_window_alone_still_kills_the_whole_fx_spray():
    """THE DECISIVE MEASUREMENT the ceiling was added for: it contributes nothing the window does not
    already do. gate-5 covenant `ab_enum_cotton_china` stated ONE 4-dp value and minted five different days'
    fixes off it; every gap is 30x-184x the reader's own +-0.00005 window."""
    for row in (3.2666, 3.2733, 3.2743, 3.2675, 3.2705):
        assert not _mint_hit("The BRL sits at 3.2651 per USD.", row, "BRL per USD")
    for row in (5.1185, 5.1155, 5.1233, 5.1158, 5.1164, 5.1202):     # the `dcw_macro_on_soy` BRL spray
        assert not _mint_hit("USDBRL printed 5.1191 on the day.", row, "BRL per USD")


def test_b1_the_d0_ceiling_is_untouched_conab_keeps_minting_and_one_still_refuses():
    """Rule (5) is still exactly what its own note says it is: the only bound on a flat +-0.5 window."""
    assert _mint_hit("CONAB puts it at 35,763 MT.", 35763.1, "MT")         # 2.8e-6 relative -- the control
    assert not _mint_hit("The reading is 1 sigma.", 1.0044, "z")           # 4.4e-3 relative -- the defect


# ---- BLOCKER 2 -- the duration exemption swallowed head-position quantities ---------------------------

def test_b2_head_position_duration_quantities_are_still_claims():
    """"followed by another word" exempted every PREPOSITIONAL continuation, i.e. exactly the head-position
    shape the amendment note swears it preserves. The builder's own pin survived only because a '[' followed
    the noun. Five measured losses, plus the two REAL corpus sentences (gate-4 + gate-5
    `dcw_positioning_beans`, the D-RC-13 recency-honesty lane)."""
    for sent, want in (("prices have risen for 5 months in a row [N10]", 5.0),
                       ("ending stocks cover 21 days of use [N6]", 21.0),
                       ("US corn is 12 days ahead of the pace [N4]", 12.0),
                       ("the crush ran 3 weeks behind schedule [N5]", 3.0),
                       ("exports rose in each of the last 5 months of the marketing year [N1]", 5.0),
                       ("the harvest is running 10 days behind the average [N2]", 10.0),
                       ("stocks cover 45 days of demand [N3]", 45.0),
                       ("(10 days before the as-of date)", 10.0),
                       ("published within 6 days prior to the 2026-08-07 as-of", 6.0)):
        assert want in vf._claim_numbers_in(sent), sent


def test_b2_the_window_modifier_exemption_still_holds_on_both_spellings():
    """What the amendment is FOR, unmoved: the hyphenated compound (its own orthographic declaration) and
    the space form when the head is a STATISTIC."""
    for sent in ("currently below the 5-year mean [N9]", "moves above its 5-year mean",
                 "a 12-week moving average", "the 90-day change", "a 36-month window",
                 "the 5 year mean of the series", "a 3 month average of the print"):
        assert vf._claim_numbers_in(sent) == [], sent
    # the statistic in the same sentence is still a claim -- the exemption is the WINDOW, never the value
    assert vf._claim_numbers_in("a 5-year low of 9.48") == [9.48]
    assert vf._claim_numbers_in("the 3-month average of 0.21") == [0.21]


def test_b2_percent_claims_are_untouched_by_the_duration_rule():
    assert vf._claim_numbers_in("grew 5 percent") == [5.0]
    assert vf._claim_numbers_in("2 percent below the five-year average") == [2.0]


# ---- BLOCKER 3 -- the percentile carve-out lost to the hyphenated spelling ----------------------------

def test_b3_the_hyphenated_percentile_spelling_is_still_a_claim():
    """VERBATIM from the gate-5 `dcw_urea_zscore` draft. This estate serves percentile_rank metrics, so the
    ordinal IS the cited row's value; the carve-out allowed only whitespace and the hyphen defeated it."""
    assert 65.9 in vf._claim_numbers_in("The 65.9th-percentile rank [N4] on the longer distribution")
    for sent, want in (("at the 76.8th-percentile of the range [N3]", 76.8),
                       ("at the 76.8th percentile [N3]", 76.8),
                       ("in the 66th percentile band [N4]", 66.0),
                       ("a 12th" + chr(0x2011) + "decile print", 12.0),   # U+2011, source stays ASCII
                       ("the 4th-quartile reading", 4.0)):
        assert want in vf._claim_numbers_in(sent), sent


def test_b3_non_percentile_ordinals_are_still_exempt():
    assert vf._claim_numbers_in("the 3rd consecutive month of decline") == []
    assert vf._claim_numbers_in("the 1st of the month") == []


# ---- MAJOR 4 -- the amendment must not UNLOCK the repair path ----------------------------------------

def test_m4_a_two_numeral_duration_sentence_is_still_ambiguity_refused():
    """De-charging a numeral changes how many claim numerals a sentence HAS, and that count drives the
    ambiguity refusal -- so a 2-span sentence (refuse, drop) silently became 1-span (repair, REWRITE). The
    corpus's most common shape: `dcw_gas_nitrogen_squeeze` alone writes six of these."""
    z = _call("silver_fred", "eu_gas_z", ["0.31"], unit="z")
    assert vf._num_repair("gas sits at a 5-year z-score of +1.24 sigma [N1]", 1, [z]) is None
    assert vf._num_repair("the 90-day change was only -0.76 z [N1]", 1, [z]) is None
    # the ONE-numeral shape the repair path was always allowed to touch is unaffected
    assert vf._num_repair("gas sits at +1.24 sigma [N1]", 1, [z])[2] == "0.31"


# ---- MAJOR 5 -- a threshold inside a conditional is not a value slot ---------------------------------

def test_m5_a_conditional_threshold_is_never_rewritten_to_the_current_level():
    """THE ONE REPAIR THAT SURVIVED CYCLE-8 ANYWHERE ON THE GATES, and it was itself a corruption: gate-4
    `dcw_gas_nitrogen_squeeze` shipped "if this crosses above +0.195159 sigma", a sentence asserting that a
    value might cross above itself. Every existing fence passed it (index into index, one value, one
    numeral)."""
    call = _call("agent_lane", "urea_z", ["-0.195159"])
    for sent in ("if this crosses above +1 sigma [N1] the chain closes",
                 "once the z moves below -1 sigma [N1]",
                 "unless it breaches above 2 sigma [N1]",
                 "watch whether it climbs through 1 sigma [N1] this month",
                 "until the reading exceeds 3 sigma [N1]"):
        assert vf._num_repair(sent, 1, [call]) is None, sent
    st, rep = _verify("", "- **Urea [N1]:** if this crosses above +1 sigma the chain closes.", [call])
    assert "0.195159" not in st["mechanism"] and rep["repaired"] == 0
    assert rep["by_rule"].get("number_mismatch") == 1          # the honest fail-closed drop instead


def test_m5_a_bare_comparison_without_a_conditional_still_repairs():
    """The fence needs BOTH halves. Plain description is not a threshold, and over-refusing here would
    quietly convert legitimate repairs into sentence drops.

    CYCLE-9 REVIEW (2026-08-08), MAJOR 4: the replacement gained the row's SIGN (the slot writes none of
    its own and the row is -0.195159). The claim under test -- that a bare comparison stays REPAIRABLE --
    is unchanged; only the figure it writes is now the row's actual one."""
    call = _call("agent_lane", "urea_z", ["-0.195159"])
    assert vf._num_repair("the reading sits above 1 sigma [N1] today", 1, [call])[2] == "-0.195159"


# ---- MAJOR 6 -- the registry-independent class arm, for every class ----------------------------------

def test_m6_a_metric_name_declares_its_class_without_the_registry():
    """`_registry_unit_class` fails open at every step by design, and cycle-8's only registry-independent
    lock covered PERCENT slots. A metric NAME carrying an explicit unit token is a class the fence can read
    with no registry at all."""
    assert vf._metric_tell_class(_call("unregistered_tbl", "ending_stocks_mt", ["1"])) == "mass"
    assert vf._metric_tell_class(_call("unregistered_tbl", "fob_usd_t", ["1"])) == "money"
    assert vf._metric_tell_class(_call("unregistered_tbl", "anomaly_degc", ["1"])) == "temp"
    assert vf._metric_tell_class(_call("unregistered_tbl", "price_z", ["1"])) == "index"
    assert vf._metric_tell_class(_call("unregistered_tbl", "area_ha", ["1"])) == "area"
    # pct wins outright over the base unit it is a percentage OF -- the same precedence `_PCT_METRIC` asserts
    assert vf._metric_tell_class(_call("unregistered_tbl", "ending_stocks_mt_pct", ["1"])) == "pct"
    # and it is a UNIT-TOKEN test, never a semantic guess: 'us_' is not a currency, a lone 't' is not a mass
    assert vf._metric_tell_class(_call("unregistered_tbl", "us_corn_conditions", ["1"])) is None
    assert vf._metric_tell_class(_call("unregistered_tbl", "oni_level_delta", ["1"])) is None


def test_m6_a_cross_class_splice_is_refused_with_the_registry_absent():
    """The class the fence was born for, now closed without the registry: an unregistered table, a row that
    carries no unit, and a metric name that says what it is."""
    mt = _call("unregistered_tbl", "ending_stocks_mt", ["1629801"])
    assert vf._registry_unit_class(mt) is None                 # the registry genuinely cannot help
    assert vf._call_unit_class(mt, 1629801.0) == "mass"        # ... and the name still supplies the class
    assert vf._num_repair("the anomaly ran 2 degC above normal [N1]", 1, [mt]) is None
    assert vf._num_repair("cash traded at $4.20 [N1]", 1, [mt]) is None


# ---- MINOR 7 -- the 'pct-points' spelling ------------------------------------------------------------

def test_m7_the_pct_points_spelling_classifies_as_percent():
    palm = _call("silver_mpob", "production_cpo_mt", ["1629801"])
    for spelling in ("percent", "percentage points", "pct-points", "pct-point", "percentage-points",
                     "pp", "ppt"):
        sent = "roughly 2 " + spelling + " below the average [N1]"
        assert vf._num_repair(sent, 1, [palm]) is None, spelling
    assert vf._unit_class("pct-points") == "pct" and vf._unit_class("percentage-points") == "pct"
    # the bare index tokens `_UNIT_CLASSES['index']` owns are NOT swept up by the tail strip
    assert vf._unit_class("points") == "index" and vf._unit_class("pts") == "index"


# ---- MINOR 8 -- `repaired` counts handles, `repairs` counts what the reader receives ------------------

def test_m8_the_panel_headlines_the_edits_the_reader_receives_not_the_handle_count():
    traces = [{"enabled": True, "checked": 3, "stripped": 2, "claim_count": 8, "corrected": 1,
               "repaired": 2, "repairs": [], "by_rule": {"number_mismatch_repaired": 2}}]
    body = "\n".join(ev.verifier_panel(traces, ["one"]))
    assert "prose repairs (number_mismatch rewrites): 0" in body
    assert "charged against 2 offending handles" in body       # the divergence is stated, not hidden
    assert "each one changed a figure" not in body             # the false claim is gone
