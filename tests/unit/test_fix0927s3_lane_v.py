# -*- coding: utf-8 -*-
"""09-29 FIX SITTING 3, LANE V -- the verifier holds three more facts the block serves with a figure (U-4 threshold
words, U-3 pair standing, U-9 episode verdict: CONTRACT Z5 / Z6 / Z7), a struck handle re-joins its sentence through
the one splice producer (U-10 a, Z8), and a folded row under the analyst stamp names its own week (S2 V-1, Z28).

Every sentence quoted as "served" below is verbatim banked prose (arm A 09-26 and the 09-23 / 09-24 / 09-25
re-smokes, fix_sitting_3_0927/V/b51_b53_drive.py reads the same pages); the scalar dicts are the CONTRACT's shapes (the
ones lane R's `Block.scalar` and lane T's call stamp register). Author-written sentences are marked and pin a fence,
never a corpus claim -- the negative corpus is the fifty, run by the lane's drive."""
import copy

import pytest
from leviathan.graphrag import citations as C
from leviathan.graphrag import verify as V

EM = "—"
PALM_RID = "malaysian_crude_palm_oil_cme|drought|drought_z|malaysian_crude_palm_oil_cme|SE Asia Palm Belt"
SOY_SU_RID = "soybeans_cbot|psd_ending_stock_su_ratio|psd_ending_stock_su_ratio|soybeans_cbot|United States"
TW = {"past": ["past", "beyond", "crossed"], "inside": ["inside", "short of", "within", "not yet at"]}
PW = {"under": ["under", "below", "at a discount to", "cheaper than"],
      "over": ["over", "above", "at a premium to", "dearer than"], "level": ["level with", "even with"]}


def _call(table="t", metric="m", value=1.0, unit="", rid=None, **kw):
    c = {"query": {"table": table, "metric": metric}, "rows": [{"value": value, "unit": unit}], "status": "ok"}
    if rid:
        c["_row_id"] = rid
    c.update(kw)
    return c


def _calls(n, rows=None):
    out = [_call() for _ in range(n)]
    for j, c in (rows or {}).items():
        out[j - 1] = c
    return out


def _thr(rid, label, jh, relation="past", words=None):
    return {"value": 2.0, "unit": "sigma", "kind": "card_threshold", "row_id": rid, "label": label, "line": 2.0,
            "judged": "z", "judged_value": 2.665, "judged_handle": jh, "relation": relation,
            "relation_words": copy.deepcopy(words or TW), "text": "two sigma"}


def _palm_calls(level=24, n=30):
    return _calls(n, {level: _call("gold_weather_z", "drought_z", 1.2491708897603446, "z", PALM_RID),
                      level + 1: _call("gold_weather_z", "drought_z", 2.7, "sigma", PALM_RID),
                      level + 2: _call("gold_weather_z", "drought_z", 97, "percentile", PALM_RID)})


def _apply(text, pool, calls):
    ctx = V._VCtx(calls, pool)
    log = {"field": "mechanism"}
    return V._apply_direction_edits(text, ctx, log), log


# ── served prose ──────────────────────────────────────────────────────────────────────────────────────────────
SOYPALM_WATCH = ("- **The palm-belt dry spell** [N24]: 1.25 z, August 2026, three months rising and past the severe "
                 "line, which sits at two sigma.")                                  # arm A treatment soyoil/palm
PALMRAPE_WATCH = ("- **Palm-belt dry-day run** at 1.25 z for August 2026 [N14], past the severe line, which the desk "
                  "draws at two sigma: it reads wrong if the next print turns back inside that line or the "
                  "three-month rising run breaks.")                                  # arm A treatment palm/rape
PALMRAPE_JUDGED = ("- Palm belt dryness: longest dry-day run at 1.25 z for August 2026 [N14], +2.7 sigma on its "
                   "trailing ten years [N15], 97th percentile [N16], rising three months running " + EM +
                   " past the line the desk calls severe.")                          # arm A treatment palm/rape
MAX0923_FALSIFIER = ("- **The tropical Pacific** at +1.8 degC [N13], for July 2026, eight months rising, window "
                     "2026-10-31 to 2027-01-31, next print 2026-10-01: wrong if the next print turns back inside "
                     "the strong line or the run breaks.")                           # 09-23 max
MAX0924_TIGHT = ("**The tight buffer is the convexity.** US soybean stocks-to-use at 10.72 % sits past the line the "
                 "desk calls tight [N194], and a thin carryout is what makes an adverse yield or export surprise "
                 "convex to the upside while a good crop is absorbed roughly linearly.")   # 09-24 max
CW0925_TLDR = ("Corn December 2026 settles 180.5 US cents/bushel below Chicago wheat December 2026 [N15] " + EM +
               " wheat is the expensive grain, so the feed-substitution channel runs AGAINST wheat right now: corn "
               "stays in the ration and the wheat-corn spread offers no feed floor.")  # 09-25 corn/wheat
CW0925_MECH = ("With corn 180.5 US cents/bushel under Chicago wheat on the December 2026 contracts [N15], the "
               "substitution runs the wrong way for wheat " + EM + " corn is the cheap ration grain, so wheat wins no "
               "incremental feed demand.")                                           # 09-25 corn/wheat
CW_E2 = ("- Documents: the feed-substitution link is documented " + EM + " corn became the cheaper feed ingredient "
         "and feed corn use rose at wheat's expense in MY2021/22 [E1]; feed wheat was expected cheaper than domestic "
         "corn in MY2018/19 [E2]; and in April 2011 corn feed and residual use was cut as SRW prospects improved "
         "[E4].")                                                                    # arm A treatment corn/wheat
MAX_MEAL_OIL = ("- **Soybean meal and soybean oil** -- declared to compete for the same demand; soyoil moved -8.11 % "
                "[N247]; the read: the two moves sat at odds with the declared relation over that window.")
MAX_RAPEOIL = ("- **Soybeans and ZCE rapeseed oil** -- same declared competition; rapeseed oil moved -3.9 % [N245] in "
               "yuan; the read: the relation held over that window.")          # arm A treatment max
MAX_MEAL = ("- **Soybeans and CBOT soybean meal** -- joined by the same crush; meal moved -10.02 % [N246]; the read: "
            "the relation held.")                                               # arm A treatment max
DEEP2024_FORK = ("Within the 2015-10..2016-06 window the complex did not move as one: the crush link into meal held "
                 "[N67], and both Zhengzhou substitution links held [N65][N66], but the declared meal-to-oil relation "
                 "-- strong meal demand raising crush and so soyoil supply -- sat at odds with what the boards did, "
                 "with soybean oil up +9.6121 % [N68] alongside meal.")        # 09-23 deep 2024 (raw draft)
TARIFF_STRIKE = ("Lag and aftermath in the 2018 case: duties spring 2018 [N1], [N9], with WASDE registering the trade "
                 "effect by 12 July 2018.")        # the arm-A tariff shape ("[E1], [E4], with"), [N9] out of range


# ═════════════════════════════════════════ U-4 THRESHOLD WORDS ═══════════════════════════════════════════════
def test_U4_soyoil_palm_the_line_bound_to_the_level_gains_the_judged_figures_citation_and_keeps_its_words():
    out, log = _apply(SOYPALM_WATCH, [_thr(PALM_RID, "severe", 25)], _palm_calls())
    assert out == ("- **The palm-belt dry spell** [N24]: 1.25 z, August 2026, three months rising and past the "
                   "severe line [N25], which sits at two sigma.")
    assert log.get("threshold_cited") == 1 and not log.get("threshold_corrected") and not log.get("corrected")
    assert [a["rule"] for a in log["audit"]] == ["threshold_cited"]


def test_U4_palm_rape_the_same_class_on_the_other_page():
    out, log = _apply(PALMRAPE_WATCH, [_thr(PALM_RID, "severe", 15)], _palm_calls(level=14))
    assert "past the severe line [N15], which the desk draws at two sigma" in out
    assert "turns back inside that line" in out and log.get("threshold_cited") == 1


def test_U4_a_sentence_already_citing_the_judged_figure_is_left_byte_for_byte():
    out, log = _apply(PALMRAPE_JUDGED, [_thr(PALM_RID, "severe", 15)], _palm_calls(level=14))
    assert out == PALMRAPE_JUDGED and log.get("threshold_agreed") == 1 and "audit" not in log


def test_U4_a_falsifier_about_the_next_print_is_never_corrected():
    oni = "El_Nino|oni|global"
    calls = _calls(20, {13: _call("silver_noaa_oni", "oni", 1.8, "degC", oni)})
    thr = dict(_thr(oni, "strong", 13), judged="level")
    out, log = _apply(MAX0923_FALSIFIER, [thr], calls)
    assert out == MAX0923_FALSIFIER
    assert log.get("threshold_unanchored") == 1 and not log.get("threshold_corrected")


def test_U4_a_contradicting_relation_word_written_beside_the_judged_figure_is_corrected_never_struck():
    s = "The dry-day run reads 2.7 sigma [N25], inside the severe line."          # author-written: the fence
    out, log = _apply(s, [_thr(PALM_RID, "severe", 25)], _palm_calls())
    assert out == "The dry-day run reads 2.7 sigma [N25], past the severe line."
    assert log.get("threshold_corrected") == 1


def test_U4_the_correction_keeps_the_vocabulary_position_of_the_word_it_replaces():
    s = "The dry-day run reads 2.7 sigma [N25], short of the severe line."         # author-written
    out, _log = _apply(s, [_thr(PALM_RID, "severe", 25)], _palm_calls())
    assert out == "The dry-day run reads 2.7 sigma [N25], beyond the severe line."


def test_U4_the_citation_joins_a_handle_group_that_already_closes_the_clause():
    calls = _calls(200, {194: _call("silver_psd", "su_ratio", 10.72, "%", SOY_SU_RID),
                         196: _call("silver_psd", "su_ratio", 23, "percentile", SOY_SU_RID)})
    thr = dict(_thr(SOY_SU_RID, "tight", 196), judged="percentile")
    out, log = _apply(MAX0924_TIGHT, [thr], calls)
    assert "past the line the desk calls tight [N194] [N196], and a thin carryout" in out
    assert log.get("threshold_cited") == 1


def test_U4_a_judged_handle_that_does_not_address_the_row_inserts_nothing():
    calls = _palm_calls()
    calls[24]["_row_id"] = "another|row"
    out, log = _apply(SOYPALM_WATCH, [_thr(PALM_RID, "severe", 25)], calls)
    assert out == SOYPALM_WATCH and log.get("threshold_unanchored") == 1


def test_U4_a_label_of_a_row_the_sentence_does_not_cite_binds_nothing():
    out, log = _apply(SOYPALM_WATCH, [_thr("some|other|row", "severe", 25)], _palm_calls())
    assert out == SOYPALM_WATCH and log.get("threshold_unanchored") == 1


def test_U4_a_figure_between_the_relation_word_and_the_label_is_not_one_clause():
    s = "Stocks ran past 2.8 MMT to the severe mark [N24]."                          # author-written
    out, log = _apply(s, [_thr(PALM_RID, "severe", 25)], _palm_calls())
    assert out == s and not log.get("threshold_cited")


def test_U4_the_line_value_words_are_the_books_only_heads_shape_threshold_is_no_fact():
    head_shape = {"value": 2.0, "unit": "sigma", "kind": "card_threshold", "row_id": None, "handle": None,
                  "text": "two sigma"}                                                  # HEAD's SB-V registration
    assert V._threshold_pool([head_shape]) == ()
    out, log = _apply(SOYPALM_WATCH, [head_shape], _palm_calls())
    assert out == SOYPALM_WATCH and "audit" not in log


def test_U4_the_row_is_read_from_threshold_row_id_where_the_scalar_keeps_heads_row_id_none():
    thr = dict(_thr(PALM_RID, "severe", 25), row_id=None, threshold_row_id=PALM_RID)   # lane R's SB-V shape
    out, log = _apply(SOYPALM_WATCH, [thr], _palm_calls())
    assert "past the severe line [N25], which" in out and log.get("threshold_cited") == 1


def test_U4_two_rows_sharing_a_label_bind_by_the_handle_group_the_clause_follows_or_not_at_all():
    rid2 = "palm_olein_dce|drought|drought_z|palm_olein_dce|SE Asia Palm Belt"
    calls = _palm_calls()
    calls[27] = _call("gold_weather_z", "drought_z", 1.19, "z", rid2)
    calls[28] = _call("gold_weather_z", "drought_z", 2.5, "sigma", rid2)
    pool = [_thr(PALM_RID, "severe", 25), _thr(rid2, "severe", 29)]
    s = "Palm [N24] and olein [N28] both read dry, past the severe line."             # author-written
    out, log = _apply(s, pool, calls)
    assert out == "Palm [N24] and olein [N28] both read dry, past the severe line [N29]."
    s2 = "Past the severe line, palm [N24] and olein [N28] both read dry."            # author-written: no group before
    out2, log2 = _apply(s2, pool, calls)
    assert out2 == s2 and log2.get("threshold_unanchored") == 1


def test_U4_verify_citations_inserts_in_its_own_apply_pass_and_charges_nothing_new():
    calls = _palm_calls()
    st_off = {"tldr": "", "mechanism": SOYPALM_WATCH, "sources": []}
    st_on = copy.deepcopy(st_off)
    rep_off = V.verify_citations(st_off, [], copy.deepcopy(calls), served_scalars=[])
    rep_on = V.verify_citations(st_on, [], copy.deepcopy(calls), served_scalars=[_thr(PALM_RID, "severe", 25)])
    assert "past the severe line [N25], which sits at two sigma" in st_on["mechanism"]
    assert st_off["mechanism"] == SOYPALM_WATCH
    assert rep_on["by_rule"] == rep_off["by_rule"] and rep_on["stripped"] == rep_off["stripped"]
    assert rep_on.get("threshold_cited") == 1 and "direction_corrected" not in rep_on
    assert [a["rule"] for a in rep_on["direction_audit"]] == ["threshold_cited"]


def test_U4_no_citation_is_inserted_into_a_sentence_the_verifier_strikes_a_handle_in():
    s = SOYPALM_WATCH.replace("[N24]", "[N24] [N99]")                              # [N99]: out of range, struck
    st = {"tldr": "", "mechanism": s, "sources": []}
    rep = V.verify_citations(st, [], _palm_calls(), served_scalars=[_thr(PALM_RID, "severe", 25)])
    assert rep["by_rule"] == {"index_out_of_range": 1}
    assert "[N25]" not in st["mechanism"] and "past the severe line, which sits at two sigma" in st["mechanism"]
    assert rep.get("threshold_unanchored") == 1 and "threshold_cited" not in rep


def test_U4_no_pool_is_heads_report_and_prose():
    calls = _palm_calls()
    st = {"tldr": "", "mechanism": SOYPALM_WATCH, "sources": []}
    rep = V.verify_citations(st, [], calls)
    assert st["mechanism"] == SOYPALM_WATCH
    for k in ("threshold_cited", "threshold_corrected", "threshold_unanchored", "direction_audit", "strike_rejoined"):
        assert k not in rep


# ═════════════════════════════════════════ U-3 PAIR STANDING ═════════════════════════════════════════════════
def _pair(value=-180.5, handle=15, **kw):
    d = {"value": value, "unit": "US cents/bushel", "kind": "pair_relation", "handle": handle,
         "legs": ["corn_cbot", "soft_red_winter_wheat_cbot"], "standing": "under" if value < 0 else "over",
         "standing_words": copy.deepcopy(PW), "row_id": "corn_cbot|pair_level_spread|soft_red_winter_wheat_cbot"}
    d.update(kw)
    return d


def _pair_calls():
    return _calls(20, {15: _call("silver_futures_eod", "settle difference, CBOT corn minus CBOT srw wheat", -180.5,
                                 "US cents/bushel", "corn_cbot|pair_level_spread|soft_red_winter_wheat_cbot")})


@pytest.mark.parametrize("sent", [CW0925_TLDR, CW0925_MECH])
def test_U3_the_served_standing_sentences_agree_and_are_left_byte_for_byte(sent):
    out, log = _apply(sent, [_pair()], _pair_calls())
    assert out == sent and log.get("pair_standing_agreed") == 1 and "audit" not in log


def test_U3_a_standing_word_that_contradicts_the_spreads_own_sign_is_corrected():
    s = CW0925_TLDR.replace("below Chicago wheat", "above Chicago wheat")             # author-written
    out, log = _apply(s, [_pair()], _pair_calls())
    assert out == CW0925_TLDR and log.get("pair_standing_corrected") == 1
    assert log["audit"][0]["rule"] == "pair_standing"


def test_U3_the_standing_is_read_from_the_leg_named_first_either_order_agrees():
    s = "Chicago wheat settles 180.5 US cents/bushel over corn on the December 2026 contracts [N15]."  # author-written
    out, log = _apply(s, [_pair()], _pair_calls())
    assert out == s and log.get("pair_standing_agreed") == 1


def test_U3_a_historical_document_sentence_without_the_spreads_handle_is_counted_never_touched():
    out, log = _apply(CW_E2, [_pair()], _pair_calls())
    assert out == CW_E2 and log.get("pair_standing_unanchored") == 1


def test_U3_a_phrase_whose_object_is_a_figure_is_not_a_standing():
    s = "Corn fell 12 cents over 5 sessions while wheat rose [N15]."                 # author-written
    out, log = _apply(s, [_pair()], _pair_calls())
    assert out == s and "audit" not in log


def test_U3_a_segment_carrying_a_declared_edges_words_is_withheld_as_an_inference():
    s = "Corn settles above Chicago wheat, which it substitutes for in the ration [N15]."  # author-written
    s = s.replace(", which", " which")
    pair = _pair(edges=[{"from": "soft_red_winter_wheat_cbot", "onto": "corn_cbot", "relation": "substitutes_for",
                         "sign": "-", "lag": "0-2q", "declared": "wheat", "class": False}])   # lane R's edge shape
    out, log = _apply(s, [pair], _pair_calls())
    assert out == s and log.get("pair_standing_in_inference") == 1


def test_U3_a_refused_or_malformed_pair_is_no_fact():
    assert V._pair_pool([_pair(legs=["corn_cbot"])]) == ()
    assert V._pair_pool([_pair(standing="sideways")]) == ()
    assert V._pair_pool(None) == ()


# ═════════════════════════════════════════ U-9 EPISODE VERDICT ═══════════════════════════════════════════════
ON = "over the named window of one of the past episodes"
MIDS = {"aligned": "the declared relation held " + ON,
        "at_odds": "the two moves sat at odds with the declared relation " + ON}


def _stamp(a, b, verdict, hs=None):
    d = {"legs": [a, b], "relation": "competes_with", "sign": "-", "verdict": verdict,
         "verdict_words": dict(MIDS)}
    if hs:
        d["handles"] = ["N%d" % hs[0], "N%d" % hs[1]]
    return d


MAX_CELLS = (("soybeans", "rapemeal", "aligned"), ("soybeans", "rapeoil", "aligned"), ("soybeans", "meal", "aligned"),
             ("meal", "oil", "at_odds"), ("oil", "palm", "at_odds"))
MAX_H = {"soybeans": 242, "rapemeal": 243, "rapeoil": 245, "meal": 246, "oil": 247, "palm": 248}


def _max_calls():
    """LANE T's LANDED SHAPE (`cascade.cw_episode_verdict` at its call site): ONE dict per call -- the child's call
    carries its own cell with `handles` naming both legs; a parent's call carries a copy of the FIRST cell it leads
    only where it carries none yet."""
    c = _calls(250)
    for a, b, v in MAX_CELLS:
        st = _stamp(a, b, v, (MAX_H[a], MAX_H[b]))
        c[MAX_H[b] - 1]["episode_verdict"] = st
        if "episode_verdict" not in c[MAX_H[a] - 1]:
            c[MAX_H[a] - 1]["episode_verdict"] = dict(st)
    return c


def _max_calls_listed():
    """The contract's other admissible form: every cell a call is a leg of, as a list (no `handles`)."""
    c = _calls(250)
    for a, b, v in MAX_CELLS:
        for leg in (a, b):
            c[MAX_H[leg] - 1].setdefault("episode_verdict", []).append(_stamp(a, b, v))
    return c


# 09-29 SITTING 3 VERIFIER RE-BANK (S3-V1, the writer-freedom revert; VERIFY.md sec 1): THE U-9 VERDICT ARM IS UNWIRED
# (`verify._VCtx.verd` is empty), because on the fifty its only fires were FALSE corrections (the 0923 deep-2024 page's
# aligned "held" clauses rewritten to the at-odds line words by proximity to the one cited at-odds cell). Every U-9 pin
# below keeps its claim that a served / agreeing / ambiguous clause is left byte for byte; the pins that asserted a
# correction or a verdict count now assert the unwired arm touches nothing. Lane T's stamp (the fact) is still read.
@pytest.mark.parametrize("sent", [MAX_MEAL_OIL, MAX_RAPEOIL, MAX_MEAL])
def test_U9_the_served_consequence_reads_agree_and_are_left_byte_for_byte(sent):
    out, log = _apply(sent, [], _max_calls())
    assert out == sent and "audit" not in log and not log.get("verdict_corrected")


def test_U9_S3V1_the_verdict_arm_is_UNWIRED_and_rewrites_no_clause_to_the_lines_words():
    s = MAX_MEAL_OIL.replace("the two moves sat at odds with the declared relation over that window",
                             "the relation held over that window")               # author-written
    out, log = _apply(s, [], _max_calls())
    assert out == s and not log.get("verdict_corrected") and "audit" not in log
    assert V._verdict_cells(_max_calls()) and V._VCtx(_max_calls(), None).verd == {}


def test_U9_S3V1_MV1_an_aligned_clause_whose_cell_is_uncited_is_never_rewritten_by_proximity():
    """THE MEASURED FALSE CORRECTION (0923 deep-2024 served page, verifier probe `mv1_verdict_probe.py`): the aligned
    clauses carry no handle and the one cited group is the AT-ODDS meal -> oil cell. HEAD's page, byte for byte --
    the regression guard any rebuilt verdict check must pass (bind by the legs the clause names, never by proximity)."""
    s = ("Within that window the complex did not move as one: the crush link into meal held, and the rapeseed links "
         "held, but the meal-to-oil relation sat at odds with what the boards did, with soybean oil down -8.11 % "
         "[N247] alongside meal.")                                                # the served page's shape
    out, log = _apply(s, [], _max_calls())
    assert out == s and not log.get("verdict_corrected") and "audit" not in log


def test_U9_a_parents_copy_of_its_first_childs_cell_binds_nothing():
    s = "- CBOT soybeans fell -9.95 % [N242]; the read: the two moves sat at odds."  # author-written
    out, log = _apply(s, [], _max_calls())                   # N242 carries (soybeans, rapemeal) aligned as a COPY
    assert out == s and "audit" not in log and not log.get("verdict_agreed")


def test_U9_listed_stamps_a_leg_of_cells_the_record_reads_differently_is_left_and_counted():
    out, log = _apply(MAX_MEAL, [], _max_calls_listed())   # meal: child of an aligned cell, parent of an at_odds
    assert out == MAX_MEAL and not log.get("verdict_corrected")          # S3-V1 re-bank: left, the arm unwired


def test_U9_a_clause_is_read_against_BOTH_neighbouring_handle_groups():
    c = _calls(70)
    for j, (a, b, v) in {65: ("soybeans", "rapemeal", "aligned"), 66: ("soybeans", "rapeoil", "aligned"),
                         67: ("soybeans", "meal", "aligned"), 68: ("meal", "oil", "at_odds")}.items():
        c[j - 1]["episode_verdict"] = [_stamp(a, b, v)]
    out, log = _apply(DEEP2024_FORK, [], c)
    assert out == DEEP2024_FORK and not log.get("verdict_corrected")     # S3-V1 re-bank: left, the arm unwired


def test_U9_undetermined_corrects_nothing():
    c = _max_calls()
    c[246]["episode_verdict"] = _stamp("meal", "oil", "undetermined", (246, 247))
    s = MAX_MEAL_OIL.replace("the two moves sat at odds with the declared relation over that window",
                             "the relation held over that window")               # author-written
    out, log = _apply(s, [], c)
    assert out == s and not log.get("verdict_corrected")


def test_U9_a_clause_carrying_a_figure_is_not_a_verdict_clause():
    s = "- soyoil moved -8.11 % [N247]; soyoil held at 66.93 US cents/lb."            # author-written
    out, log = _apply(s, [], _max_calls())
    assert out == s and "audit" not in log


def test_U9_calls_without_the_stamp_are_heads_reading():
    assert V._verdict_cells(_calls(5)) == {}
    ctx = V._VCtx(_calls(5), None)
    assert not (ctx.thr or ctx.pairs or ctx.verd) and ctx.board is False


# ═════════════════════════════════════════ U-10 (a) THE STRIKE RE-JOINS ══════════════════════════════════════
def _strike(served_scalars):
    st = {"tldr": "", "mechanism": TARIFF_STRIKE, "sources": []}
    kw = {} if served_scalars is None else {"served_scalars": served_scalars}
    rep = V.verify_citations(st, [], [_call(value=25.0), _call(value=30.0)], **kw)
    return st["mechanism"], rep


def test_U10a_a_board_turns_strike_leaves_one_separator_never_two():
    from leviathan.graphrag.state import rows as ROWS
    assert callable(getattr(ROWS, "splice", None)), "lane R's splice producer (CONTRACT Z8) is not on this tree"
    out, rep = _strike([])
    assert out == ("Lag and aftermath in the 2018 case: duties spring 2018 [N1], with WASDE registering the trade "
                   "effect by 12 July 2018.")
    assert rep["by_rule"] == {"index_out_of_range": 1} and rep.get("strike_rejoined") == 1
    assert rep.strip_seams and rep.strip_seams[0]["src"] == "verify"


def test_U10a_board_off_keeps_heads_strike_byte_for_byte():
    out, rep = _strike(None)
    assert ",," in out and "strike_rejoined" not in rep
    assert rep["by_rule"] == {"index_out_of_range": 1}


def test_U10a_a_splice_answer_that_widens_over_a_word_is_refused(monkeypatch):
    from leviathan.graphrag.state import rows as ROWS
    monkeypatch.setattr(ROWS, "splice", lambda text, a, b, name="", **k: (a - 10, b, ""), raising=False)
    out, rep = _strike([])
    assert ",," in out and "strike_rejoined" not in rep


def test_U10a_no_producer_on_the_tree_is_heads_span(monkeypatch):
    from leviathan.graphrag.state import rows as ROWS
    monkeypatch.delattr(ROWS, "splice", raising=False)
    out, rep = _strike([])
    assert ",," in out and "strike_rejoined" not in rep


# ═════════════════════════════════════════ S2 V-1 (Z28) THE FOLDED ROW'S OWN WEEK ════════════════════════════
def _fold_call(display=None, period="2025-09-26..2026-09-26"):
    c = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "soybeans_cbot",
                   "country": None, "period": period, "asof": "2026-09-26", "agg": "latest"},
         "rows": [{"period": "2027", "value": 775.39197, "unit": "1000 MT", "knowledge_date": "20260924",
                   "data_date": "2026-09-17", "_fold": {"axis": "destination", "rule": "sum", "n": 36}}],
         "status": "ok"}
    if display:
        c["display"] = display
    return c


def test_Z28_under_the_analyst_stamp_a_folded_row_read_over_a_window_names_its_own_week():
    lab = C.from_number(_fold_call("analyst"), 16).label
    assert "summed over every destination 2026-09-17 = 775.39" in lab
    assert "2025-09-26" not in lab and "week to 17 September 2026" in lab


def test_Z28_off_the_stamp_the_label_is_heads():
    lab = C.from_number(_fold_call(), 16).label
    assert "summed over every destination 2026-09-17 2025-09-26..2026-09-26 = 775.392" in lab


def test_Z28_a_query_period_that_is_a_period_of_its_own_is_kept():
    lab = C.from_number(_fold_call("analyst", period="2026"), 16).label
    assert "2026-09-17" in lab and "2026/27" in lab
