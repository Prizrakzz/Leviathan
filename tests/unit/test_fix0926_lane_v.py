# -*- coding: utf-8 -*-
"""09-26 FIX SITTING, LANE V -- the verifier holds the WORDS the block printed with a figure (V-1) and reads a
declaration's date instead of slicing it (V-2). CONTRACT P4 / P5 / P7 (fix_sitting_0926/CONTRACT.md).

Every sentence quoted as a "served" sentence below is verbatim arm-A 09-26 prose (treatment quick palm/rapeoil,
the deep China-tariff turn, the 09-23 deep and max soybean turns); the pools are CONTRACT P5's scalar shape, the
shape lane R's `Block.scalar` registers. Author-written sentences are marked as such and pin a fence, never a
corpus claim (the negative corpus is the eighty, run by fix_sitting_0926/V/b22_direction.py)."""
import copy

from leviathan.graphrag import verify as V

EM = "—"
RID_EU = "french_rapeseed_matif|ending_stocks_su_ratio|psd_ending_stock_su_ratio|french_rapeseed_matif|European Union"
VOCAB_SU = {"up": ("rising", "loosening"), "down": ("falling", "tightening")}

# ---- served prose (arm A 09-26, treatment quick palm/rapeoil, post-verify) -------------------------------------
TLDR_F2 = ("From here the two lean opposite ways: palm's building inventory is price-pressuring near-term while a "
           "severe dry-spell reading in the palm belt [N14] loads a right tail into late 2026 into 2027, whereas "
           "rapeseed's loosening sits on a European balance sheet that is itself loosening [N62].")
FAN_F1 = ("It is one reading declared on thirty-four other markets " + EM + " twenty-eight in the same direction, "
          "six opposite.")
PER_MARKET = ("Its signs differ by market and must be kept apart: on palm the model declares it in the same "
              "direction at two-to-four quarters, high confidence; on MATIF rapeseed, ICE canola and ZCE rapeseed "
              "oil it is declared in the opposite direction at one-to-three quarters, low confidence.")
CHAIN_EXPECT = ("European stocks-to-use then sits at 9.42 % [N62], falling since 2025, and the model expects it to "
                "move palm the opposite way; there the readings agree.")
# ---- served prose (09-23 re-smoke, deep and max soybeans) -- correct as written, and not a whole sign phrase
RUN_ON_0923 = ("it is declared on twenty-three other markets, twenty-two the same way, the nearest being ICE raw "
               "sugar at zero to two quarters, high confidence.")


def _calls(n=62, **tail):
    calls = [{"query": {"table": "t", "metric": "m"}, "rows": [{"value": 1.0}], "status": "ok"} for _ in range(n)]
    calls[61] = {"query": {"table": "silver_psd", "metric": "su_ratio", "country": "European Union"},
                 "rows": [{"value": 9.417142857142856, "unit": "%"}], "status": "ok", "_row_id": RID_EU}
    calls[13] = {"query": {"table": "gold_weather_z", "metric": "drought_z", "country": "SE Asia Palm Belt"},
                 "rows": [{"value": 1.2491708897603446, "unit": "z"}], "status": "ok",
                 "_row_id": "malaysian_crude_palm_oil_cme|drought|drought_z|malaysian_crude_palm_oil_cme|SE Asia"}
    return calls


def _run(rid=RID_EU, direction="down", vocab=VOCAB_SU):
    return {"value": 1, "unit": "marketing year", "kind": "run_length", "row_id": rid, "text": "one",
            "words": dict(up="rising", down="falling")[direction], "direction": direction,
            "direction_words": {k: list(v) for k, v in vocab.items()}}


def _fan(total, head, head_words, rest, rest_words, fid="El_Nino|oni_climate|_global|"):
    from leviathan.graphrag.state.rows import words_for_int as w
    return [{"value": total, "unit": "markets", "kind": "fan_count", "text": w(total), "words": "", "fan_id": fid},
            {"value": head, "unit": "markets", "kind": "fan_count", "text": w(head), "words": head_words,
             "fan_id": fid},
            {"value": rest, "unit": "markets", "kind": "fan_count", "text": w(rest), "words": rest_words,
             "fan_id": fid}]


OPP, SAME = "in the opposite direction", "in the same direction"
FAN_RAPE = _fan(34, 28, OPP, 6, SAME)       # the MATIF / canola / ZCE El Nino row: 28 '-', 6 '+'
FAN_PALM = _fan(34, 29, OPP, 5, SAME)       # palm's own El Nino row: 29 '-', 5 '+'


def _apply(text, pool, calls=None):
    ctx = V._VCtx(calls if calls is not None else _calls(), pool)
    log = {"field": "mechanism"}
    return V._apply_direction_edits(text, ctx, log), log


# ═════════════════════════════════════════ V-1 FAN ═══════════════════════════════════════════════════════════
def test_fan_F1_the_swapped_split_is_corrected_to_the_words_the_block_registered():
    out, log = _apply(FAN_F1, FAN_RAPE + FAN_PALM)
    assert out == ("It is one reading declared on thirty-four other markets " + EM + " twenty-eight in the "
                   "opposite direction, six in the same direction.")
    assert log["corrected"] == 2 and not log.get("fan_ambiguous")
    assert [a["rule"] for a in log["audit"]] == ["fan", "fan"]
    assert {a["before"] for a in log["audit"]} == {"in the same direction", "opposite"}


def test_fan_the_right_split_is_left_byte_for_byte():
    right = ("It is one reading declared on thirty-four other markets " + EM + " twenty-eight in the opposite "
             "direction, six in the same direction.")
    out, log = _apply(right, FAN_RAPE)
    assert out == right and not log.get("corrected")


def test_fan_the_right_split_in_either_order_is_left_byte_for_byte():
    right = ("It is one reading declared on thirty-four other markets: six in the same direction, twenty-eight "
             "opposite.")                                             # author-written: arms reversed, both right
    out, log = _apply(right, FAN_RAPE)
    assert out == right and not log.get("corrected") and not log.get("fan_ambiguous")


def test_fan_V1g_digit_counts_bind_like_their_word_form():
    out, log = _apply("It is declared on 34 other markets " + EM + " 28 in the same direction, 6 opposite.",
                      FAN_RAPE)
    assert out == ("It is declared on 34 other markets " + EM + " 28 in the opposite direction, 6 in the same "
                   "direction.")
    assert log["corrected"] == 2


def test_fan_V1f_a_per_market_sign_with_no_count_is_never_touched():
    out, log = _apply(PER_MARKET, FAN_RAPE)
    assert out == PER_MARKET and not log.get("corrected") and not log.get("fan_ambiguous")


def test_fan_needs_the_fans_total_in_the_sentence():
    s = "Twenty-eight in the same direction, six opposite."          # author-written: no total -> no fan named
    out, log = _apply(s, FAN_RAPE)
    assert out == s and not log.get("corrected")


def test_fan_V1e_two_fans_of_one_total_that_both_match_are_ambiguous_and_left_as_written():
    # rice's El_Nino and La_Nina off ONE ONI series: equal totals, the same counts, OPPOSITE words
    other = _fan(34, 28, SAME, 6, OPP, fid="La_Nina|oni_climate|_global|")
    out, log = _apply(FAN_F1, FAN_RAPE + other)
    assert out == FAN_F1 and log.get("fan_ambiguous") == 1 and not log.get("corrected")


def test_fan_a_phrase_running_past_its_clause_is_left_as_written_never_half_corrected():
    fan = _fan(23, 22, SAME, 1, OPP, fid="crude_oil|brent_crude_z|_global|")
    out, log = _apply(RUN_ON_0923, fan)
    assert out == RUN_ON_0923 and log.get("fan_ambiguous") == 1 and not log.get("corrected")


def test_fan_semicolon_joined_arms_are_one_readers_sentence_so_both_arms_move_together():
    s = "It is declared on thirty-four other markets: twenty-eight in the same direction; six opposite."
    out, log = _apply(s, FAN_RAPE)                                   # author-written: the ';' join
    assert out == ("It is declared on thirty-four other markets: twenty-eight in the opposite direction; six in "
                   "the same direction.")
    assert log["corrected"] == 2


def test_fan_a_count_inside_another_number_word_is_not_the_count():
    s = "It is declared on thirty-four other markets; twenty-eightfold is not a count."
    out, log = _apply(s, FAN_RAPE)
    assert out == s and not log.get("corrected")


# ═════════════════════════════════════════ V-1 RUN ═══════════════════════════════════════════════════════════
def test_run_F2_the_word_on_the_handle_is_corrected_to_the_rows_own_book_word():
    out, log = _apply(TLDR_F2, [_run()])
    assert out.endswith("whereas rapeseed's loosening sits on a European balance sheet that is itself "
                        "tightening [N62].")
    assert log["corrected"] == 1
    assert log["audit"] == [{"field": "mechanism", "before": "loosening", "after": "tightening", "handle": 62,
                             "rule": "run"}]


def test_run_V1a_the_other_rows_word_in_the_same_segment_is_not_the_handles():
    out, _log = _apply(TLDR_F2, [_run()])
    assert "rapeseed's loosening sits on" in out                   # the FIRST 'loosening' is rapeseed's, kept


def test_run_same_vocabulary_a_run_word_is_corrected_by_the_run_word():
    s = "The European balance sheet is rising [N62]."               # author-written
    out, log = _apply(s, [_run()])
    assert out == "The European balance sheet is falling [N62]." and log["corrected"] == 1


def test_run_an_agreeing_word_is_left_byte_for_byte():
    s = "The European balance sheet is tightening [N62]."           # author-written
    out, log = _apply(s, [_run()])
    assert out == s and not log.get("corrected")


def test_run_V1b_an_expectation_away_from_the_handle_is_never_checked():
    out, log = _apply(CHAIN_EXPECT, [_run(direction="up")])
    assert out == CHAIN_EXPECT and not log.get("corrected")


def test_run_V1c_a_word_carrying_its_own_period_anchor_is_left_as_written_and_counted():
    s = "The European balance sheet is loosening [N62] since 2025."   # author-written: its own since-date
    out, log = _apply(s, [_run()])
    assert out == s and log.get("unanchored") == 1 and not log.get("corrected")


def test_run_V1d_a_state_label_is_not_a_direction_word():
    s = "The European balance sheet is loose [N62]."                 # author-written: a label, not a run word
    out, log = _apply(s, [_run()])
    assert out == s and not log.get("corrected")


def test_run_a_group_citing_two_rows_binds_no_direction_word():
    s = "Both balances are loosening [N14][N62]."                    # author-written: two row identities
    out, log = _apply(s, [_run()])
    assert out == s and not log.get("corrected")


def test_run_V1a_a_segment_citing_two_row_identities_binds_no_direction_word():
    s = "Palm dryness sits at 1.25 z [N14] and the balance sheet is loosening [N62]."   # author-written
    out, log = _apply(s, [_run()])
    assert out == s and not log.get("corrected")
    s2 = "Palm dryness sits at 1.25 z [N14], and the balance sheet is loosening [N62]."  # its own segment
    out2, log2 = _apply(s2, [_run()])
    assert out2.endswith("the balance sheet is tightening [N62].") and log2["corrected"] == 1


def test_run_a_call_without_a_row_identity_binds_nothing():
    calls = _calls()
    calls[61] = {k: v for k, v in calls[61].items() if k != "_row_id"}
    out, log = _apply(TLDR_F2, [_run()], calls=calls)
    assert out == TLDR_F2 and not log.get("corrected")


def test_run_the_vocabulary_is_the_rows_own_never_a_list():
    # a row whose declared book differs: the same prose word is not this row's vocabulary -> nothing to check
    out, log = _apply(TLDR_F2, [_run(vocab={"up": ("rising",), "down": ("falling",)})])
    assert out == TLDR_F2 and not log.get("corrected")
    # a word naming both directions names neither
    assert V._dir_vocab({"up": ["rising"], "down": ["rising"]}) == {}


# ═════════════════════════════════════════ V-1 THE SEAM ══════════════════════════════════════════════════════
def _st(tldr, mech=""):
    return {"tldr": tldr, "mechanism": mech, "sources": []}


def test_verify_citations_corrects_in_place_and_reports_only_its_own_keys():
    st = _st(TLDR_F2, FAN_F1 + " " + PER_MARKET)
    rep = V.verify_citations(st, [], _calls(), served_scalars=[_run()] + FAN_RAPE)
    assert "itself tightening [N62]" in st["tldr"]
    assert "twenty-eight in the opposite direction, six in the same direction." in st["mechanism"]
    assert rep["direction_corrected"] == 3 and len(rep["direction_audit"]) == 3
    assert {a["field"] for a in rep["direction_audit"]} == {"tldr", "mechanism"}
    assert "direction" not in " ".join(rep["by_rule"])            # never a charge
    assert "fan_ambiguous" not in rep and "direction_unanchored" not in rep


def test_the_correction_rides_the_apply_pass_so_the_strip_seam_reads_the_text_the_field_returns():
    # author-written: a whole-sentence number_mismatch kill right before the corrected sentence
    st = _st("", "Stocks stood at 55.5 MMT [N62]. The balance sheet is loosening [N62].")
    rep = V.verify_citations(st, [], _calls(), served_scalars=[_run()])
    assert st["mechanism"] == "The balance sheet is tightening [N62]."
    assert rep["by_rule"] == {"number_mismatch": 1} and rep["direction_corrected"] == 1
    assert rep.strip_seams and rep.strip_seams[0]["key"].startswith("the balance sheet is tightening")


def test_a_sentence_the_verifier_deletes_takes_its_correction_with_it_uncounted():
    s = "Stocks sit at 55.5 MMT and loosening [N62]. Nothing else."                   # author-written
    assert V._direction_edits(s.split(". ")[0] + ".", V._VCtx(_calls(), [_run()])) != []  # a live candidate...
    st = _st("", s)
    rep = V.verify_citations(st, [], _calls(), served_scalars=[_run()])
    assert rep["by_rule"] == {"number_mismatch": 1}                                   # ...in a killed sentence
    assert "loosening" not in st["mechanism"] and "tightening" not in st["mechanism"]
    assert "direction_corrected" not in rep and "direction_audit" not in rep


def test_V1h_flag_off_no_pool_is_heads_report_and_prose():
    st0, st1 = _st(TLDR_F2, FAN_F1), _st(TLDR_F2, FAN_F1)
    r0 = V.verify_citations(st0, [], _calls())
    r1 = V.verify_citations(st1, [], _calls(), served_scalars=None)
    assert r0 == r1 and st0 == st1 and st0["tldr"] == TLDR_F2 and st0["mechanism"] == FAN_F1
    assert not any(k.startswith("direction") or k == "fan_ambiguous" for k in r0)


def test_a_pool_with_no_direction_facts_moves_nothing():
    # HEAD's scalar shape (no words / direction / fan_id): the direction arm stays inert
    heads = [{"value": 1, "unit": "marketing year", "kind": "run_length", "row_id": RID_EU, "text": "one"}]
    st0, st1 = _st(TLDR_F2, FAN_F1), _st(TLDR_F2, FAN_F1)
    r0 = V.verify_citations(st0, [], _calls(), served_scalars=heads)
    r1 = V.verify_citations(st1, [], _calls(), served_scalars=[])
    assert st0["tldr"] == TLDR_F2 and st0["mechanism"] == FAN_F1 and st1 == st0
    assert not any(k.startswith("direction") or k == "fan_ambiguous" for k in r0)
    assert V._direction_pool(heads) == ({}, ())


# ═════════════════════════════════════════ V-2 THE DECLARED DATE ═════════════════════════════════════════════
E7 = {"source": "usda_gain_soybeans", "date": "2025-03-19",
      "source_key": "text/source=usda_gain_soybeans/country=CN/publication_date=20250319/document=cn2025-0055",
      "text": "Beijing has placed retaliatory tariffs on U.S. soybeans.", "event_date": "2025-02",
      "event_date_precision": "month"}
E1 = {"source": "usda_gain_soybean_meal", "date": "2019-03-28", "source_key": "k/e1",
      "text": "After China imposed 25 percent tariffs on U.S. soybeans in spring 2018, soybean prices dropped "
              "significantly.", "event_date": "2018-03", "event_date_precision": "month"}
E23 = {"source": "usda_gain_rapeseed", "date": "2022-03-17", "source_key": "k/e23",
       "text": "China implemented a tariff exclusion process on March 2, 2020, for Section 301 retaliatory tariffs "
               "on U.S. soybeans, returning duties from 30.5 percent to 3 percent."}
E24 = {"source": "usda_gain_soybean_meal", "date": "2022-03-17", "source_key": "k/e24",
       "text": "China implemented a tariff exclusion process on March 2, 2020, for Section 301 retaliatory tariffs "
               "on U.S. soybeans, reducing effective duties."}
E4 = {"source": "wb_cmo_outlook", "date": "2018-10-01", "source_key": "k/e4",
      "text": "China imposed tariffs of 25 percent on imports of U.S. soybeans in 2018."}
E7_SENT = ("The newest dated policy action retrieved is February 2025, reported 19 March 2025 " + EM + " 10 to 15 "
           "percent more tariffs on US farm goods, 10 percent on soybeans [E7]; the model treats a policy as in "
           "force until a later dated action.")


def _menu():
    m = [{"source": "x%d" % i, "date": "2001-01-%02d" % i, "source_key": "k/%d" % i, "text": "filler row %d" % i}
         for i in range(1, 25)]
    m[0], m[3], m[6], m[22], m[23] = E1, E4, E7, E23, E24
    return m


def test_declared_dates_reads_every_date_the_menu_phrase_carries():
    assert V._declared_dates({"date": "reported 2025-03-19; event 2025-02"}) == ("2025-03-19", "2025-02")
    assert V._declared_dates({"date": "reported 2018-10; event 2018"}) == ("2018-10",)
    assert V._declared_dates({"date": "2018-07-12"}) == ("2018-07-12",)
    assert V._declared_dates({"date": "19 March 2025"}) == ("2025-03-19",)
    assert V._declared_dates({"date": "MY2017/18"}) == () and V._declared_dates({}) == ()


def test_V2_the_tariff_regime_receipt_is_named_by_its_own_date_and_survives():
    menu = _menu()
    st = {"tldr": "", "mechanism": E7_SENT,
          "sources": [{"ref": 7, "source": "USDA attache GAIN, soybeans", "date": "reported 2025-03-19; event 2025-02"}]}
    iss = {k: [e] for k, e in enumerate(menu, 1)}
    rep = V.verify_citations(st, menu, [], evidence_chunks=iss)
    assert "[E7]" in st["mechanism"], rep.get("by_rule")
    assert "unsupported_at_address" not in rep["by_rule"]
    assert rep["ledger_address_identity"] == ["7"]                  # relabelled, never disputed
    assert rep["resolved"]["7"]["source_key"] == E7["source_key"]
    # the kept row carries the document date the phrase named (HEAD's relabel left it so), never the phrase
    assert [(x["ref"], x["date"]) for x in st["sources"]] == [(7, "2025-03-19")]


def test_V2_a_phrase_that_names_the_address_is_not_counted_as_a_date_mismatch():
    menu = _menu()
    st = {"tldr": "", "mechanism": ("On 6th July 2018 China imposed tariffs on U.S. soybeans, reported "
                                    "19 March 2025 [E7]."),
          "sources": [{"ref": 7, "source": "usda_gain_soybeans", "date": "reported 2025-03-19; event 2025-02"}]}
    rep = V.verify_citations(st, menu, [], evidence_chunks={k: [e] for k, e in enumerate(menu, 1)})
    assert "7" not in (rep.get("ledger_declared_mismatch") or {}) and rep["corrected"] == 0
    assert st["sources"][0]["date"] == "2025-03-19" and "[E7]" in st["mechanism"]


def test_V2_HEAD_parity_a_plain_iso_declaration_decides_exactly_as_before():
    menu = _menu()
    for decl in ({"source": "usda_gain_soybeans", "date": "2025-03-19"},
                 {"source": "USDA attache GAIN, soybeans", "date": "2025-03-19"},
                 {"source": "USDA attache GAIN, soybeans", "date": "2024-01-01"}):
        head = (str(decl["date"])[:10] == E7["date"])
        assert (E7["date"] in V._declared_dates(decl)) == head


def test_V2b_an_event_date_equal_to_ANOTHER_documents_date_names_nothing():
    menu = _menu()
    # a declaration at E1's address whose EVENT date is E7's document date and whose report date is not E1's
    decl = {"source": "USDA attache GAIN, soybean meal", "date": "reported 2019-01-01; event 2025-03-19"}
    assert V._declared_names_address(decl, E1, menu) is False       # only the address's OWN date names it
    assert V._date_named_documents(decl, E1, menu) == set()         # and the slip reader is HEAD's, unchanged


def test_V2_twins_of_one_date_keep_their_dispute_and_support_still_decides():
    menu = _menu()
    decl = {"source": "USDA attache GAIN, rapeseed", "date": "reported 2022-03-17; event 2020-03-02"}
    assert V._declared_names_address(decl, E23, menu) is False      # E24 carries the same date: no identity
    # ...and on the disputed path an unsupported sentence is still struck (V2-c: no exemption in disguise)
    st = {"tldr": "", "mechanism": "Chicago rallied on unrelated weather news [E23].", "sources": [dict(decl, ref=23)]}
    rep = V.verify_citations(st, menu, [], evidence_chunks={k: [e] for k, e in enumerate(menu, 1)})
    assert rep["by_rule"].get("unsupported_at_address") == 1 and "[E23]" not in st["mechanism"]


def test_V2_a_month_declaration_names_its_address_only_when_no_other_document_shares_the_month():
    menu = _menu()
    decl = {"source": "World Bank Commodity Markets Outlook", "date": "reported 2018-10; event 2018"}
    assert V._declared_names_address(decl, E4, menu) is True
    rival = dict(menu[5], date="2018-10-15", source_key="k/rival")
    assert V._declared_names_address(decl, E4, menu[:5] + [rival] + menu[6:]) is False


def test_V2_flag_off_no_ledger_is_heads_path():
    menu = _menu()
    st0 = {"tldr": "", "mechanism": E7_SENT,
           "sources": [{"ref": 7, "source": "USDA attache GAIN, soybeans", "date": "reported 2025-03-19; event 2025-02"}]}
    st1 = copy.deepcopy(st0)
    r0 = V.verify_citations(st0, menu, [])
    r1 = V.verify_citations(st1, menu, [], evidence_chunks=None)
    assert r0 == r1 and st0 == st1
    assert "ledger_address_identity" not in r0 and "ledger_declared_mismatch" not in r0
