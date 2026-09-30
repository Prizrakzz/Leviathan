"""FIX SITTING 4 (2026-09-29), LANE I -- THE CENSUS ROWS OF THE SITTING'S CLASSES, THE NETTING PARTS' NAMES AND THE
BANKED EPISODE WINDOWS (CONTRACT C4-20 / C4-21; I4-1, I4-2 = sitting 3's BLOCKER-1 and NOTE-1, I4-3).

Every reading pin runs on REAL banked seat output: tests/fixtures/instrument_census_0929/ (five live pages of the
2026-09-29 smoke and probe, each a per-answer record reduced to the census-read keys, verbatim, beside its page AS
SERVED -- README.txt there). The flag-off / banked-draft pins run on sitting 2's committed arm-A fixture
(tests/fixtures/instrument_census_0926/). Two inputs are NOT on any banked record and are labelled at the site: the
verifier's live report (`direction_audit`, which the per-answer record does not bank -- restated from the banked
drafts, where the post-verify draft carries the handle the pre-verify one lacks), and lane R's contracted
`render.THRESHOLD_CLAUSE_NOUN` (C4-6; the word render.py's threshold clause prints) where the tree does not yet
declare it. Nothing here is a phrase the census matches: every row reads a producer field and locates a handle, a
figure or a producer's own words on the page.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from leviathan.graphrag import eval as gev

_FIX = Path(__file__).resolve().parents[1] / "fixtures"
_S4 = ("bare_handle_parenthetical", "absence_append_beside_served", "long_label_in_sentence", "handle_inside_noun",
       "change_row_equals_level", "known_after_asof", "raw_unit_spelling")
_S3_ROSTER_LEN = 25                     # HEAD 6ba0a87b's roster: sitting 2's twenty + sitting 3's Z23 five


def _page(name: str) -> tuple:
    d = json.loads((_FIX / "instrument_census_0929" / f"{name}.json").read_text(encoding="utf-8"))
    return copy.deepcopy(d["record"]), d["page"]


def _served(name: str, **out) -> tuple:
    """(record, live row) -- the live row carries the page AS SERVED as `out['answer']` (plus any `out` key given)."""
    rec, body = _page(name)
    return rec, {"q": {"id": name}, "out": {"answer": body, **out}}


def _read(name: str, row: str, **out) -> dict:
    rec, live = _served(name, **out)
    return gev._instrument_row(rec, live)[row]


# -- 0. THE ROSTER: SEVEN ROWS APPENDED, IN THE CONTRACT'S ORDER ----------------------------------------------------
def test_the_seven_c4_21_rows_are_appended_after_the_sitting_3_roster_in_the_contracts_order():
    names = tuple(n for n, _k, _p in gev._INSTRUMENTS)
    assert names[_S3_ROSTER_LEN:] == _S4
    kinds = {n: k for n, k, _p in gev._INSTRUMENTS}
    assert all(kinds[n] == "count" for n in _S4)
    assert [n for n, _k in gev._S4_LISTS] == list(_S4)


# -- 1. EVERY ROW IS ABSENT, NEVER A ZERO, WHERE ITS FIELD IS NOT ON THE RECORD ------------------------------------
def test_on_a_banked_draft_the_rows_that_need_the_served_page_read_absent_with_the_field_named():
    """THREAT I-a: a per-answer record banks the post-verify DRAFT, and every seam that writes these classes writes
    after it -- so on the arm-A records (no served page) those rows are ABSENT with the missing field named, never a
    0 a report could quote as a pass."""
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((_FIX / "instrument_census_0926").glob("*.json"))]
    per = [r for d in docs for r in d["per_answer"]]
    cen = gev.instrument_census(per)
    for name in ("bare_handle_parenthetical", "absence_append_beside_served", "long_label_in_sentence",
                 "handle_inside_noun", "known_after_asof"):
        c = cen["census"][name]
        assert (c["n"], c["value"], c["quoted"]) == (0, None, False), (name, c)
    assert set(cen["census"]["handle_inside_noun"]["absent"]) == {
        "the verifier's report is not on the record (a banked record carries no direction_audit)"}
    assert set(cen["census"]["known_after_asof"]["absent"]) <= {
        "no as-of on the record (state_board.asof / the deck query's asof)",
        "no served page on the record (the footer is on the served page only)"}
    for k in ("bare_handle_found", "absence_append_found", "long_label_found", "handle_inside_noun_found",
              "known_after_asof_found"):
        assert k not in cen                                           # omitted when empty (the contract's law)


# -- 2. BARE-HANDLE PARENTHETICALS (A4-1) ----------------------------------------------------------------------------
def test_the_seams_bare_handle_date_stamps_are_counted_against_the_rows_the_seam_dated():
    """The palm/rape smoke page carries three date stamps the post-verify seam wrote with the handles bare
    ("(N61, N8 the 2026-08 reading, read 2026-09-13)"): ten bare addresses, and the seam dated ten rows."""
    got = _read("smoke1_quick_palm_rapeoil", "bare_handle_parenthetical")
    assert (got["v"], got["d"]) == (10, 10)
    assert got["x"]["parentheticals"] == 3 and got["x"]["by_stage"] == {"post_verify_seam": 3}
    assert [f["handles"] for f in got["_found"]] == [["N61", "N8"], ["N13", "N15", "N16"],
                                                     ["N40", "N42", "N31", "N37", "N34"]]


def test_a_bare_token_is_an_address_only_where_the_handle_parser_reads_it_and_the_page_prints_it_bracketed():
    """"E10" (a fuel blend) inside a parenthetical is never a handle unless the page's own ledger carries [E10]; a
    bracketed handle is not bare. The corn/wheat page's real stamp is read beside them."""
    rec, live = _served("smoke1_quick_corn_wheat")
    live["out"]["answer"] = live["out"]["answer"].replace(
        "\n## Sources", "\nBlend note (E10 fuel, [N14] aside).\n## Sources", 1)
    got = gev._instrument_row(rec, live)["bare_handle_parenthetical"]
    assert (got["v"], got["d"]) == (2, 3)                             # only "(N14, N16 read 2026-09-11)"
    assert [f["handles"] for f in got["_found"]] == [["N14", "N16"]]


# -- 3. ABSENCE APPENDS BESIDE A SERVED ABSENCE (A4-2) ---------------------------------------------------------------
def test_an_absence_append_beside_a_quorums_unread_member_is_counted_and_listed_with_its_sentence():
    """The max smoke page's claim "with drought and heat stress carrying no series read on this turn" restates the
    quorum line's own unread members ("... so not counted (drought and heat stress)"), and the seam appended [N130]
    beside it."""
    got = _read("smoke1_max_soybeans_2026_09_07", "absence_append_beside_served")
    assert (got["v"], got["d"]) == (1, 1)
    assert got["x"]["located"] == 1 and got["x"]["by_basis"] == {"quorum": 1}
    f = got["_found"][0]
    assert f["beside"] == "drought" and f["append"].startswith("a served reading bears on this: [N130]")


def test_a_shortened_member_name_is_not_read_the_error_stays_under_claim_and_the_append_is_still_listed():
    """The tariff smoke page's "No series is served at the tariff link" restates the rendered chain's unmeasured
    hop, whose printed name is "China import tariff": the claim does not carry it whole, so the row does not count
    it -- an UNDER-claim, stated -- and lists the append with its sentence for a human to read."""
    got = _read("smoke2_deep_tariff_soybeans", "absence_append_beside_served")
    assert (got["v"], got["d"]) == (0, 1) and got["x"]["located"] == 1
    assert got["_found"][0]["beside"] is None
    assert got["_found"][0]["sentence"].startswith("**The chain.** No series is served at the tariff link")
    names = dict(gev._served_absence_names(_page("smoke2_deep_tariff_soybeans")[0]["state_board"]))
    assert names.get("China import tariff") == "hop"


def test_the_append_is_located_by_its_producers_own_words_never_by_a_typed_phrase():
    words = gev._absence_append_words()
    assert words and words.endswith(":")
    from leviathan.graphrag import answer as an
    assert f"({words} [N7]" in an._absence_append("x.", 7, {7: {"value": "1", "unit": "z", "known": ""}},
                                                   handle_prose=True)


# -- 4. LONG LABELS IN A SENTENCE (R4-1) -----------------------------------------------------------------------------
def _book_or_contracted_shorts(monkeypatch) -> None:
    """Lane R's `reading_short` (C4-9) where the tree's book declares it; where it does not yet, the two cards this
    page's seams named get a stand-in short name DIFFERENT from their long one (C4-9's own shape, labelled) -- and
    every other card none, which is exactly the book-less reading the row must not count."""
    real = gev._reading_short
    stand_in = {("gold_weather_z", "drought_z"), ("silver_pink_sheet", "brent_crude_usd_bbl_zscore_5yr")}

    def _short(rd, table, metric):
        got = real(rd, table, metric)
        return got or ("<C4-9 short name>" if (table, metric) in stand_in else "")
    monkeypatch.setattr(gev, "_reading_short", _short)


def test_a_long_card_label_the_seams_wrote_beyond_the_draft_is_counted_and_the_writers_own_uses_are_not(monkeypatch):
    _book_or_contracted_shorts(monkeypatch)
    got = _read("smoke1_quick_palm_rapeoil", "long_label_in_sentence")
    assert got["v"] == 3 and got["d"] == 2                            # 2 routing corrections; a chain line wrote 1
    by = {f["name"]: f["seam_written"] for f in got["_found"]}
    assert by == {"the longest dry-day run in the month, as a z-score": 2,
                  "the Brent crude price against its own five-year record": 1}
    rec, live = _served("smoke1_quick_palm_rapeoil")
    # the writer's own use of the long name (in the post-verify draft) is never a correction's
    rec["raw_draft"]["postverify_mechanism"] += " the longest dry-day run in the month, as a z-score"
    assert gev._instrument_row(rec, live)["long_label_in_sentence"]["v"] == 2


def test_without_a_declared_short_name_a_long_label_cannot_be_told_and_the_row_is_absent(monkeypatch):
    """HEAD's book declares no `reading_short`: every card name a seam wrote would read as "long" (MEASURED on the
    63: 78 against the 9 real ones) -- so the row reads nothing and says why."""
    monkeypatch.setattr(gev, "_reading_short", lambda rd, table, metric: "")
    got = _read("smoke1_quick_palm_rapeoil", "long_label_in_sentence")
    assert got["v"] is None and got["d"] == 2 and "reading_short" in got["why"]


# -- 5. A THRESHOLD CITATION INSIDE A NOUN (V4-3) --------------------------------------------------------------------
def _palm_report() -> dict:
    """The verifier's threshold_cited audit entries on the palm/rape page, RESTATED from its own banked output: each
    handle stands after its label in the post-verify draft and NOT in the pre-verify one (the verifier wrote it)."""
    rec, _body = _page("smoke1_quick_palm_rapeoil")
    rd = rec["raw_draft"]
    ents = [("tldr", 14, "severe"), ("mechanism", 14, "severe"), ("mechanism", 42, "ample")]
    for fld, h, lab in ents:
        assert f"{lab} [N{h}] line" in rd["postverify_" + fld] and f"{lab} [N{h}]" not in rd["preverify_" + fld]
    return {"citation_verifier": {"threshold_cited": 3, "direction_audit": [
        {"field": f, "handle": h, "label": lab, "rule": "threshold_cited", "row_id": "x"} for f, h, lab in ents]}}


def test_a_threshold_citation_between_its_label_and_the_declared_head_noun_is_counted(monkeypatch):
    from leviathan.graphrag.state import render as rd
    monkeypatch.setattr(rd, "THRESHOLD_CLAUSE_NOUN", "line", raising=False)   # C4-6 (lane R), labelled
    got = _read("smoke1_quick_palm_rapeoil", "handle_inside_noun", trace=_palm_report())
    assert (got["v"], got["d"]) == (3, 3)
    assert got["x"] == {"inserted": 3, "located": 3, "inside_noun": 3, "own_group_beside_another": 0}
    assert [f["handle"] for f in got["_found"]] == [14, 14, 42]       # the TL;DR's spot and the body's: two, never one


def test_a_citation_placed_after_the_noun_phrase_is_not_inside_it(monkeypatch):
    from leviathan.graphrag.state import render as rd
    monkeypatch.setattr(rd, "THRESHOLD_CLAUSE_NOUN", "line", raising=False)   # C4-6 (lane R), labelled
    rec, live = _served("smoke1_quick_palm_rapeoil", trace=_palm_report())
    live["out"]["answer"] = (live["out"]["answer"].replace("severe [N14] line", "severe line [N14]")
                             .replace("ample [N42] line", "ample line [N42]"))
    got = gev._instrument_row(rec, live)["handle_inside_noun"]
    assert (got["v"], got["d"]) == (0, 3) and got["x"]["located"] == 0


def test_without_a_declared_head_noun_or_a_live_report_the_row_is_absent(monkeypatch):
    from leviathan.graphrag.state import render as rd
    monkeypatch.delattr(rd, "THRESHOLD_CLAUSE_NOUN", raising=False)
    got = _read("smoke1_quick_palm_rapeoil", "handle_inside_noun", trace=_palm_report())
    assert got["v"] is None and got["d"] == 3 and "THRESHOLD_CLAUSE_NOUN" in got["why"]
    assert _read("smoke1_quick_palm_rapeoil", "handle_inside_noun")["why"].startswith("the verifier's report")


# -- 6. A CHANGE ROW EQUAL TO ITS LEVEL (F4-1) -----------------------------------------------------------------------
def test_the_as_of_cocoa_pages_sixty_three_session_change_equal_to_its_level_is_counted():
    rec, _body = _page("probe_deep_cocoa_asof_2026_04")
    got = gev._instrument_row(rec)["change_row_equals_level"]          # served_rows: read on the banked record too
    assert (got["v"], got["d"]) == (1, 4)
    assert got["_found"] == [{"metric": "settle change over 63 sessions", "value": 3630.0, "level": 3630.0,
                              "unit": "USD/metric ton"}]
    table, metric = gev._tape_card()
    from leviathan.graphrag.state import feeders as fd
    assert (table, metric) == (fd.TAPE_TABLE, fd.TAPE_METRIC)          # the producer's card, never typed here


def test_the_change_family_is_the_producers_registration_run_and_a_budget_cut_row_is_unread():
    rec, _body = _page("smoke1_quick_corn_wheat")
    got = gev._instrument_row(rec)["change_row_equals_level"]
    assert got["v"] == 0 and got["d"] == got["x"]["change_rows"] - got["x"]["unread"] and got["d"] > 0
    for c in rec["served_rows"]:
        if str(c.get("metric") or "").startswith("settle change over"):
            c["rows"] = []                                           # the per-record row budget's header-only call
    cut = gev._instrument_row(rec)["change_row_equals_level"]
    assert cut["v"] is None and cut["why"] == "no readable tape change row on the record"


# -- 7. A ROW KNOWN AFTER THE AS-OF (F4-2) ---------------------------------------------------------------------------
def test_the_footer_line_known_after_the_as_of_is_counted_at_the_stamps_own_grain():
    got = _read("probe_deep_cocoa_asof_2026_04", "known_after_asof")
    assert (got["v"], got["d"]) == (1, 36)
    assert got["_found"][0]["asof"] == "2026-04-15" and got["_found"][0]["line"].startswith("[N76] ")
    assert got["_found"][0]["line"].endswith("[known 2026-05-05]")
    assert gev._known_stamp() == ("  [known ", "]")                  # the footer's own format, read off citations


def test_the_as_of_falls_back_to_the_deck_query_and_is_absent_without_either():
    rec, live = _served("smoke1_quick_corn_wheat")
    rec["state_board"].pop("asof")
    assert gev._instrument_row(rec, live)["known_after_asof"]["why"].startswith("no as-of on the record")
    live["q"]["asof"] = "2026-09-01"                                  # a deck as-of before the page's stamps
    got = gev._instrument_row(rec, live)["known_after_asof"]
    assert got["v"] > 0 and got["src"].endswith("the deck query's asof")


# -- 8. A RAW UNIT SPELLING (R4-2) -----------------------------------------------------------------------------------
def test_a_prose_figure_printed_in_the_stored_scaled_spelling_is_counted_against_every_spelling_of_that_unit():
    got = _read("smoke1_quick_corn_wheat", "raw_unit_spelling")
    assert (got["v"], got["d"]) == (3, 3)
    assert got["_found"] == [{"unit": "(1000 MT)", "stored": 3, "reader_spelling": 0}]
    rec, live = _served("smoke1_quick_corn_wheat")
    live["out"]["answer"] = live["out"]["answer"].replace(" 1000 MT", " thousand tonnes")
    fixed = gev._instrument_row(rec, live)["raw_unit_spelling"]
    assert (fixed["v"], fixed["d"]) == (0, 3)                         # the reader spelling the verifier's grammar reads


# -- 9. THE NETTING PARTS' NAMES (I4-2: BLOCKER-1 + NOTE-1) ----------------------------------------------------------
def test_an_event_printed_with_only_its_receipt_is_a_part_read_by_its_E_address():
    """The as-of probe's ask head: `{"opposing": [29], "tape": 55, "event_e": 13}` -- HEAD read two parts."""
    rec, _body = _page("probe_deep_cocoa_asof_2026_04")
    assert rec["state_board"]["ask_netting"] == {"opposing": [29], "tape": 55, "event_e": 13}
    got = gev._netting_read(rec, None, None)
    assert got["d"] == 3 and got["_page"]["printed"] == ["opposing", "event", "tape"]
    assert got["x"]["event"]["readings"] == 1


def test_every_markets_parts_are_read_and_the_top_level_is_never_counted_twice():
    rec, _body = _page("smoke1_quick_palm_rapeoil")
    an = rec["state_board"]["ask_netting"]
    got = gev._netting_read(rec, None, None)
    assert got["d"] == sum(1 for m in an["by_market"].values() for p in ("opposing", "event", "tape") if m.get(p))
    assert got["d"] == 8 and all(":" in lb for lb in got["_page"]["printed"])
    first = next(iter(an["by_market"]))
    assert f"{first}:opposing" in got["_page"]["printed"] and "opposing" not in got["_page"]["printed"]
    an["not_a_part"] = [16]                                           # a key the contract does not name
    assert gev._netting_read(rec, None, None)["d"] == 8


def test_a_facts_whole_name_is_the_books_name_for_its_rows_card_and_the_tape_has_none():
    names, scope = gev._netting_row_names({"row_id": "soybeans_cbot|El_Nino|oni_climate|_global|"})
    from leviathan.graphrag.state import render as rd
    assert rd.reading_words("silver_noaa_oni", "oni_anom") in names and scope == ""
    assert gev._netting_row_names({"row_id": "soybeans_cbot||silver_futures_eod|soybeans_cbot|2026-11"}) == ((), "")
    assert gev._netting_row_names(63) == ((), "")                     # a bare handle names nothing (sitting 3 pin)
    _n, scope = gev._netting_row_names(
        {"row_id": "soft_red_winter_wheat_cbot|area|area|soft_red_winter_wheat_cbot|United States"})
    assert scope == "United States"


def test_a_name_is_told_whole_with_its_scope_in_one_sentence_or_not_at_all():
    """The corn/wheat TL;DR's "a collapsed harvested area [N14]" names the card's name but not its scope's words
    whole (it says "US"): not told by name -- the error stays under-claim."""
    rec, _body = _page("smoke1_quick_corn_wheat")
    from leviathan.graphrag import verify as vf
    sents = [" ".join(s.lower().split()) for s in vf.sentences(rec["raw_draft"]["postverify_tldr"])]
    assert gev._whole_name_told(sents, ("harvested area",), "") is True
    assert gev._whole_name_told(sents, ("harvested area",), "United States") is False
    assert gev._whole_name_told(sents, ("harvested",), "") is True and gev._whole_name_told(sents, ("harvest",), "") \
        is False                                                      # whole words only


# -- 10. THE BANKED EPISODE WINDOWS (I4-3) ---------------------------------------------------------------------------
def test_the_record_banks_episodes_injected_verbatim_and_a_flag_off_record_keeps_heads_columns():
    eps = [{"node": "drivers/frost", "line": "DATED EPISODES for drivers/frost ...", "spans": ["1994-06..1994-08"],
            "windows": [{"start": "1994-06-01", "end": "1994-08-31", "span": "1994-06..1994-08", "n": 3}]},
           {"node": "drivers/drought", "line": "floored", "spans": [], "windows": [], "floored": True}]
    on = gev._per_answer_record({"q": {"id": "x"}, "out": {"trace": {"planner": "l2", "episodes_injected": eps}}},
                                "single")
    off = gev._per_answer_record({"q": {"id": "x"}, "out": {"trace": {"planner": "l2"}}}, "single")
    assert on["episodes_injected"] == eps and "episodes_injected" not in off
    assert [k for k in on if k != "episodes_injected"] == list(off)   # one column, only on the row that has it
    assert list(on)[-1] == "bare_handle_escapes"                      # the tail pin holds


# -- 11. THE REPORT ---------------------------------------------------------------------------------------------------
def test_the_report_prints_each_row_with_its_population_and_every_instance_it_counted():
    per, rows = [], []
    for name in ("probe_deep_cocoa_asof_2026_04", "smoke1_quick_palm_rapeoil", "smoke1_quick_corn_wheat",
                 "smoke1_max_soybeans_2026_09_07", "smoke2_deep_tariff_soybeans"):
        rec, live = _served(name)
        rec["id"] = name
        per.append(rec)
        rows.append(live)
    cen = gev.instrument_census(per, rows)
    rep = gev.instrument_report(cen)
    for name in _S4:
        line = next(x for x in rep if x.startswith(f"- {name}:"))
        assert "(population: " in line and "n=" in line, line
    assert cen["census"]["change_row_equals_level"]["value"] == 1
    assert cen["census"]["known_after_asof"]["value"] == 1
    assert any(x.startswith("  - change row equal to its level `probe_deep_cocoa_asof_2026_04`") for x in rep)
    assert any(x.startswith("  - bare handle `smoke1_quick_palm_rapeoil` (post_verify_seam): N61, N8") for x in rep)
    assert any(x.startswith("  - absence append `smoke2_deep_tariff_soybeans` no served absence named") for x in rep)
    assert "episodes_injected" not in cen and "instruments" not in per[0]
