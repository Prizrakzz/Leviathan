"""09-25 FIX ROUND 3, LANE VC -- the verifier / citations / ledger half of the 09-25 re-smoke's fix list.

Every prose fixture below is VERBATIM from the 09-25 raw drafts (resmoke_0925/answers/*.trace.json
`raw_draft.preverify_*`), every served value is that turn's served row, and every calculator row is RE-MINTED by
the REAL producers (`numbers.stats.window_change` over the served level values, `numbers.agent._stat_calls(...,
board=True)` -- lane T's K5 row) -- never typed. The [E] evidence menu is not persisted in any trace, so the
ledger pins rebuild the documents the 09-23 / 09-24 / 09-25 traces DID resolve (`citation_resolved`, verbatim
snippets) at the indices they were printed under.

  VC-1  every figure a served STAT row's label prints (the calculator's percent beside the change) is a typed
        member of that row on a STAMPED call: the palm/rape answer is served with its receipts (0 charges)
  VC-2  the menu issues its ordinals (the ledger reads the turn's one menu decision); a declaration at an issued
        address is NAMED by the address's own date -- a paraphrased publisher disputes nothing, a shared date
        or another publisher still does
  VC-3  a sentence ABOUT a receipt's date is bound by the receipt's dated identity at its own precision
  VC-4  one document, one address: a second declaration of a document its own address already declares
        leaves the index standing, and a ref that resolves to a document held at another issued address folds
        onto it
"""
from __future__ import annotations

import copy

from leviathan.graphrag import citations as cit
from leviathan.graphrag import verify as vf


# -- VC-1 -------------------------------------------------------------------------------------------------
_CHINA_PALM = [709200.0, 799400.0, 826100.0, 696000.0, 762500.0, 724100.0]       # 09-25 palm/rape N1
_CHINA_RAPE = [242000.0, 271000.0, 302000.0, 355000.0, 363000.0, 412000.0]       # N2
_INDIA_PALM = [486000.0, 534000.0, 413000.0, 466000.0, 364000.0, 316000.0]       # N3
_PAK_PALM = [514950.0, 544500.0, 496900.0, 446000.0, 344750.0, 288800.0]         # N5
_BGD_PALM = [115950.0, 111150.0, 99460.0, 71950.0, 72250.0, 33780.0]             # N7
_US_PALM = [159000.0, 159000.0, 159000.0, 159000.0, 136000.0, 136000.0]          # N9
_US_RAPE = [57000.0, 57000.0, 57000.0, 57000.0, 67000.0, 66000.0]                # N10


def _level(vals, country):
    return {"query": {"table": "silver_mpoc_stock_comparison", "metric": "ending_stocks_mt", "country": country},
            "rows": [{"value": str(v), "unit": None, "country": country} for v in vals], "status": "ok"}


def _change(vals, country):
    """The seat's window_change row, minted by the REAL calculator and lane T's REAL board row producer."""
    from leviathan.graphrag.numbers import agent as AG
    from leviathan.graphrag.numbers import stats as S
    res = S.window_change(vals, 0, -1)
    c = AG._stat_calls("window_change", res, {"stat": "window_change"}, "MT", None, board=True)[0]
    c["rows"][0]["country"] = country
    return c


def _palm_calls(*, stamp: bool) -> list:
    calls = [_level(_CHINA_PALM, "china"), _level(_CHINA_RAPE, "china"), _level(_INDIA_PALM, "india"),
             _level([3000.0], "india"), _level(_PAK_PALM, "pakistan"), _level([500.0], "pakistan"),
             _level(_BGD_PALM, "bangladesh"), {"query": {"table": "silver_mpoc_stock_comparison"}, "rows": [],
                                               "status": "no_rows"},
             _level(_US_PALM, "usa"), _level(_US_RAPE, "usa"),
             _change(_CHINA_PALM, "china"), _change(_CHINA_RAPE, "china"), _change(_INDIA_PALM, "india"),
             _change(_PAK_PALM, "pakistan"), _change(_BGD_PALM, "bangladesh"), _change(_US_PALM, "usa"),
             _change(_US_RAPE, "usa")]
    return [dict(c, display="analyst") for c in calls] if stamp else calls


_PALM_TLDR = ("On stocks movement the answer is lopsided by destination: Chinese rapeseed oil inventories rose "
              "+170,000 MT (+70.25%) from January 2026 to June 2026 [N12] against a barely-changed Chinese palm "
              "holding of +14,900 MT (+2.1%) [N11] -- rapeseed oil's position moved far more.")
_PALM_MECH = ("Chinese stocks, January 2026 to June 2026: rapeseed oil +170,000 MT (+70.25%) [N12] to 412,000 MT "
              "[N2]; palm +14,900 MT (+2.1%) [N11] to 724,100 MT [N1]. Elsewhere the direction reverses: Indian "
              "stocks -170,000 MT (-34.98%) [N13], Pakistan -226,150 MT (-43.92%) [N14], Bangladesh -82,170 MT "
              "(-70.87%) [N15]; In the US, palm fell -23,000 MT (-14.47%) [N16] while rapeseed oil rose +9,000 MT "
              "(+15.79%) [N17] -- the same split. China built rapeseed oil aggressively, +170,000 MT (+70.25%) "
              "[N12], while India, Pakistan and Bangladesh drew palm down hard [N13][N14][N15].")


def test_vc1_the_calculators_percent_is_the_rows_own_member_and_the_answer_keeps_its_receipts():
    calls = _palm_calls(stamp=True)
    assert calls[11]["rows"][0]["pct_change"] == calls[11]["shown"][1]            # lane T's own member
    st = {"tldr": _PALM_TLDR, "mechanism": _PALM_MECH, "sources": []}
    rep = vf.verify_citations(st, [], calls)
    assert rep["by_rule"] == {}, rep["by_rule"]
    assert st["tldr"] == _PALM_TLDR and st["mechanism"] == _PALM_MECH           # every handle served


def test_vc1_the_member_rides_the_stamp_only_board_off_is_heads_reading():
    """No stamp (a board-off turn) -> the member arm is inert: HEAD's reading convicts exactly as 09-25 did."""
    st = {"tldr": _PALM_TLDR, "mechanism": "", "sources": []}
    rep = vf.verify_citations(st, [], _palm_calls(stamp=False))
    assert rep["by_rule"].get("number_unbacked", 0) >= 1
    assert "[N12]" not in st["tldr"]


def test_vc1_the_member_is_typed_by_the_unit_the_label_prints():
    """The percent backs a figure written as a PERCENT, never the same digits in another unit."""
    calls = _palm_calls(stamp=True)
    ok = "Chinese rapeseed oil stocks rose +170,000 MT (+70.25%) [N12]."
    bad = "Chinese rapeseed oil stocks rose +170,000 MT to 70.25 MT [N12]."
    assert vf._check_number_handle(ok, 12, calls) is None
    assert vf._check_number_handle(bad, 12, calls) == "number_unbacked"


def test_vc1_one_producer_for_the_label_and_the_verifier():
    row = {"value": 170000.0, "pct_change": 70.24793388429752}
    assert cit.row_side_figures(row) == ((70.24793388429752, cit.PCT_MEMBER_UNIT),)
    assert cit._pct_words(row) == " (+70.25 %)"
    assert cit.row_side_figures({"value": 1.0}) == () and cit._pct_words({"value": 1.0}) == ""
    assert vf._side_members(dict(_palm_calls(stamp=False)[11])) == ()           # unstamped: no member


_COCOA_N1 = {"query": {"table": "silver_icco_cocoa", "metric": "su_ratio", "country": None}, "status": "ok",
             "rows": [{"period": "2023/24", "value": "0.2635948526359485", "unit": None},
                      {"period": "2024/25", "value": "0.28522039757994816", "unit": None}]}   # 09-25 cocoa N1
_COCOA_S1 = ("The two readings of the same season's cushion differ by trust tier: the ICCO's published 2024/25 "
             "stocks-to-grindings is 29.2% [E7], while the series read here gives 28.52% [N1].")


def test_vc1_a_figure_addressed_to_an_evidence_handle_is_that_documents_never_a_neighbours_charge():
    """09-25 cocoa strike S1 (fact grade F-N3): 29.2% is written INTO [E7] (the figure [handle] convention), so
    it is the document's figure; [N1] keeps its own 28.52%. Board-off (no stamp): HEAD's backstop, unchanged."""
    assert vf._check_number_handle(_COCOA_S1, 1, [dict(_COCOA_N1, display="analyst")]) is None
    assert vf._check_number_handle(_COCOA_S1, 1, [dict(_COCOA_N1)]) == "number_unbacked"
    loose = "The ICCO's 2024/25 figure is 29.2% and the series read here gives 28.52% [N1] [E7]."
    assert vf._check_number_handle(loose, 1, [dict(_COCOA_N1, display="analyst")]) == "number_unbacked"


# -- VC-2 -------------------------------------------------------------------------------------------------
def _doc(source, date, text, key, **kw):
    return dict({"source": source, "date": date, "text": text, "source_key": key}, **kw)


def _filler(n):
    return [_doc("placeholder_%d" % k, "1900-01-%02d" % (k % 28 + 1), "zzfiller%d" % k, "ph/%d" % k)
            for k in range(1, n + 1)]


def test_vc2_the_ledger_issues_the_menus_ordinals_when_the_menu_printed_them():
    menu = [_doc("a", "2020-01-01", "t1", "k1"), _doc("b", "2021-01-01", "t2", "k2"), {"source": "c", "text": "x"}]
    led = cit.EvidenceLedger(menu, menu_printed=True)
    assert sorted(led.issued()) == [1, 2]                     # a keyless row has no address to issue
    assert cit.EvidenceLedger(menu, menu_printed=False).issued() == {}
    from leviathan.graphrag import answer as an                # the ONE producer of the menu decision
    # RE-BANKED 09-25 (close-out lane AT, AT-3 / VERIFY MINOR-6): the decision is HANDED to the ledger by the
    # serving body's builder, never read back off the process's imports -- a ledger nobody told printed no menu
    assert cit.EvidenceLedger(menu).menu_printed is False
    assert an._evidence_ledger(menu).menu_printed is True
    with an.handle_menu_override(False):
        assert an._evidence_ledger(menu).issued() == {}
    k = cit.EvidenceLedger(menu, menu_printed=True).address(_doc("d", "2022-01-01", "t4", "k4"))
    assert k == 4


def _rice_menu():
    """The 09-25 rice menu positions the traces resolved (09-24 citation_resolved E33 / E38 / E39, 09-23 E43,
    09-25 E37 / E41 -- each at the index the 09-25 writer cited it under, with the date the 09-25 writer declared
    for it; snippets VERBATIM, the ellipsis of a truncated snippet dropped), every other position a filler."""
    ev = _filler(47)
    ev[32] = _doc("usda_gain_wheat", "2025-04-02", "The Indian government is likely to increase the offtake of rice "
                  "for food security programs and open market sales due to government-held rice",
                  "text/source=usda_gain_wheat/grain_and_feed_annual_new_delhi_india_in2025-0023/document.json")
    ev[36] = _doc("usda_wasde", "2025-12-09", "2025/26 global rice beginning stocks are increased primarily for "
                  "India, based on higher-than-expected beginning stocks reported by the Food",
                  "text/source=usda_wasde/release_date=2025-12-09/document.json")
    ev[37] = _doc("usda_gain_rice", "2025-04-15", "Rice export restrictions in India reduced competition for "
                  "Vietnam rice exports.", "text/source=usda_gain_rice/vietnam_vm2025-0015/document.json")
    ev[38] = _doc("usda_gain_grain_monthly", "2024-11-04", "On September 28, 2024, India's Ministry of Commerce and "
                  "Industry removed exports of non-Basmati white rice from the prohibited list to the f",
                  "text/source=usda_gain_grain_monthly/new_delhi_india_in2024-0055/document.json")
    ev[40] = _doc("usda_wasde", "2023-09-12", "The Government of India has imposed further restrictions on rice "
                  "exports with an export tax on parboiled rice and a minimum export price for",
                  "text/source=usda_wasde/release_date=2023-09-12/document.json")
    ev[42] = _doc("usda_gain_rice", "2026-03-31", "Conflict-related disruptions through the Red Sea and in the "
                  "Middle East raise freight and insurance costs for Thailand rice and increase qua",
                  "text/source=usda_gain_rice/bangkok_thailand_th2026-0006/document.json")
    return ev


_RICE_SOURCES = [{"ref": 37, "source": "USDA WASDE (official world/US balance sheet)", "date": "2025-12-09"},
                 {"ref": 41, "source": "USDA WASDE (official world/US balance sheet)", "date": "2023-09-12"},
                 {"ref": 33, "source": "USDA GAIN attache report (wheat)", "date": "2025-04-02"},
                 {"ref": 39, "source": "USDA GAIN attache report (grain monthly)",
                  "date": "2024-11-04 (event 2024-09-28)"},
                 {"ref": 38, "source": "USDA GAIN attache report (rice)", "date": "2025-04-15"},
                 {"ref": 43, "source": "USDA GAIN attache report (rice)", "date": "2026-03-31"}]
_RICE_MECH = ("India's 2025 record shows stocks ballooning beyond buffer norms with open-market sales likely "
              "[E33], and the world sheet was revised up on higher Indian beginning stocks [E37]. Dated support, "
              "dated honestly: Indian export restrictions reduced competition for Vietnamese exports as of 15 "
              "April 2025 [E38]; India moved non-basmati white rice off the prohibited list on 28 September 2024 "
              "subject to a $490/MT minimum export price [E39]; the 2023 restrictions stacked a parboiled export "
              "tax on a basmati minimum price [E41]. Freight is the newest document behind this answer: Red Sea "
              "and Middle East disruption raising freight and insurance on Thai rice, reported 31 March 2026 "
              "[E43]. While it climbs, open-market releases stay the more likely policy and world offers stay "
              "capped [E33].")


def test_vc2_a_paraphrased_publisher_at_the_menus_own_address_and_date_names_that_document():
    ev = _rice_menu()
    rep_h, st_h = _run_e(_RICE_MECH, _RICE_SOURCES, ev, None)                    # HEAD: no ledger issued
    assert rep_h["by_rule"] == {"fabricated_citation": 4, "ledger_cascade": 5}
    rep, st = _run_e(_RICE_MECH, _RICE_SOURCES, ev, cit.EvidenceLedger(copy.deepcopy(ev), menu_printed=True))
    assert rep["by_rule"] == {}, rep["by_rule"]
    assert sorted(rep["resolved"], key=int) == ["33", "37", "38", "39", "41", "43"]
    assert rep["resolved"]["38"]["source_key"].endswith("vietnam_vm2025-0015/document.json")
    assert rep["ledger_address_identity"] == ["33", "38", "39", "43"]
    assert st["mechanism"] == _RICE_MECH
    assert {x["ref"]: x["source"] for x in st["sources"]}[38] == "usda_gain_rice"   # the label relabelled


def _run_e(mech, sources, ev, led, tldr=""):
    kw = {}
    if led is not None:
        ev = led.evidence()
        kw = {"evidence_chunks": led.issued()} if led.issued() else {}
    st = {"tldr": tldr, "mechanism": mech, "sources": copy.deepcopy(sources)}
    return vf.verify_citations(st, ev, [], **kw), st


def test_vc2_a_shared_date_or_another_publisher_keeps_the_dispute():
    """The source may only DISAMBIGUATE: with a second document of the same date the paraphrase cannot choose,
    and a declaration naming another publisher the turn holds names that publisher -- both keep round 2's
    dispute, so the address must carry the sentence on its own chunks."""
    ev = _rice_menu()
    ev[10] = _doc("usda_gain_grain_monthly", "2025-04-15", "Thai rice planting slowed on dry weather.",
                  "gain_grain_monthly/TH/x")                     # ANOTHER document of the same date
    rep, st = _run_e(_RICE_MECH, _RICE_SOURCES, ev, cit.EvidenceLedger(copy.deepcopy(ev), menu_printed=True))
    assert "38" not in (rep.get("ledger_address_identity") or [])
    assert "38" in rep["ledger_declared_mismatch"]
    assert "[E38]" in st["mechanism"]                          # the address carries its sentence on its own
    wrong = [{"ref": 38, "source": "USDA WASDE", "date": "2025-04-15"}]
    assert not vf._declared_names_address(wrong[0], ev[37], _rice_menu())
    assert vf._declared_names_address({"source": "USDA GAIN attache report (rice)", "date": "2025-04-15"},
                                      _rice_menu()[37], _rice_menu())


# -- VC-3 -------------------------------------------------------------------------------------------------
def _palm_menu():
    ev = _filler(11)
    ev[1] = _doc("mpoc", "2023-03-13", "Rapeseed oil and soybean oil will fill the sunflower oil gap in China, "
                 "giving more room for palm oil demand", "mpoc/2023-03-13")
    ev[9] = _doc("usda_gain_palm_oil", "2010-03-12", "When crude palm oil prices reached above RM3,500/MT in "
                 "mid-2008, palm oil biodiesel lost some of its luster.", "gain_palm_oil/MY/20100312",
                 event_date="2008-06-01", event_date_precision="month")
    ev[10] = _doc("mpoc", "2022-03-15", "If palm oil prices remain high, rapeseed oil used as biodiesel feedstock "
                  "would be strengthened", "mpoc/2022-03-15", event_date="2022-04-01", event_date_precision="day")
    return ev


_E10 = [{"ref": 10, "source": "usda_gain_palm_oil, USDA attache report", "date": "2010-03-12 (event 2008-06-01)"}]
_AGE = "Its only dated document is an action in June 2008 [E10], far older than the lag the model allows."


def test_vc3_a_sentence_about_the_receipts_age_is_bound_by_its_dated_identity():
    ev = _palm_menu()
    led = cit.EvidenceLedger(copy.deepcopy(ev), menu_printed=True)
    led.address(dict(ev[9]))                                   # the block printed the chain's aged receipt
    rep, st = _run_e(_AGE, _E10, ev, led)
    assert rep["by_rule"] == {} and st["mechanism"] == _AGE
    assert rep["resolved"]["10"]["source_key"] == "gain_palm_oil/MY/20100312"
    assert rep["receipt_identity_bound"] == 1
    # the round-2 issued set (only the block's receipt, no menu) reaches the same verdict: VC-3 lives in the
    # verifier's support test, not in the ledger's widening (HEAD's verdict on this shape: no_lexical_overlap,
    # the 09-25 strike -- pinned failing on HEAD by the lane's refute run)
    led_b = cit.EvidenceLedger(copy.deepcopy(ev), menu_printed=False)
    led_b.address(dict(ev[9]))
    rep_b, _ = _run_e(_AGE, _E10, ev, led_b)
    assert rep_b["by_rule"] == {}


def test_vc3_a_month_the_receipt_does_not_carry_or_a_rival_carries_binds_nothing():
    ev = _palm_menu()
    led = cit.EvidenceLedger(copy.deepcopy(ev), menu_printed=True)
    rep, st = _run_e(_AGE.replace("June 2008", "June 2009"), _E10, ev, led)
    assert rep["by_rule"] == {"no_lexical_overlap": 1} and "[E10]" not in st["mechanism"]
    ev2 = _palm_menu()
    ev2[4] = _doc("usda_gain_rapeseed", "2008-06-20", "zzfiller", "gain_rapeseed/x")   # a rival of that month
    rep2, _ = _run_e(_AGE, _E10, ev2, cit.EvidenceLedger(copy.deepcopy(ev2), menu_printed=True))
    assert rep2["by_rule"] == {"no_lexical_overlap": 1}
    # a sentence that makes its OWN claim under the receipt's date is not restating the receipt (THREAT_MODEL C-1)
    claim = "Its only dated document is an action in June 2008 that cut output 40 percent [E10]."
    rep3, _ = _run_e(claim, _E10, ev, cit.EvidenceLedger(copy.deepcopy(ev), menu_printed=True))
    assert rep3["by_rule"] == {"no_lexical_overlap": 1}


def test_vc3_a_month_date_is_read_only_where_no_full_date_holds_it():
    assert [ym for _a, _b, ym in vf._month_dates("an action in June 2008 and a report of 19 March 2025")] \
        == [(2008, 6)]
    assert [ym for _a, _b, ym in vf._month_dates("the 2008-06 reading, not 2008-06-01")] == [(2008, 6)]


# -- VC-4 -------------------------------------------------------------------------------------------------
def _corn_wheat_menu():
    """09-25 corn/wheat: E1 = the 2021-10-14 Kyiv GAIN report (09-23 and 09-24 resolved it at [E1], snippet
    verbatim); E10 = the 2024-04-11 WASDE (09-23 [E10], 09-25 citation_resolved)."""
    ev = _filler(12)
    ev[0] = _doc("usda_gain_grain_monthly", "2021-10-14", "Because corn became a relatively cheaper feed ingredient "
                 "compared to wheat, the Post increased corn feed consumption at the expense of decre",
                 "gain_grain_monthly/UA/20211014")
    ev[9] = _doc("usda_wasde", "2024-04-11", "2023/24 U.S. wheat ending stocks are higher in this month's outlook.",
                 "wasde/2024-04-11")
    return ev


_CW = ("Historically this is exactly how the record reads it: corn feed use rose at wheat's expense when corn was "
       "the cheaper ingredient in MY2021/22 [E1].")
_CW_SOURCES = [{"ref": 1, "source": "USDA WASDE (official balance sheet, T1)", "date": "2024-04-11"},
               {"ref": 10, "source": "USDA WASDE (official balance sheet, T1)", "date": "2024-04-11"}]


def test_vc4_a_second_label_of_a_document_its_own_address_declares_leaves_the_index_standing():
    """09-25 corn/wheat, verbatim: refs 1 AND 10 declared "USDA WASDE" 2024-04-11; the WASDE sits at address 10
    and ref 10 declares it there, so ref 1's declaration is a second LABEL of a placed document, not an index
    slip -- [E1] stays the 2021-10-14 GAIN report its sentence quotes. HEAD's matcher sent BOTH refs to the WASDE
    (one document at two addresses, the page's [E1] row naming a document that does not make the claim)."""
    ev = _corn_wheat_menu()
    rep_h, _ = _run_e(_CW, _CW_SOURCES, ev, None)
    assert rep_h["resolved"]["1"]["source_key"] == rep_h["resolved"]["10"]["source_key"] == "wasde/2024-04-11"
    rep, st = _run_e(_CW, _CW_SOURCES, ev, cit.EvidenceLedger(copy.deepcopy(ev), menu_printed=True))
    assert rep["by_rule"] == {} and st["mechanism"] == _CW
    assert rep["resolved"]["1"]["source_key"] == "gain_grain_monthly/UA/20211014"
    assert rep["resolved"]["10"]["source_key"] == "wasde/2024-04-11"          # one document, one address
    assert rep["ledger_index_upheld"] == ["1"]


def test_vc4_a_true_index_slip_folds_onto_the_address_the_page_printed():
    """The writer declared the WASDE exactly and typed [E3] (a filler the sentence shares nothing with): the
    declaration names the document and the prose does not uphold the index, so it is the round-2 slip -- and
    the WASDE holds address 10 on this page, so [E3] is corrected to [E10] and one row serves it."""
    ev = _corn_wheat_menu()
    s = "US wheat ending stocks for 2023/24 were raised in the April outlook [E3]."
    src = [{"ref": 3, "source": "usda_wasde", "date": "2024-04-11"}]
    rep, st = _run_e(s, src, ev, cit.EvidenceLedger(copy.deepcopy(ev), menu_printed=True))
    assert rep["folded"] == {"3": 10} and "[E10]" in st["mechanism"] and "[E3]" not in st["mechanism"]
    assert rep["resolved"]["10"]["source_key"] == "wasde/2024-04-11" and "3" not in rep["resolved"]
    assert [x["ref"] for x in st["sources"]] == [10]
    rep_h, st_h = _run_e(s, src, ev, None)                                      # HEAD: two addresses, one doc
    assert rep_h["resolved"]["3"]["source_key"] == "wasde/2024-04-11" and "[E3]" in st_h["mechanism"]


def test_vc2_a_paraphrase_whose_date_names_one_other_document_is_that_documents_index_slip():
    """The publisher in paraphrase (the page's display name + the menu's tier tag -- the 09-25 shape) at a
    NEIGHBOUR's index, with the date of exactly one other document: the date names it, so it resolves to that
    document (never through the source matcher that cannot read the paraphrase) and folds onto its address.
    HEAD: the paraphrase matches nothing -> fabricated_citation, the handle cut."""
    ev = _corn_wheat_menu()
    s = _CW.replace("[E1]", "[E3]")
    src = [{"ref": 3, "source": "USDA FAS GAIN Report - Grain (monthly) [T2]", "date": "2021-10-14"}]
    rep, st = _run_e(s, src, ev, cit.EvidenceLedger(copy.deepcopy(ev), menu_printed=True))
    assert rep["by_rule"] == {} and rep["folded"] == {"3": 1} and st["mechanism"] == _CW
    assert rep["resolved"]["1"]["source_key"] == "gain_grain_monthly/UA/20211014"
    rep_h, st_h = _run_e(s, src, ev, None)
    assert rep_h["by_rule"] == {"fabricated_citation": 1, "ledger_cascade": 1} and "[E3]" not in st_h["mechanism"]
    # a ref resolved AT its own issued address never folds -- even on an issued map (the twin drive's shape)
    # whose list holds that document's key at two addresses
    ev2 = _corn_wheat_menu()
    ev2[4] = dict(ev2[9])                                      # the WASDE key at 5 AND 10, both issued
    src2 = [{"ref": 10, "source": "USDA WASDE", "date": "2024-04-12"}]
    s2 = "US wheat ending stocks for 2023/24 are higher in the April outlook [E10]."
    st2 = {"tldr": "", "mechanism": s2, "sources": copy.deepcopy(src2)}
    rep2 = vf.verify_citations(st2, ev2, [], evidence_chunks={k: [e] for k, e in enumerate(ev2, 1)})
    assert "folded" not in rep2 and "[E10]" in st2["mechanism"] and "10" in rep2["resolved"]


def test_vc4_the_fold_re_writes_only_the_handle():
    assert vf._refold_e_handles("a [E3] b [N3] c [E3, E7] d [E1-E4]", {3: 10}) == \
        ("a [E10] b [N3] c [E10, E7] d [E1-E4]", 2)
