# -*- coding: utf-8 -*-
"""09-29 FIX SITTING 4, LANE V -- the pair standing bound by what its clause cites (V4-1, CONTRACT C4-3), the judged
figure's citation after its noun phrase (V4-3, C4-6), the threshold relation read with its polarity (V4-4, C4-5), the
verdict check rebuilt and left UNWIRED (V4-5, C4-7), the public name of the numeral grammar (V4-2 / V4-6 V half,
C4-4), and citations.py's halves of R4-2 (the display unit under the analyst stamp, C4-10) and T4-1 (the numbers
ledger names each conflict, C4-16).

Sentences quoted as "served" are verbatim banked prose (the 09-29 smoke pages, the opus5_plain probe pages, arm A and
the 09-23 / 09-24 / 09-25 re-smokes -- the lane's drive `fix_sitting_4_0929/v_work/drive_v4.py` reads the same pages
through head_s4 and the tree). Author-written sentences are marked and pin a fence, never a corpus claim: the negative
corpus is the 63 banked pages, run by the drive. The scalar dicts are the CONTRACT's shapes (lane R's registrations,
lane T's call stamp); the book words are passed on the scalar exactly as the registration carries them."""
import copy

import pytest
from leviathan.graphrag import citations as C
from leviathan.graphrag import verify as V

EM = "—"
TW = {"past": ["past", "beyond", "crossed"], "inside": ["inside", "short of", "within", "not yet at"]}
# the book's `pair_standing_words` as C4-3 declares it (the attributive at each "... than" list's tail) and as HEAD had it
PW4 = {"under": ["under", "below", "at a discount to", "cheaper than", "cheaper"],
       "over": ["over", "above", "at a premium to", "dearer than", "dearer"], "level": ["level with", "even with"]}
PW_HEAD = {"under": ["under", "below", "at a discount to", "cheaper than"],
           "over": ["over", "above", "at a premium to", "dearer than"], "level": ["level with", "even with"]}
CORN, SRW = "corn_cbot", "soft_red_winter_wheat_cbot"
CORN_PX = "corn_cbot||silver_futures_eod|corn_cbot|2026-12"                       # render.tape_row_id's spelling
SRW_PX = "soft_red_winter_wheat_cbot||silver_futures_eod|soft_red_winter_wheat_cbot|2026-12"
PALM_RID = "malaysian_crude_palm_oil_cme|drought|drought_z|malaysian_crude_palm_oil_cme|SE Asia Palm Belt"


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


def _apply(text, pool, calls):
    ctx = V._VCtx(calls, pool)
    log = {"field": "mechanism"}
    return V._apply_direction_edits(text, ctx, log), log


# ═════════════════════════════════════════ V4-1 THE PAIR STANDING ════════════════════════════════════════════
# smoke 09-29 run 1, quick corn/wheat, the TL;DR (served, verbatim; HEAD served "dearer" beside "corn under wheat")
CW_SMOKE_TLDR = ("Corn's US sheet is the tight one and wheat's is the loose one: corn's stocks-to-use sits at 12.14% of "
                 "domestic use [N11], in the 16th percentile of its own record [N49] and past the desk's tight line, "
                 "against 65.22% for all-classes US wheat [N12] " + EM + " so the feed-substitution edge runs in "
                 "wheat's favour, with corn the dearer grain per bushel ([N63] 527.5 US cents/bushel for December 2026 "
                 "corn against [N69] 707 for December 2026 CBOT srw wheat, a gap the record prints only as the spread "
                 "[N13] of -179.5 US cents/bushel, corn under wheat).")
CW_SMOKE_MECH = ("Which leg dominates is set by the relative price, and on this settle corn sits under wheat [N13] " + EM +
                 " meaning wheat is not the cheap ration grain here, so the substitution channel is not currently "
                 "draining corn feed demand.")                                # smoke 09-29 run 1 corn/wheat, served
CW_E2 = ("- Documents: the feed-substitution link is documented " + EM + " corn became the cheaper feed ingredient "
         "and feed corn use rose at wheat's expense in MY2021/22 [E1]; feed wheat was expected cheaper than domestic "
         "corn in MY2018/19 [E2]; and in April 2011 corn feed and residual use was cut as SRW prospects improved "
         "[E4].")                                                                    # arm A treatment corn/wheat


def _pair(words=None, value=-179.5, handle=13, levels=True, edges=True):
    out = []
    if levels:
        out += [{"kind": "level", "value": 527.5, "unit": "US cents/bushel", "row_id": CORN_PX, "handle": 63},
                {"kind": "level", "value": 707.0, "unit": "US cents/bushel", "row_id": SRW_PX, "handle": 69}]
    d = {"value": value, "unit": "US cents/bushel", "kind": "pair_relation", "handle": handle, "legs": [CORN, SRW],
         "standing": "under" if value < 0 else "over", "standing_words": copy.deepcopy(words or PW4),
         "row_id": "%s|pair_level_spread|%s" % (CORN, SRW)}
    if edges:
        d["edges"] = [{"from": SRW, "onto": CORN, "relation": "substitutes_for", "sign": "-", "lag": "0-2q",
                       "declared": "wheat", "class": False}]
    return out + [d]


def _cw_calls():
    return _calls(80, {13: _call("silver_futures_eod", "settle difference, CBOT corn minus CBOT srw wheat", -179.5,
                                 "US cents/bushel", "%s|pair_level_spread|%s" % (CORN, SRW)),
                       63: _call("silver_futures_eod", "settle", 527.5, "US cents/bushel", CORN_PX),
                       69: _call("silver_futures_eod", "settle", 707.0, "US cents/bushel", SRW_PX),
                       11: _call("silver_psd", "su_ratio", 12.14, "%",
                                 "corn_cbot|ending_stocks_su_ratio|psd_ending_stock_su_ratio|corn_cbot|United States"),
                       49: _call("silver_psd", "su_ratio", 16, "percentile",
                                 "corn_cbot|ending_stocks_su_ratio|psd_ending_stock_su_ratio|corn_cbot|United States"),
                       12: _call("silver_psd", "su_ratio", 65.22, "%",
                                 "soft_red_winter_wheat_cbot|ending_stocks|psd_ending_stock_su_ratio|"
                                 "soft_red_winter_wheat_cbot|United States")})


def test_V41_the_smoke_tldr_attributive_dearer_bound_by_the_spread_in_its_parenthetical_is_corrected():
    out, log = _apply(CW_SMOKE_TLDR, _pair(), _cw_calls())
    assert out == CW_SMOKE_TLDR.replace("corn the dearer grain", "corn the cheaper grain")
    assert log.get("pair_standing_corrected") == 1 and log.get("pair_standing_attributive") == 1
    assert log.get("pair_standing_agreed") == 1                     # "corn under wheat" in the same clause agrees
    a = log["audit"][0]
    assert (a["rule"], a["before"], a["after"], a.get("bound")) == ("pair_standing", "dearer", "cheaper", "spread")


def test_V41_heads_book_without_the_attributive_leaves_dearer_and_binds_the_standing_through_the_clause():
    out, log = _apply(CW_SMOKE_TLDR, _pair(words=PW_HEAD), _cw_calls())
    assert out == CW_SMOKE_TLDR                                     # no declared phrase: the writer's word stands
    assert log.get("pair_standing_agreed") == 1 and "audit" not in log


def test_V41_bound_by_both_legs_own_price_levels_where_the_clause_cites_no_spread():
    s = CW_SMOKE_TLDR.replace("the spread [N13] of", "the spread of")                   # author-modified: no spread handle
    out, log = _apply(s, _pair(), _cw_calls())
    assert "with corn the cheaper grain per bushel" in out
    assert log.get("pair_standing_bound_by_levels") == 2 and log["audit"][0].get("bound") == "levels"


def test_V41_a_clause_comparing_two_driver_rows_never_binds_a_price_standing():
    s = "Corn's stocks-to-use at 12.14% [N11] sits below wheat's 65.22% [N12], so corn is the dearer feed."  # author
    out, log = _apply(s, _pair(value=179.5), _cw_calls())          # served standing OVER: a price fact
    assert out == s and "audit" not in log                           # the su levels are no leg's price


def test_V41_without_the_legs_price_levels_on_the_pool_the_attributive_needs_the_spread():
    s = CW_SMOKE_TLDR.replace("the spread [N13] of", "the spread of")
    out, log = _apply(s, _pair(levels=False), _cw_calls())
    assert out == s and log.get("pair_standing_unanchored") == 2    # "dearer" and "corn under wheat": nothing cited


def test_V41_an_object_phrase_whose_object_is_not_the_other_leg_is_never_bound():
    s = ("December corn is dearer than a year ago at 527.5 US cents/bushel [N63] while wheat sits at 707 [N69] and "
         "the spread [N13] is -179.5.")                                              # author-written: the fence
    out, log = _apply(s, _pair(), _cw_calls())
    assert out == s and "audit" not in log


def test_V41_the_subject_is_the_nearest_leg_named_before_the_attributive_in_its_clause():
    s = "Corn trades under wheat [N13], so wheat is the dearer grain."              # author-written
    out, log = _apply(s, _pair(), _cw_calls())
    assert out == s and log.get("pair_standing_agreed") == 1       # "corn under wheat" (HEAD); "wheat ... dearer": no clause cite
    s2 = "Corn trades under wheat and wheat is the dearer grain [N13]."             # author-written: one clause
    out2, log2 = _apply(s2, _pair(), _cw_calls())
    assert out2 == s2 and log2.get("pair_standing_agreed") == 2


def test_V41_an_attributive_with_no_leg_before_it_in_its_clause_is_no_pair_standing():
    s = "The dearer grain [N13] is the one the ration drops."                       # author-written
    out, log = _apply(s, _pair(), _cw_calls())
    assert out == s and "audit" not in log and not log.get("pair_standing_unanchored")


def test_V41_a_conditional_clause_bound_only_through_its_clause_is_left_as_written():
    s = "It reads wrong if corn turns the dearer grain [N13] before the December delivery."    # author-written
    out, log = _apply(s, _pair(), _cw_calls())
    assert out == s and log.get("pair_standing_unanchored") == 1


def test_V41_the_documents_sentence_about_past_marketing_years_stays_unanchored():
    out, log = _apply(CW_E2, _pair(), _cw_calls())
    assert out == CW_E2 and log.get("pair_standing_unanchored") == 2 and "audit" not in log


def test_V41_the_served_mechanism_standing_agrees_and_is_left_byte_for_byte():
    out, log = _apply(CW_SMOKE_MECH, _pair(), _cw_calls())
    assert out == CW_SMOKE_MECH and log.get("pair_standing_agreed") == 1


def test_V41_verify_citations_corrects_in_its_own_apply_pass_and_charges_nothing_new():
    calls = _cw_calls()
    st_off = {"tldr": CW_SMOKE_TLDR, "mechanism": "", "sources": []}
    st_on = copy.deepcopy(st_off)
    rep_off = V.verify_citations(st_off, [], copy.deepcopy(calls), served_scalars=[])
    rep_on = V.verify_citations(st_on, [], copy.deepcopy(calls), served_scalars=_pair())
    assert "with corn the cheaper grain per bushel" in st_on["tldr"] and "dearer" not in st_on["tldr"]
    assert "with corn the dearer grain per bushel" in st_off["tldr"]
    assert rep_on["by_rule"] == rep_off["by_rule"] and rep_on["stripped"] == rep_off["stripped"]
    assert rep_on.get("pair_standing_corrected") == 1 and rep_on.get("pair_standing_attributive") == 1


def test_V41_the_legs_price_handles_are_the_tapes_level_scalars_only():
    pool = _pair() + [{"kind": "level", "value": 12.14, "unit": "%", "handle": 11,
                       "row_id": "corn_cbot|ending_stocks_su_ratio|psd_ending_stock_su_ratio|corn_cbot|United States"},
                      {"kind": "window_change", "value": 88.0, "unit": "US cents/bushel", "handle": 67,
                       "row_id": CORN_PX}]
    f = V._pair_pool(pool)[0]
    assert f["levels"] == (frozenset({63}), frozenset({69}))
    assert f["attributive"] == frozenset({("under", 4), ("over", 4)})
    assert V._pair_pool(_pair(words=PW_HEAD))[0]["attributive"] == frozenset()


def test_V41_the_clause_runs_through_a_parenthetical_and_stops_at_the_sentences_own_break():
    m = V._mask_handles(CW_SMOKE_TLDR)
    cl = V._clause_spans(m)
    tail = [c for c in cl if "dearer" in m[c[0]:c[1]]][0]
    assert "corn under wheat)" in m[tail[0]:tail[1]] and "favour" not in m[tail[0]:tail[1]]
    assert len(V._segment_spans(m)) > len(cl)


# ═════════════════════════════════════════ V4-3 THE CITATION AFTER ITS NOUN PHRASE ═══════════════════════════
def _thr(label="severe", jh=14, relation="past", noun="line", rid=PALM_RID):
    d = {"value": 2.0, "unit": "sigma", "kind": "card_threshold", "row_id": rid, "threshold_row_id": rid,
         "label": label, "line": 2.0, "judged": "z", "judged_value": 2.665, "judged_handle": jh,
         "relation": relation, "relation_words": copy.deepcopy(TW), "text": "two sigma"}
    if noun:
        d["head_noun"] = noun
    return d


def _palm(level=13, n=40):
    return _calls(n, {level: _call("gold_weather_z", "drought_z", 1.2491708897603446, "z", PALM_RID),
                      level + 1: _call("gold_weather_z", "drought_z", 2.7, "sigma", PALM_RID),
                      level + 2: _call("gold_weather_z", "drought_z", 97, "percentile", PALM_RID)})


# the raw drafts of the smoke / probe sentences HEAD served as "severe [N14] line [N13]" etc. (raw_draft.preverify_*)
PR_SMOKE_TLDR = ("From here the two read differently: Malaysian palm is heavy in the near term but carries a "
                 "right-tailed drought reading past the severe line [N13] that the model works with a two-to-four-"
                 "quarter lag.")                                     # smoke 09-29 palm/rape TL;DR (shortened)
PR_SMOKE_MECH = ("- **SE Asia palm-belt dry-day run** [N13], 1.25 z, August 2026: past the severe line (drawn at two "
                 "sigma) with three months rising; the lag window it would act in runs 28 February 2027 to 31 August "
                 "2027.")                                                      # smoke 09-29 palm/rape mechanism
S24_MECH = ("- **US dry-spell length** [N13] -0.67 z, January 2024, past the notable line on the wet side, window "
            "2024-01-31 to 2024-04-30.")                           # smoke 09-29 run 1, 2024 (handles renumbered)
PROBE_PALM = "- **The palm belt dry-run print** [N13], now 1.25 z, past the severe line at two sigma and rising three months."
PROBE_COCOA = ("On palm it compounds with the largest move on the board " + EM + " the SE Asia dry-day run at 1.25 z, "
               "97th percentile, rising three months, past the line called severe [N13], with a quarter of the basin's "
               "cells at or beyond two sigma.")                               # probe max cocoa (handles renumbered)


def test_V43_the_smoke_tldr_citation_joins_the_writers_group_after_the_noun():
    out, log = _apply(PR_SMOKE_TLDR, [_thr()], _palm())
    assert "past the severe line [N13, N14] that the model" in out and "severe [N14]" not in out
    assert log.get("threshold_cited") == 1 and log["audit"][0].get("joined") is True


def test_V43_after_the_head_noun_never_between_the_label_and_its_noun():
    for s, want in ((PR_SMOKE_MECH, "past the severe line [N14] (drawn at two sigma)"),
                    (S24_MECH.replace("notable", "notable"), "past the notable line [N14] on the wet side,"),
                    (PROBE_PALM, "past the severe line [N14] at two sigma and rising")):
        lab = "notable" if "notable" in s else "severe"
        out, log = _apply(s, [_thr(label=lab)], _palm())
        assert want in out, (s, out)
        assert "%s [N14] line" % lab not in out and log.get("threshold_cited") == 1


def test_V43_a_noun_before_the_label_places_the_citation_after_the_label_joining_the_group():
    out, log = _apply(PROBE_COCOA, [_thr()], _palm())
    assert "past the line called severe [N13, N14], with a quarter" in out and log.get("threshold_cited") == 1


def test_V43_no_head_noun_registered_places_it_at_the_end_of_the_threshold_words():
    s = "- **The palm belt** [N13]: 1.25 z, past the severe line with three months rising; next print in October."
    out, log = _apply(s, [_thr(noun="")], _palm())                              # author-written: the fallback
    assert "past the severe line with three months rising [N14]; next print" in out


def test_V43_a_figure_ending_the_threshold_words_places_nothing_and_is_counted():
    s = "- **The palm belt** [N13]: past the severe mark at 2.7 sigma, three months rising."    # author-written
    out, log = _apply(s, [_thr()], _palm())
    assert out == s and log.get("threshold_unanchored") == 1 and not log.get("threshold_cited")


def test_V43_a_range_or_non_canonical_group_is_followed_never_joined():
    for grp in ("[N20-N22]", "[N20,N22]", "[E2]"):
        s = "The palm belt [N13] reads past the severe line %s that the model lags." % grp  # author-written
        out, log = _apply(s, [_thr()], _palm())
        assert (grp + " [N14]") in out, (grp, out)


def test_V43_the_correct_arms_adjacency_is_heads_a_falsifier_before_its_rows_handle_is_left():
    s = "- **The palm belt** [N13]: wrong if the next print turns back inside the severe line [N14]."   # author-written
    out, log = _apply(s, [_thr()], _palm())
    assert out == s and log.get("threshold_unanchored") == 1


# ═════════════════════════════════════════ V4-4 THE RELATION WITH ITS POLARITY ═══════════════════════════════
def test_V44_a_negated_relation_contradicting_the_served_one_gains_no_citation():
    s = "- **The palm-belt dry spell** [N13]: 1.25 z, not yet past the severe line, which sits at two sigma."  # probe
    out, log = _apply(s, [_thr()], _palm())
    assert out == s and log.get("threshold_negated_unanchored") == 1 and not log.get("threshold_cited")


def test_V44_a_negated_relation_beside_the_judged_figure_is_corrected_negator_and_phrase_together():
    s = "- **The palm-belt dry spell** [N13]: 2.7 sigma [N14], not yet past the severe line."          # author
    out, log = _apply(s, [_thr()], _palm())
    assert out == "- **The palm-belt dry spell** [N13]: 2.7 sigma [N14], past the severe line."
    assert log.get("threshold_negated_corrected") == 1 and log["audit"][0]["rule"] == "threshold_negated"


def test_V44_a_negated_relation_that_agrees_with_an_inside_fact_is_cited():
    s = "- **The palm-belt dry spell** [N13]: 1.25 z, not yet past the severe line, which sits at two sigma."
    out, log = _apply(s, [_thr(relation="inside")], _palm())
    assert "not yet past the severe line [N14], which" in out
    assert log.get("threshold_negated_agreed") == 1 and log.get("threshold_cited") == 1


def test_V44_a_negator_between_the_relation_and_its_label_negates_the_label_and_is_never_corrected():
    s = "- **The palm-belt dry spell** [N13] is past its record but not severe."                      # probe
    out, log = _apply(s, [_thr()], _palm())
    assert out == s and log.get("threshold_negated_unanchored") == 1
    s2 = "- **The palm-belt dry spell** 2.7 sigma [N14] is past its record but not severe."          # author
    out2, log2 = _apply(s2, [_thr()], _palm())
    assert out2 == s2 and log2.get("threshold_negated_unanchored") == 1


def test_V44_a_conditional_negated_relation_is_no_present_relation():
    s = "- **The palm-belt dry spell** [N13] [N14]: wrong if the next print is not yet past the severe line."
    out, log = _apply(s, [_thr()], _palm())                                   # author-written
    assert out == s and log.get("threshold_negated_unanchored") == 1


def test_V44_the_phrases_own_negator_is_the_phrases_word_and_a_double_negative_agrees():
    s = "- **The palm-belt dry spell** [N13]: 1.25 z, not yet at the severe line, which sits at two sigma."
    out, log = _apply(s, [_thr(relation="inside")], _palm())                  # author: "not yet at" IS the phrase
    assert "not yet at the severe line [N14]" in out and not log.get("threshold_negated_agreed")
    s2 = "- **The palm-belt dry spell** [N13]: 1.25 z, not short of the severe line, which sits at two sigma."
    out2, log2 = _apply(s2, [_thr()], _palm())                                # author: not + inside = past
    assert "not short of the severe line [N14]" in out2 and log2.get("threshold_negated_agreed") == 1


def test_V44_an_unnegated_relation_reads_exactly_as_head():
    s = "- **The palm-belt dry spell** [N13]: 2.7 sigma [N14], short of the severe line."
    out, log = _apply(s, [_thr()], _palm())
    assert out == "- **The palm-belt dry spell** [N13]: 2.7 sigma [N14], beyond the severe line."
    assert log.get("threshold_corrected") == 1 and not log.get("threshold_negated_corrected")


# ═════════════════════════════════════════ V4-5 THE VERDICT CHECK, REBUILT (UNWIRED) ══════════════════════════
ON = "over the named window of one of the dated windows on the record"
MIDS = {"aligned": "the declared relation held " + ON,
        "at_odds": "the two moves sat at odds with the declared relation " + ON}
MEAL, OIL, BEANS, PALM = "soybean_meal_cbot", "soybean_oil_cbot", "soybeans_cbot", "malaysian_crude_palm_oil_cme"


def _stamp(a, b, verdict, hs):
    return {"legs": [a, b], "relation": "competes_with", "sign": "-", "verdict": verdict,
            "verdict_words": dict(MIDS), "handles": ["N%d" % hs[0], "N%d" % hs[1]]}


def _vcalls():
    c = _calls(260)
    for a, b, v, ha, hb in ((BEANS, MEAL, "aligned", 242, 246), (MEAL, OIL, "at_odds", 246, 247),
                            (OIL, PALM, "at_odds", 247, 248)):
        c[hb - 1]["episode_verdict"] = _stamp(a, b, v, (ha, hb))
        if "episode_verdict" not in c[ha - 1]:
            c[ha - 1]["episode_verdict"] = dict(_stamp(a, b, v, (ha, hb)))
    return c


def _wired(sent, calls):
    ctx = V._VCtx(calls, [])
    ctx.verd = V._verdict_cells(calls)                  # THE WIRING a verifier would apply -- here only
    log = {}
    return V._verdict_edits(sent, ctx, log), log


def test_V45_the_rebuilt_arm_stays_unwired_on_every_turn():
    calls = _vcalls()
    assert V._verdict_cells(calls) and V._VCtx(calls, []).verd == {} and V._VCtx(calls, None).verd == {}


def test_V45_MV1_the_aligned_clauses_naming_one_leg_never_bind_when_wired():
    s = ("Within that window the complex did not move as one: the crush link into meal held, and the rapeseed links "
         "held, but the meal-to-oil relation sat at odds with what the boards did, with soybean oil down -8.11 % "
         "[N247] alongside meal.")                                          # the MV-1 pin's served shape
    ed, log = _wired(s, _vcalls())
    assert ed == [] and not log.get("verdict_ambiguous")


def test_V45_a_third_markets_name_is_never_split_across_two_legs():
    s = "The palm link onto CBOT soybean oil held over that window."           # author-written
    ed, _log = _wired(s, _vcalls())
    assert ed == []                                     # "CBOT soybean oil" names soybean oil only; palm not named
    assert [x[2] for x in V._market_mentions(V._mask_handles(s), 0, len(s), V._market_words([OIL, PALM, BEANS]))] \
        == [OIL]


def test_V45_a_clause_naming_both_legs_that_contradicts_has_only_its_verdict_run_replaced():
    s = "- The relation of CBOT soybean meal to CBOT soybean oil held over that window."           # author-written
    ed, _log = _wired(s, _vcalls())
    assert len(ed) == 1
    a, b, v, e = ed[0]
    assert s[a:b] == "held" and v == "two moves sat at odds with" and e["verdict"] == "at_odds"
    out = s[:a] + v + s[b:]
    assert out == "- The relation of CBOT soybean meal to CBOT soybean oil two moves sat at odds with over that window."
    # ^ THE CONTRACTED REPLACEMENT (C4-7: the run only, never the clause) IS UNGRAMMATICAL on a real fire -- pinned so
    #   the wiring call reads it (the drive's flip probe shows the same on the banked clauses): one reason it is unwired


def test_V45_a_clause_naming_the_legs_of_cells_read_two_ways_is_ambiguous():
    s = "- The relations among CBOT soybeans and CBOT soybean meal and CBOT soybean oil held."  # author-written
    ed, log = _wired(s, _vcalls())
    assert ed == [] and log.get("verdict_ambiguous") == 1


def test_V45_an_agreeing_clause_is_left_and_counted():
    s = "- CBOT soybean meal and CBOT soybean oil sat at odds with the relation."                # author-written
    ed, log = _wired(s, _vcalls())
    assert ed == [] and log.get("verdict_agreed") == 1


# ═════════════════════════════════════════ V4-2 / V4-6 THE NUMERAL GRAMMAR'S PUBLIC NAME ═════════════════════
def test_V42_the_public_name_is_the_grammar_itself_never_a_copy():
    assert V.claim_number_spans is V._claim_number_spans
    s = "bottoming at [N34] the 3rd percentile in February 2024"               # smoke 09-29 2024 raw draft
    assert [v for _a, _b, v in V.claim_number_spans(V._mask_handles(s))] == [3.0]


# ═════════════════════════════════════════ C4-16 THE LEDGER NAMES ITS CONFLICTS ══════════════════════════════
def _gw(value, knowledge="2026-09-10", **kw):
    c = {"query": {"table": "gold_weather_z", "metric": "tmax_anomaly_z", "commodity": "cocoa", "country": "Ghana",
                   "period": "2026-08"},
         "rows": [{"period": "2026-08", "value": value, "unit": "z", "knowledge_date": knowledge}], "status": "ok"}
    c.update(kw)
    return c


def test_C416_an_identity_served_at_two_values_is_named_with_both_values_and_both_handles():
    led = C.NumbersLedger([_call(value=5.0)] * 3, n_start=1)
    h1, r1 = led.address(_gw(0.42))
    h2, r2 = led.address(_gw(0.57))
    h3, r3 = led.address(_gw(0.42))
    assert (h1, r1, h2, r2, h3, r3) == (4, False, 5, False, 4, True)
    st = led.stamp()
    assert st["identity_value_conflict"] == 1
    assert st["conflicts"] == [{"row_id": "gold_weather_z|cocoa|Ghana|2026-08|tmax_anomaly_z", "values": [0.42, 0.57],
                                "handles": [4, 5]}]
    assert led.conflict_of(5) == {"with": 4, "values": [0.42, 0.57],
                                  "row_id": "gold_weather_z|cocoa|Ghana|2026-08|tmax_anomaly_z"}
    assert led.conflict_of(4) is None


def test_C416_no_conflict_keeps_heads_three_keys():
    led = C.NumbersLedger([], n_start=1)
    led.address(_gw(0.42))
    led.address(_gw(0.42))
    assert led.stamp() == {"issued": 1, "reused": 1, "identity_value_conflict": 0}


def test_C416_the_stamp_is_a_route_key_and_never_moves_the_identity():
    led = C.NumbersLedger([], n_start=1)
    ic = {"with": 4, "values": [0.42, 0.57], "row_id": "x"}
    assert led.identity(_gw(0.57, identity_conflict=ic)) == led.identity(_gw(0.57))
    assert C.NUMBERS_LEDGER_ROUTE_CALL_KEYS[:4] == ("_row_id", "shown", "display", "_sb")


def test_C416_the_second_handles_line_names_the_first_under_the_analyst_stamp_only():
    ic = {"with": 4, "values": [0.42, 0.57], "row_id": "x"}
    lab_a = C.from_number(_gw(0.57, identity_conflict=ic, display="analyst"), 5).label
    lab_off = C.from_number(_gw(0.57, identity_conflict=ic), 5).label
    assert "(the same series also reads" in lab_a and "at [N4])" in lab_a and "0.42" in lab_a
    assert lab_off == C.from_number(_gw(0.57), 5).label and "same series" not in lab_off
    assert "same series" not in C.from_number(_gw(0.57, display="analyst", identity_conflict={"with": "x"}), 5).label


# ═════════════════════════════════════════ C4-10 THE DISPLAY UNIT ON THE FOOTER ══════════════════════════════
def _esr(display=None):
    c = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "soybeans_cbot",
                   "country": None, "period": "2026", "asof": "2026-09-26", "agg": "latest"},
         "rows": [{"period": "2026", "value": 775.39197, "unit": "1000 MT", "knowledge_date": "20260924",
                   "data_date": "2026-09-17"}], "status": "ok"}
    if display:
        c["display"] = display
    return c


def test_C410_under_the_analyst_stamp_the_unit_prints_through_the_one_producer(monkeypatch):
    from leviathan.graphrag.state import rows as ROWS
    monkeypatch.setattr(ROWS, "display_unit", lambda u: "thousand tonnes" if u == "1000 MT" else u, raising=False)
    cit = C.from_number(_esr("analyst"), 16)
    assert "thousand tonnes" in cit.label and "1000 MT" not in cit.label
    assert cit.unit == "1000 MT"                                   # the served unit itself is never rewritten


def test_C410_off_the_stamp_the_label_is_heads(monkeypatch):
    from leviathan.graphrag.state import rows as ROWS
    monkeypatch.setattr(ROWS, "display_unit", lambda u: "thousand tonnes", raising=False)
    assert "1000 MT" in C.from_number(_esr(), 16).label


@pytest.mark.parametrize("fn", [None, (lambda u: ""), (lambda u: 1 / 0)])
def test_C410_no_producer_a_blank_or_a_failing_one_prints_the_stored_unit(monkeypatch, fn):
    from leviathan.graphrag.state import rows as ROWS
    if fn is None:
        monkeypatch.delattr(ROWS, "display_unit", raising=False)
    else:
        monkeypatch.setattr(ROWS, "display_unit", fn, raising=False)
    assert "1000 MT" in C.from_number(_esr("analyst"), 16).label
