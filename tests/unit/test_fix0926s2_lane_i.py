"""FIX SITTING 2 (2026-09-26), LANE I -- THE INSTRUMENTS, RESIDUAL AFTER 511631c5 (CONTRACT Y15).

THE DECK-LEVEL PIN: the instrument census runs over a COMMITTED fixture reduced from the six arm-A baselines
(tests/fixtures/instrument_census_0926/, both cells, keys verbatim, each file named after its source
baseline) and asserts that every instrument the report QUOTES as a result was asserted NON-VACUOUS on that
deck -- at least `_VACUITY_MIN_N` pages carried a reading and they differ -- and that the vacuous set is
exactly the one the census names. The fixture is REAL banked seat output (threat I1-b: never synthetic for
this pin); the measured sets are pinned because the fixture is frozen, so a reader that moves moves them.

THE NEW ROWS (each ABSENT until its producer key is on the record): absence_binding, prose_ceiling,
duplicate_handles, esr_national_rows, held_rows_in_claims, window_draw; the re-based fields censused on their
own (tldr_direction.declared, tldr_direction.basis -- threat I1-a); the FROZEN v1 register table beside the
extended one (I1-d); the count check reading a qualified noun the block registered against that noun only
(I2-a). Where a pin needs a producer key no banked record carries yet (the contracted Y1 / Y5 / Y10 / Y12 /
Y20 / Y22 keys), it COPIES a fixture record and adds that ONE key -- labelled at the site, every other field
the banked page's own.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from leviathan.graphrag import eval as gev
from leviathan.graphrag import register as reg

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "instrument_census_0926"
_REDUCED_TOP = {"id", "intent", "intent_ok", "kind_history", "mode_decision", "tldr_direction", "register_leaks",
                "desk_register", "writer_seam", "bridge_query", "raw_draft", "served_rows", "state_board"}
_NEW_ROWS = ("absence_binding", "prose_ceiling", "duplicate_handles", "esr_national_rows", "held_rows_in_claims",
             "window_draw")


def _docs() -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(_FIX.glob("*_2026*.json"))]


def _cell(cell: str) -> list:
    return [r for d in _docs() if d["cell"] == cell for r in d["per_answer"]]


def _rec(cell: str, rid: str, mode: str = "deep") -> dict:
    """A DEEP COPY of one banked record (so a pin that adds a contracted key never touches the fixture)."""
    for d in _docs():
        if d["cell"] == cell and d["mode"] == mode:
            for r in d["per_answer"]:
                if r["id"] == rid:
                    return copy.deepcopy(r)
    raise KeyError((cell, rid, mode))


# -- 0. THE FIXTURE IS THE BANKED ARM, REDUCED, NEVER SYNTHETIC (I1-b) ------------------------------------------
def test_the_fixture_is_the_six_arm_a_baselines_reduced_with_both_cells():
    docs = _docs()
    assert len(docs) == 6
    assert sorted((d["cell"], d["mode"], len(d["per_answer"])) for d in docs) == [
        ("control", "deep", 6), ("control", "max", 1), ("control", "quick", 3),
        ("treatment", "deep", 6), ("treatment", "max", 1), ("treatment", "quick", 3)]
    for d in docs:
        assert d["source"].endswith(".json") and len(d["source_sha256"]) == 64
        for r in d["per_answer"]:
            assert set(r) <= _REDUCED_TOP, set(r) - _REDUCED_TOP         # only census-read keys, never a new one
            assert list(r)[0] == "id"
    ids = {c: sorted(r["id"] for r in _cell(c)) for c in ("control", "treatment")}
    assert ids["control"] == ids["treatment"] and len(ids["control"]) == 10


# -- 1. THE DECK-LEVEL PIN (Y15): QUOTED == ASSERTED NON-VACUOUS ------------------------------------------------
def _assert_quoted_is_non_vacuous(cen: dict) -> None:
    names = [n for n, _k, _p in gev._INSTRUMENTS]
    for name in names:
        c = cen["census"][name]
        assert c["quoted"] is (c["vacuous"] is False), (name, c)
    assert cen["quoted"] == [n for n in names if cen["census"][n]["vacuous"] is False]
    assert cen["vacuous"] == [n for n in names if cen["census"][n]["vacuous"] is True]
    rep = gev.instrument_report(cen)
    qline = next(x for x in rep if x.startswith("- **quoted as results**"))
    assert qline.rsplit("): ", 1)[1] == (", ".join(cen["quoted"]) or "none")
    vline = next(x for x in rep if x.startswith("- **vacuous instruments**"))
    assert vline.rsplit("): ", 1)[1] == (", ".join(cen["vacuous"]) or "none")
    for name in names:
        line = next(x for x in rep if x.startswith(f"- {name}:"))
        marked = ("ABSENT on every page" in line or "NOT QUOTED -- VACUOUS" in line
                  or "UNTESTED, NOT A RESULT" in line)
        assert marked is (not cen["census"][name]["quoted"]), line          # quoted <=> unmarked


def test_quoted_instruments_non_vacuous():
    """THE PIN THE CONTRACT NAMES: per cell (one arm cell = its deep + max + quick pages), every quoted
    instrument is non-vacuous and the vacuous set is the census's own. MEASURED on the frozen fixture."""
    control = gev.instrument_census(_cell("control"))
    treatment = gev.instrument_census(_cell("treatment"))
    for cen in (control, treatment):
        assert cen["pages"] == 10
        _assert_quoted_is_non_vacuous(cen)
    assert control["vacuous"] == ["intent_ok", "tldr_direction.agree [producer]", "register_leaks"]
    assert treatment["vacuous"] == ["intent_ok", "tldr_direction.agree [producer]",
                                    "coverage.watch_cited [producer]", "coverage.events_referenced [producer]",
                                    "absence_binding"]
    assert control["quoted"] == ["n_sections", "desk_register_hits", "desk_register_hits.v1",
                                 "esr_national_rows"]
    assert treatment["quoted"] == ["n_sections", "coverage.watch_referenced [producer]", "register_leaks",
                                   "desk_register_hits", "count_mismatches", "desk_register_hits.v1",
                                   "tldr_direction.basis", "prose_ceiling", "duplicate_handles",
                                   "esr_national_rows"]


def test_intent_ok_on_a_banked_record_is_named_vacuous_and_never_quoted():
    """THREAT I1-e: a banked record carries the OLD per-answer `intent_ok` column (the deck's expected word is
    not on the record, so the deck-level vocabulary read cannot run). The census NAMES it vacuous; the
    re-based reader is proven on a live run's rows, never claimed on banked records."""
    for cell in ("control", "treatment"):
        cen = gev.instrument_census(_cell(cell))
        assert "intent_ok" in cen["vacuous"] and "intent_ok" not in cen["quoted"]
        assert cen["census"]["intent_ok"]["constant"] is False
        assert cen["census"]["intent_ok"]["sources"] == {"per-answer intent_ok": 10}


def test_a_banked_run_read_per_file_quotes_nothing_it_could_not_test():
    """The CLI's per-baseline read: a 1- or 3-page file carries too few readings for a vacuity test, so it
    QUOTES NOTHING -- every read line says UNTESTED, NOT A RESULT; the 6-page deep files quote only what
    they assert non-vacuous."""
    for d in _docs():
        cen = gev.instrument_census(d["per_answer"])
        _assert_quoted_is_non_vacuous(cen)
        if len(d["per_answer"]) < gev._VACUITY_MIN_N:
            assert cen["quoted"] == [] and cen["vacuous"] == [], d["source"]
            rep = gev.instrument_report(cen)
            assert any("UNTESTED, NOT A RESULT" in x for x in rep)


# -- 2. THE RE-BASED FIELDS ARE CENSUSED TOO (I1-a) -----------------------------------------------------------
def test_a_writer_that_declares_one_token_on_every_page_is_named_vacuous():
    """THREAT I1-a: a writer declaring `two_sided` on every page makes `tldr_direction` ABSENT (a
    non-directional token is never tested) -- which would HIDE the constant. The declared field has its own
    row, and it is named. (CONTRACT Y14's key added to banked treatment records: the only synthetic field.)"""
    recs = _cell("treatment")
    for r in recs:
        r["tldr_direction"] = dict(r["tldr_direction"], declared="two_sided")
    cen = gev.instrument_census(recs)
    assert cen["census"]["tldr_direction"]["n"] == 0
    assert set(cen["census"]["tldr_direction"]["absent"]) <= {"declared token not directional",
                                                               "no settled side on the board"}
    assert "tldr_direction.declared" in cen["vacuous"]
    assert cen["census"]["tldr_direction.declared"]["constant"] == "two_sided"


def test_the_side_basis_is_read_off_the_board_and_is_varied_on_the_treatment_cell():
    cen = gev.instrument_census(_cell("treatment"))
    b = cen["census"]["tldr_direction.basis"]
    assert b["value"] == {"higher": 6, "lower": 1} and b["n"] == 7 and b["vacuous"] is False
    assert b["sources"] == {"state_board.chains[rendered].side": 7}
    assert b["absent"] == {"no settled side on the board": 3}          # cotton, rice, soyoil: unsettled only
    assert gev.instrument_census(_cell("control"))["census"]["tldr_direction.basis"]["n"] == 0   # no board


# -- 3. THE NEW ROWS: ABSENT UNTIL THE PRODUCER KEY IS ON THE RECORD ------------------------------------------
def test_every_new_row_is_absent_where_its_producer_key_is_missing_never_zero():
    control = gev.instrument_census(_cell("control"))
    for name in ("absence_binding", "prose_ceiling", "duplicate_handles"):
        c = control["census"][name]
        assert c["n"] == 0 and c["value"] is None, name                  # the control ran no writer seam
    treatment = gev.instrument_census(_cell("treatment"))
    for cen in (control, treatment):
        for name in ("held_rows_in_claims", "window_draw"):
            assert cen["census"][name]["n"] == 0 and cen["census"][name]["value"] is None
    assert treatment["census"]["held_rows_in_claims"]["absent"] == {
        "state_board.retention absent (the P-1 retention stamp is not on the record)": 10}
    assert treatment["census"]["window_draw"]["absent"] == {
        "bridge_query.window_draw absent (not built on the page, or no node was stale)": 10}
    assert control["census"]["window_draw"]["absent"] == {
        "bridge_query absent (GRAPHRAG_BRIDGE_QUERY off on the page)": 10}


def test_the_absence_seam_is_read_as_the_recon_measured_it_and_named_vacuous():
    """The recon: "checked 19, unbound 19, appended 0 (0 of 19 bound)" over the arm-A treatment pages. A page
    that made no absence claim is ABSENT (nothing to bind is not a binding of zero)."""
    cen = gev.instrument_census(_cell("treatment"))
    c = cen["census"]["absence_binding"]
    assert (c["value"], c["denominator"], c["n"], c["vacuous"]) == (0, 19, 9, True)
    assert c["absent"] == {"no absence claim on the page": 1}           # cocoa
    tot = cen["details"]["absence_binding"]["totals"]
    assert (tot["absence_claims_checked"], tot["absence_unbound"], tot["absence_rows_appended"]) == (19, 19, 0)
    rep = "\n".join(gev.instrument_report(cen))
    assert "absence_reason_corrected: not stamped" in rep and "absence_bound_seat: not stamped" in rep


def test_the_prose_ceiling_is_read_per_tier_with_its_ratio():
    cen = gev.instrument_census(_cell("treatment"))
    c = cen["census"]["prose_ceiling"]
    assert (c["value"], c["n"], c["vacuous"]) == (1, 10, False)          # cocoa alone sat within 900 words
    tiers = cen["details"]["prose_ceiling"]["by_tier"]
    assert {t: (x["pages"], x["within"], x["ceiling"]) for t, x in tiers.items()} == {
        "deep": (6, 1, [900]), "max": (1, 0, [1200]), "quick": (3, 0, [450])}
    assert tiers["quick"]["max_ratio"] == 3.28 and tiers["quick"]["cut_paragraphs"] is None
    rep = "\n".join(gev.instrument_report(cen))
    assert "tier `quick`: 0 of 3 page(s) within the ceiling" in rep and "whole paragraphs cut: not stamped" in rep


def test_the_esr_national_read_names_the_one_buyer_rows_by_the_cards_declaration():
    """PC-1's defect, read off the served rows: a no-destination read of a declared metric on a card that
    declares a national fold, answered by ONE buyer's row. Control: 6 of 9 such reads on 5 pages
    (Costa Rica / El Salvador / Canada / Guatemala); treatment: 6 of 49."""
    ctl = gev.instrument_census(_cell("control"))["census"]["esr_national_rows"]
    trt = gev.instrument_census(_cell("treatment"))["census"]["esr_national_rows"]
    assert (ctl["value"], ctl["denominator"], ctl["n"]) == (6, 9, 5)
    assert (trt["value"], trt["denominator"], trt["n"]) == (6, 49, 7)
    cards = gev._national_fold_cards()
    assert set(cards) == {"silver_esr"}                                  # read off tables.yaml, not typed here
    assert "weekly_exports_1000mt" in cards["silver_esr"]
    # a DERIVED pace row on the same table is not a read of a declared metric; a destination-named read is
    # not a national read -- the reader's population, on a banked page
    rec = _rec("control", "event_china_tariff_soybeans_2026_09")
    got = gev._esr_national_read(rec)
    assert (got["v"], got["d"], got["x"]["one_buyer"]) == (1, 1, 1)
    named = copy.deepcopy(rec)
    for c in named["served_rows"]:
        if c["table"] == "silver_esr":
            c["country"] = "China"                                       # a destination-named read (synthetic key)
    assert gev._esr_national_read(named)["v"] is None


def test_a_folded_row_is_counted_folded_never_one_buyer():
    """CONTRACT Y1's `_fold` marker (the only field added): the compiler's national row, summed over buyers,
    carries no buyer and the marker -- it reads `folded`, and the page's one-buyer count falls."""
    rec = _rec("control", "event_china_tariff_soybeans_2026_09")
    for c in rec["served_rows"]:
        if c["table"] == "silver_esr" and c["metric"] == "weekly_exports_1000mt":
            c["rows"] = [{"country": None, "_fold": {"axis": "destination", "rule": "sum", "n": 97}}]
    got = gev._esr_national_read(rec)
    assert (got["v"], got["x"]["folded"], got["x"]["one_buyer"]) == (0, 1, 0)


def test_served_rows_carry_the_fold_marker_only_where_the_producer_stamped_it():
    plain = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"}, "status": "ok",
             "rows": [{"period": "2026-09-17", "value": 0.0, "unit": "1000 MT", "country": "Costa Rica"}]}
    folded = copy.deepcopy(plain)
    folded["rows"] = [{"period": "2026-09-17", "value": 775.392, "unit": "1000 MT",
                       "_fold": {"axis": "destination", "rule": "sum", "n": 97}}]
    p = gev._served_rows({"number_calls_full": [plain]})[0]["rows"][0]
    assert "_fold" not in p and list(p) == ["period", "estimate_role", "value", "unit", "country",
                                             "knowledge_date"]                  # HEAD's projection, exactly
    f = gev._served_rows({"number_calls_full": [folded]})[0]["rows"][0]
    assert f["_fold"] == {"axis": "destination", "rule": "sum", "n": 97} and list(f)[-1] == "_fold"


def test_duplicate_handles_reads_the_seam_count_and_the_ledger_stamp_where_it_ran():
    cen = gev.instrument_census(_cell("treatment"))
    c = cen["census"]["duplicate_handles"]
    assert (c["value"], c["n"], c["vacuous"]) == (180, 10, False)
    assert cen["details"]["duplicate_handles"]["stamped_pages"]["ledger"] == 0     # no ledger at 9750ae3e
    rec = _rec("treatment", "state_rice_2026_09")
    rec["state_board"]["numbers_ledger"] = {"issued": 60, "reused": 18, "identity_value_conflict": 1}  # Y22 key
    got = gev._duplicate_handles_read(rec)
    assert got["v"] == 18 and got["x"]["ledger"] == {"issued": 60, "reused": 18, "identity_value_conflict": 1}


def test_the_window_draw_and_the_retention_stamp_are_read_where_their_keys_land():
    rec = _rec("treatment", "rv_palm_rapeoil", mode="quick")
    rec["bridge_query"] = dict(rec["bridge_query"], window_draw={"nodes": 21, "stale": 4, "added": 9,
                                                                 "statements": 1, "ms": 212,
                                                                 "floor_unknown": 0})   # CONTRACT Y10's key
    got = gev._window_draw_read(rec)
    assert (got["v"], got["d"], got["src"]) == (9, 4, "bridge_query.window_draw")
    rec["state_board"]["retention"] = {"read": True, "keys": 3, "stamped": 2, "ms": 40}      # CONTRACT Y5's key
    held = gev._held_rows_read(rec)
    # THE BLOCKER, READ HONESTLY: the stamped population is the denominator; the TL;DR half stays ABSENT
    assert held["v"] is None and held["d"] == 2 and "no trace key maps a held row" in held["why"]


def test_the_contracted_absence_and_ceiling_keys_are_read_where_stamped():
    rec = _rec("treatment", "state_rice_2026_09")
    rec["writer_seam"].update({"absence_reason_corrected": 1, "absence_bound_seat": 1,        # CONTRACT Y12
                               "ceiling_cut_paragraphs": 2, "ceiling_kept_over": 1})          # CONTRACT Y20
    recs = [rec] + [r for r in _cell("treatment") if r["id"] != "state_rice_2026_09"]
    cen = gev.instrument_census(recs)
    st = cen["details"]["absence_binding"]["stamped_pages"]
    assert st["absence_reason_corrected"] == 1 and st["absence_bound_seat"] == 1
    assert cen["details"]["prose_ceiling"]["by_tier"]["deep"]["cut_paragraphs"] == 2


# -- 4. THE REGISTER: THE FROZEN v1 TABLE BESIDE THE EXTENDED ONE (I1-d) ---------------------------------------
def test_the_register_line_prints_the_v1_subset_beside_the_extended_table_in_each_cell():
    for cell, key, (ext, v1) in (("control", "mandate-dark", (53, 33)), ("treatment", "mandate-lit", (25, 21))):
        cen = gev.instrument_census(_cell(cell))
        c = cen["register_cells"][key]
        assert (c["desk_register_hits"], c["desk_register_hits_v1"], c["desk_v1_n"]) == (ext, v1, 10)
        line = next(x for x in gev.instrument_report(cen) if x.startswith(f"- register, {key} cell"))
        assert "FROZEN v1 table" in line and f": {v1} on " in line
        assert line.count("(population:") == 2 and line.count("n=") == 2      # a SUBSET, never a third population


def test_a_table_that_grows_moves_the_extended_count_and_never_the_v1_count(monkeypatch):
    rec = _rec("control", "state_cocoa_2026_09")
    before = gev._instrument_row(rec)
    real = reg.desk_register_hits
    monkeypatch.setattr(reg, "desk_register_hits",
                        lambda text: real(text) + [("a grown row", "ctx")] * 3)      # three names off v1
    after = gev._instrument_row(rec)
    assert after["desk_register_hits"]["v"] == before["desk_register_hits"]["v"] + 3
    assert after["desk_register_hits.v1"]["v"] == before["desk_register_hits.v1"]["v"]
    assert set(reg.DESK_REGISTER_V1_NAMES) <= {n for n, _p, _r in reg.DESK_REGISTER_TOKENS}


# -- 5. THE COUNT CHECK: THE BLOCK'S OWN NOUN (I2-a) ------------------------------------------------------------
def test_a_count_beside_a_qualified_noun_the_block_registered_is_read_against_that_noun_only():
    """CONTRACT C-I6's `served_counts` (the only synthetic field: N mints it) on the banked rice treatment
    page, whose own draft says "declared on three other markets here" and "twenty-nine of the thirty-four
    other markets tracked" and "run into these three markets"."""
    rec = _rec("treatment", "state_rice_2026_09")
    prose = rec["raw_draft"]["postverify_mechanism"]
    assert "three other markets here" in prose and "thirty-four other markets" in prose
    sb = dict(rec["state_board"], served_counts=[{"noun": "other markets", "value": 34,
                                                  "text": "thirty-four other markets"},
                                                 {"noun": "markets", "value": 3, "text": "these three markets"}])
    pool = gev._count_pool(sb)
    assert pool[("other", "market")] == {34} and 3 in pool["market"] and 34 in pool["market"]
    got = gev._count_check(prose, pool)
    other = [m for m in got["mismatches"] if m["noun"] == "other market"]
    # "three other markets here" is read against the fan's OWN count (34) and fails; under the head-noun
    # floor it would have PASSED against the count line's 3 -- the wrong noun
    assert [(m["printed"], m["trace_values"]) for m in other] == [(3, [34])]
    assert not [m for m in got["mismatches"] if m["printed"] == 34]          # 34 other markets: read right
    assert not [m for m in got["mismatches"] if "these three markets" in m["quote"]]   # the head floor


def test_without_a_registered_phrase_the_head_noun_floor_is_unchanged():
    rec = _rec("treatment", "state_rice_2026_09")
    prose = rec["raw_draft"]["postverify_mechanism"]
    pool = gev._count_pool(rec["state_board"])
    assert not [k for k in pool if isinstance(k, tuple)]
    got = gev._count_check(prose, pool)
    assert sorted((m["noun"], m["printed"]) for m in got["mismatches"]) == [("market", 3), ("market", 3),
                                                                             ("market", 34)]


# -- 6. THE CLI READS AN ARM CELL AS ONE DECK -------------------------------------------------------------------
def test_the_cli_reads_several_banked_files_as_one_deck(monkeypatch, capsys):
    files = [str(p) for p in sorted(_FIX.glob("*_2026*.json"))
             if json.loads(p.read_text(encoding="utf-8"))["cell"] == "treatment"]
    monkeypatch.setattr("sys.argv", ["eval", "--instruments-from", *files])
    assert gev.main() == 0
    out = capsys.readouterr().out
    assert "deck read from 3 files" in out
    assert "- **quoted as results**" in out and "absence_binding" in out.split("- **vacuous instruments**")[1]
    monkeypatch.setattr("sys.argv", ["eval", "--instruments-from", files[1]])           # one file still works
    assert gev.main() == 0
    assert "deck read from" not in capsys.readouterr().out


@pytest.mark.parametrize("name", _NEW_ROWS)
def test_every_new_row_prints_its_population_and_its_n(name):
    rep = gev.instrument_report(gev.instrument_census(_cell("treatment")))
    line = next(x for x in rep if x.startswith(f"- {name}:"))
    assert "(population: " in line and ", n=" in line, line
