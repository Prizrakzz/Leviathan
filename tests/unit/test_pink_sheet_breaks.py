"""LANE (b): the Pink Sheet SERIES-REPLACEMENT log, pinned.

THE FAILURE MODE THIS TRIPWIRE EXISTS FOR is the mirror image of a rename: the column name NEVER
changes, but the thing it names is REPLACED.  The 71 header strings were byte-identical Jan-2025 ->
Sep-2026 while the Description sheet logged SEVEN same-name/different-series replacements over that
same history.  The estate's usual remedy -- key on the source's stable code -- cannot be applied,
because the World Bank's own codes appear in exactly ONE of the six measured vintages.  So the
parsed log IS the tripwire.

The Description sheet's CELL LAYOUT was not reachable from the seat that built this, so the parser
makes no assumption about which row or column a sentence sits in and these pins drive it on
sentence text.  ``break_log_decline`` is what keeps "we found nothing" from being read as "there is
nothing".

AWS-free, network-free.
"""
from __future__ import annotations

import pytest
from leviathan.transforms.raw_to_bronze import pink_sheet_breaks as K


class TestSentenceParsing:
    def test_a_month_and_year_replacement_is_parsed_whole(self):
        got = K.parse_break_sentences([
            "Beef: the series was replaced in January 2024 with a new Australian quotation."])
        assert len(got) == 1
        assert got[0].series == "Beef"
        assert got[0].break_month == "2024-01"
        assert got[0].month_known is True
        # THE SENTENCE IS VERBATIM. A paraphrase of a provenance note is a new claim.
        assert got[0].sentence.startswith("Beef: the series was replaced in January 2024")

    def test_a_year_only_break_is_dated_january_and_FLAGGED_as_month_unknown(self):
        """The Rubber TSR20 entry is dated by year alone. Inventing a month for it would be a
        fabricated precision, so the flag rides instead."""
        got = K.parse_break_sentences(
            ["Rubber TSR20 replaces RSS3 in the index from 2018."])
        assert len(got) == 1
        assert got[0].break_month == "2018-01"
        assert got[0].month_known is False

    def test_a_switched_origin_reads_as_a_replacement(self):
        got = K.parse_break_sentences([
            "Chicken: the quotation switched from USA to Brazil in September 2021."])
        assert [(b.series, b.break_month) for b in got] == [("Chicken", "2021-09")]

    def test_several_statements_in_ONE_cell_are_split(self):
        cell = ("Lamb was replaced in January 2020. Potassium chloride: the quotation moved and "
                "was replaced in January 2020; Groundnut oil was replaced in January 2023.")
        got = K.parse_break_sentences([cell])
        assert len(got) == 3
        assert {b.break_month for b in got} == {"2020-01", "2023-01"}

    def test_a_sentence_with_no_replacement_verb_is_not_a_break(self):
        got = K.parse_break_sentences([
            "Crude oil, Brent: simple average of Brent, Dubai and WTI, equally weighted, "
            "January 2024."])
        assert got == []

    def test_a_replacement_with_no_date_is_not_filed_under_a_guess(self):
        assert K.parse_break_sentences(["Fishmeal was replaced."]) == []

    def test_a_replacement_with_no_series_is_not_filed_under_a_guess(self):
        assert K.parse_break_sentences(["replaced in January 2024"]) == []

    def test_duplicates_across_cells_collapse(self):
        text = "Beef was replaced in January 2024."
        assert len(K.parse_break_sentences([text, text, text])) == 1

    def test_output_is_sorted_by_month_then_series(self):
        got = K.parse_break_sentences([
            "Fishmeal was replaced in July 2026.",
            "Lamb was replaced in January 2020.",
            "Beef was replaced in January 2024.",
        ])
        assert [b.break_month for b in got] == ["2020-01", "2024-01", "2026-07"]


class TestTheSevenKnownBreaks:
    def test_all_seven_are_declared_with_a_month(self):
        assert len(K.KNOWN_BREAKS) == 7
        for series, month in K.KNOWN_BREAKS:
            assert series and month
            assert len(month) == 7 and month[4] == "-"

    def test_the_parser_recovers_all_seven_from_their_own_wording(self):
        sentences = [
            "Fishmeal was replaced in July 2026.",
            "Beef was replaced in January 2024.",
            "Groundnut oil was replaced in January 2023.",
            "Chicken: the quotation switched from USA to Brazil in September 2021.",
            "Potassium chloride was replaced (Vancouver to Brazil) in January 2020.",
            "Lamb was replaced in January 2020.",
            "Rubber TSR20 replaces RSS3 in the index from 2018.",
        ]
        got = {(b.series.lower(), b.break_month) for b in K.parse_break_sentences(sentences)}
        expected = {(s.lower(), m) for s, m in K.KNOWN_BREAKS}
        assert expected <= got, f"unrecovered: {sorted(expected - got)}"


class TestDeclines:
    def test_an_absent_description_sheet_is_its_OWN_decline(self):
        assert K.break_log_decline([], cells_seen=0) == "description_sheet_absent"

    def test_a_sheet_that_yields_nothing_is_a_COUNTED_decline_not_a_silent_pass(self):
        """'this vintage logs no replacement' and 'the WB's wording moved out from under the regex'
        are NOT distinguishable from here, so the honest answer is a counted decline and a human
        reads one sheet -- never a green run quietly asserting there are no breaks."""
        assert K.break_log_decline([], cells_seen=42) == "no_break_log"

    def test_a_parsed_log_declines_nothing(self):
        got = K.parse_break_sentences(["Beef was replaced in January 2024."])
        assert K.break_log_decline(got, cells_seen=42) is None

    def test_the_two_absences_are_kept_apart(self):
        """Different causes, different fixes: one says the workbook moved, the other says the
        wording did. Collapsing them would send a reader to the wrong place."""
        assert (K.break_log_decline([], cells_seen=0)
                != K.break_log_decline([], cells_seen=1))


class TestBreakRecordsOnARealWorkbook:
    @staticmethod
    def _workbook(cells, *, sheet="Description"):
        import io

        from openpyxl import Workbook
        book = Workbook()
        first = book.active
        first.title = "Monthly Prices"
        first.append(["Month", "Soybean oil"])
        second = book.create_sheet(sheet)
        for cell in cells:
            second.append([cell])
        buf = io.BytesIO()
        book.save(buf)
        return buf.getvalue()

    def test_it_reports_coverage_in_BOTH_directions(self):
        """Neither direction is an error. An older vintage legitimately predates later
        replacements, and a NEW replacement is exactly what the tripwire exists to surface --
        reporting both is what keeps 'we found seven' from being read as 'there are seven'."""
        body = self._workbook([
            "World Bank Commodity Price Data -- Description",
            "Beef was replaced in January 2024.",
            "Coal, Australian was replaced in March 2027.",     # not in KNOWN_BREAKS
        ])
        rec = K.break_records("2027M04", body)
        assert rec["release_ym"] == "2027M04"
        assert rec["n_breaks"] == 2
        assert rec["decline"] is None
        assert "coal, australian@2027-03" in rec["coverage"]["found_not_expected"]
        assert any(x.startswith("fishmeal@") for x in rec["coverage"]["expected_not_found"])

    def test_a_workbook_with_no_description_sheet_declines(self):
        body = self._workbook(["irrelevant"], sheet="Annual Prices")
        rec = K.break_records("2019M04", body)
        assert rec["description_cells"] == 0
        assert rec["decline"] == "description_sheet_absent"
        assert rec["breaks"] == []

    def test_a_description_sheet_with_no_replacement_wording_declines(self):
        body = self._workbook(["World Bank Commodity Price Data", "Units are US dollars."])
        rec = K.break_records("2019M04", body)
        assert rec["description_cells"] == 2
        assert rec["decline"] == "no_break_log"

    def test_the_sheet_is_addressed_by_NAME_with_the_common_spellings_accepted(self):
        for sheet in K.DESCRIPTION_SHEET_CANDIDATES:
            body = self._workbook(["Beef was replaced in January 2024."], sheet=sheet)
            rec = K.break_records("2024M02", body)
            assert rec["n_breaks"] == 1, sheet


@pytest.mark.parametrize("month,expected", [
    ("January 2024", ("2024-01", True)),
    ("Jan 2024", ("2024-01", True)),
    ("September 2021", ("2021-09", True)),
    ("Sept 2021", ("2021-09", True)),
    ("December 1, 2019", ("2019-12", True)),
    ("2018", ("2018-01", False)),
])
def test_month_forms_the_world_bank_actually_writes(month, expected):
    got = K.parse_break_sentences([f"Beef was replaced in {month}."])
    assert len(got) == 1
    assert (got[0].break_month, got[0].month_known) == expected


class TestTheModuleDeclaresItsOwnSCOPE:
    """THE REVIEW'S MINOR, PINNED SO IT CANNOT DRIFT BACK INTO AN IMPLIED GUARANTEE.

    The design names the parsed break log as THE tripwire for the seven same-name/different-series
    replacements. No producer calls it and no object lands, so the tripwire is unshipped. The remedy
    taken here is the declaration, not the wiring: adding an S3 write to the LIVE scheduled bronze
    producer is its own change with its own gate. What this pin protects is that the module never
    again READS as if the guard were live.
    """

    def test_the_docstring_says_measurement_only_and_names_the_docket(self):
        import inspect
        doc = inspect.getdoc(K) or ""
        assert "MEASUREMENT-ONLY TODAY" in doc
        assert "NO PRODUCER CALLS THIS MODULE" in doc
        assert "DOCKET:" in doc

    def test_nothing_in_jobs_imports_it_yet_and_the_docstring_agrees(self):
        """If a producer DOES start importing it, this test fails and the docstring must be
        rewritten in the same change -- which is the point: the claim and the wiring move together."""
        from pathlib import Path
        repo = Path(__file__).resolve().parents[2]
        importers = [p.name for p in sorted((repo / "jobs").rglob("*.py"))
                     if "pink_sheet_breaks" in p.read_text(encoding="utf-8")]
        assert importers == [], (
            "a job now references pink_sheet_breaks -- update the module docstring's "
            "MEASUREMENT-ONLY section in the same change that wires it")

    def test_the_seven_known_breaks_are_still_the_documented_record(self):
        assert len(K.KNOWN_BREAKS) == 7
        assert all(series and month for series, month in K.KNOWN_BREAKS)
