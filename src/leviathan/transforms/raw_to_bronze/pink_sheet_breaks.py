"""The Pink Sheet's SERIES-REPLACEMENT log, parsed out of the workbook's Description sheet.

WHY THIS EXISTS -- THE STRING-IDENTITY FAILURE IN ITS PUREST FORM
-----------------------------------------------------------------
The estate's canonical remedy for a renamed series is "key on the source's STABLE CODE, and treat
the name as a logged tripwire" (the FCOJ COT incident: 1,049 weeks lost to a rename).  THAT REMEDY
CANNOT BE APPLIED HERE.  The World Bank publishes no usable code row: its own codes
(``CRUDE_PETRO``, ``CRUDE_BRENT``) appear in exactly ONE of the six measured vintages (raw 2026M05,
row 7), so a code-keyed join would silently narrow to that one workbook.

And the failure mode here is the mirror image of a rename: the key NEVER changes, but the THING it
names is REPLACED.  The 71 header strings were byte-identical from Jan-2025 to Sep-2026, while the
Description sheet logs SEVEN same-name/different-series replacements over that same history:

    Fishmeal                              July 2026
    Beef                                  January 2024
    Groundnut oil                         January 2023
    Chicken (USA -> Brazil)               September 2021
    Potassium chloride (Vancouver -> Brazil)  January 2020
    Lamb                                  January 2020
    Rubber TSR20 replaces RSS3 in the index   2018

A consumer that spans one of those months is joining two different physical commodities under one
column name, and NOTHING in the header, the values or the row count says so.  So THE PARSED BREAK
LOG IS THE TRIPWIRE: it lands beside bronze, no consumer may span a break without naming it, and a
vintage whose Description sheet yields NO log is a COUNTED DECLINE -- never a silent pass, because
"no breaks found" and "the sheet moved and we found nothing" look identical from the outside.

MEASUREMENT-ONLY TODAY.  SAY IT PLAINLY RATHER THAN LET THE PARAGRAPH ABOVE BE READ AS SHIPPED.
------------------------------------------------------------------------------------------------
NO PRODUCER CALLS THIS MODULE AND NO BREAK LOG OBJECT LANDS.  Its only importers are its own test
suite and a runbook smoke line.  The paragraph above describes the tripwire the design ASKED for;
what exists today is the parser, its expectations and its refusal registry -- a reader you can point
at a workbook, not a guard anything is behind.

That is a deliberate scope call, not an oversight.  Wiring it means adding an S3 write to
``jobs/batch/pink_sheet_task.py``, a LIVE scheduled producer on the served latest-only chain, whose
untouchedness is the safety argument of the whole vintages wave (``test_pink_sheet_prefix_fence.py``
pins that both scheduled jobs stay as they are).  A break-log write belongs to its own change with
its own gate, prefix classification and rollback.

SO, UNTIL THAT CHANGE LANDS, THE HONEST STATEMENT OF WHAT THIS BUYS:
  * a consumer that spans one of the seven months above is STILL unguarded at run time;
  * the seven are documented HERE, in :data:`KNOWN_BREAKS`, and that is the only place a reader can
    find them without opening a workbook;
  * :func:`break_log_decline` names a short or empty parse so the FIRST live run over a real
    workbook produces a finding rather than a shrug.
DOCKET: call :func:`parse_breaks` from the bronze producer and land
``bronze/production/source=world_bank_pink_sheet/release={R}/_break_log.json``, with its own entry
in ``configs/silver/prefix_classification.yaml`` -- the same shape the vintages ``_run_log.json``
takes.

WHAT IS MEASURED AND WHAT IS NOT, SAID PLAINLY
----------------------------------------------
The seven breaks above are measured -- they are read off the workbooks.  The Description sheet's
CELL LAYOUT is NOT measured from the seat that wrote this module (no workbook was reachable), so the
parser deliberately makes no assumption about which column or row a sentence sits in: it walks EVERY
cell of the sheet, sentence by sentence, and matches on the sentence's own wording.  The first live
run over a real workbook is what turns the expected seven into an observed seven; until then
:func:`parse_breaks` returning fewer than seven on a modern workbook is itself the finding, and
:func:`break_log_decline` names it.
"""
from __future__ import annotations

import io
import re
from typing import Any, Iterable, NamedTuple, Optional

# The Description sheet is addressed by NAME, with the common spellings accepted in order. Reading
# sheet 0 positionally is the class of bug the shipped extractor already avoids for 'Monthly Prices'.
DESCRIPTION_SHEET_CANDIDATES: tuple[str, ...] = ("Description", "Descriptions", "Notes")

# THE WRITTEN REFUSAL (SILVER-F091 / INV-10): a universe claim owes a statement of what it LEAVES
# OUT. The candidate tuple above is a claim about which sheet carries the replacement log, so this
# names the sheet this module deliberately does NOT read and why.
#
# IT IS INCOMPLETE AND SAYS SO. The workbook's full sheet list was not reachable from the seat that
# wrote this module, so the only entry here is the one sheet this estate's own code names. Read it
# as "at least this is refused", never as "this is the whole set" -- the lint's own fence says
# `covered` means a written refusal EXISTS, not that it is complete. Any sheet name outside
# DESCRIPTION_SHEET_CANDIDATES is an ABSENCE at read time and is counted as
# ``description_sheet_absent``, which is what keeps an unlisted sheet from passing silently.
_REFUSED_SHEETS: dict[str, str] = {
    "Monthly Prices": ("the monthly price grid -- parsed by raw_to_bronze.world_bank_pink_sheet "
                       "(_SHEET_NAME) for VALUES, and it carries no replacement prose, so a break "
                       "log read from it would be empty for a reason that has nothing to do with "
                       "the vintage"),
}

# The seven replacements the six measured workbooks log, as (series, break month). This is an
# EXPECTATION used to report coverage, never a substitute for parsing: a workbook that logs an
# eighth must surface it, and one that logs six must be counted short.
KNOWN_BREAKS: tuple[tuple[str, str], ...] = (
    ("Fishmeal", "2026-07"),
    ("Beef", "2024-01"),
    ("Groundnut oil", "2023-01"),
    ("Chicken", "2021-09"),
    ("Potassium chloride", "2020-01"),
    ("Lamb", "2020-01"),
    ("Rubber TSR20", "2018-01"),
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# A REPLACEMENT SENTENCE, in the World Bank's own vocabulary. Matched on the VERB, not on a fixed
# column: "replaced", "replaces", "series was changed to", "switched from ... to", "discontinued".
_REPLACEMENT_RX = re.compile(
    r"\b(replac(?:e|es|ed|ement)|superseded|switched|changed\s+(?:to|from)|discontinued|"
    r"revised\s+series|new\s+series)\b",
    re.IGNORECASE,
)
# 'January 2024', 'Jan 2024', 'January 1, 2024', '2018'. A YEAR ALONE is accepted and reported as
# the January of that year with month_known=False -- the Rubber TSR20 entry is dated by year only,
# and inventing a month for it would be a fabricated precision.
_MONTH_YEAR_RX = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+(?:\d{1,2},\s*)?(\d{4})\b",
    re.IGNORECASE,
)
_YEAR_RX = re.compile(r"\b(19|20)\d{2}\b")

# Sentence splitter: the Description cells are prose, and one cell can carry several statements.
_SENTENCE_SPLIT_RX = re.compile(r"(?<=[.;])\s+|\n+")

# The list marker a Description bullet may carry, and the characters trimmed off a series name. The
# BULLET and the EN/EM DASHES are written as \u ESCAPES, never as literals: this estate is ASCII-only
# in source, and the World Bank's prose really does use all three -- so the characters must be
# matched while the FILE stays ASCII.
_LIST_MARKER_RX = re.compile("^\\s*[-*\\u2022\\d.)\\]]+\\s*")
_TRIM_CHARS = " .,-\u2013\u2014"


class SeriesBreak(NamedTuple):
    """One logged replacement.

    Attributes:
        series:      the series name as the workbook writes it (never a governed silver slug -- the
                     mapping to a silver column is a consumer's decision and is made where the
                     consumer can be held to it).
        break_month: ``'YYYY-MM'``. When the log dates a break by YEAR ONLY, this is that year's
                     January and ``month_known`` is False.
        month_known: whether the workbook actually named a month.
        sentence:    the WB's own sentence, VERBATIM. The verbatim text is the point: a paraphrase
                     of a provenance note is a new claim.
    """

    series: str
    break_month: str
    month_known: bool
    sentence: str


def _sheet_cells(xlsx_bytes: bytes) -> list[str]:
    """Every non-empty cell of the Description sheet, as strings, in row-major order.

    Returns ``[]`` when the workbook has no sheet under any of
    :data:`DESCRIPTION_SHEET_CANDIDATES` -- an ABSENCE the caller must count, not an exception it
    can swallow.
    """
    import pandas as pd  # local import: this module stays importable without the pandas stack

    for sheet in DESCRIPTION_SHEET_CANDIDATES:
        try:
            frame = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name=sheet, header=None,
                                  engine="openpyxl")
        except Exception:  # noqa: BLE001 -- a missing sheet name is an ABSENCE, tried in order
            continue
        out: list[str] = []
        for row in frame.itertuples(index=False):
            for cell in row:
                text = "" if cell is None else str(cell).strip()
                if text and text.lower() != "nan":
                    out.append(text)
        return out
    return []


def _series_from_sentence(sentence: str) -> Optional[str]:
    """The series a replacement sentence is about: the leading noun phrase before the verb.

    The World Bank writes these as '<Series>: ... replaced ...' or '<Series> was replaced ...', so
    the text left of the colon (or left of the matched verb) is the name. Returning None when there
    is nothing to the left is deliberate -- a break with no series is not a usable tripwire and the
    caller counts it as unparsed rather than filing it under a guess.
    """
    head = sentence.split(":", 1)[0] if ":" in sentence[:80] else sentence
    match = _REPLACEMENT_RX.search(head)
    if match:
        head = head[: match.start()]
    head = _LIST_MARKER_RX.sub("", head).strip(_TRIM_CHARS)
    # Cut a trailing auxiliary so 'Beef was' reads 'Beef', then trim AGAIN: the auxiliary can sit
    # behind a dash ("Beef -- was replaced ..."), and trimming only before the cut leaves the dash
    # welded to the name, which would then never match a KNOWN_BREAKS entry.
    head = re.sub(r"\s+(?:was|were|is|are|has|have|had|series)$", "", head, flags=re.IGNORECASE)
    return head.strip(_TRIM_CHARS) or None


def _month_from_sentence(sentence: str) -> Optional[tuple[str, bool]]:
    """``('YYYY-MM', month_known)`` for the date a replacement sentence names, or None."""
    match = _MONTH_YEAR_RX.search(sentence)
    if match:
        month = _MONTHS[match.group(1).lower()]
        return f"{int(match.group(2)):04d}-{month:02d}", True
    year = _YEAR_RX.search(sentence)
    if year:
        return f"{int(year.group(0)):04d}-01", False
    return None


def parse_break_sentences(sentences: Iterable[str]) -> list[SeriesBreak]:
    """The replacement log implied by a stream of sentences. Pure; no workbook, no network."""
    out: list[SeriesBreak] = []
    seen: set[tuple[str, str]] = set()
    for raw in sentences:
        for sentence in _SENTENCE_SPLIT_RX.split(str(raw)):
            sentence = sentence.strip()
            if not sentence or not _REPLACEMENT_RX.search(sentence):
                continue
            when = _month_from_sentence(sentence)
            series = _series_from_sentence(sentence)
            if when is None or not series:
                continue
            key = (series.lower(), when[0])
            if key in seen:
                continue
            seen.add(key)
            out.append(SeriesBreak(series=series, break_month=when[0], month_known=when[1],
                                   sentence=sentence))
    return sorted(out, key=lambda b: (b.break_month, b.series.lower()))


def parse_breaks(xlsx_bytes: bytes) -> list[SeriesBreak]:
    """The replacement log a Pink Sheet workbook's Description sheet carries."""
    return parse_break_sentences(_sheet_cells(xlsx_bytes))


def break_log_decline(breaks: list[SeriesBreak], cells_seen: int) -> Optional[str]:
    """``None`` when the parsed log is usable, else WHY this vintage's log is a counted decline.

    Two distinct absences, kept apart because they have different causes and different fixes:

      * ``description_sheet_absent`` -- no sheet under any of the candidate names. The workbook
        moved or the era predates the sheet; the era rule needs re-deriving.
      * ``no_break_log`` -- the sheet is there and says nothing this parser recognises. Either the
        vintage genuinely logs no replacement, or the WB's wording moved out from under
        ``_REPLACEMENT_RX``. THE TWO ARE NOT DISTINGUISHABLE FROM HERE, so the honest answer is a
        counted decline and a human reads one sheet, rather than a green run that quietly asserts
        "this vintage has no breaks".
    """
    if cells_seen == 0:
        return "description_sheet_absent"
    if not breaks:
        return "no_break_log"
    return None


def break_records(release_ym: str, xlsx_bytes: bytes) -> dict[str, Any]:
    """The landable record for one release: its breaks, its decline (if any), and its coverage.

    ``coverage`` compares the parsed log against :data:`KNOWN_BREAKS` and reports BOTH directions --
    which expected breaks this vintage's log did not yield, and which parsed breaks were not
    expected. Neither direction is an error: an older vintage legitimately predates later
    replacements, and a NEW replacement is exactly what the tripwire exists to surface. Reporting
    both is what keeps 'we found seven' from being mistaken for 'there are seven'.
    """
    cells = _sheet_cells(xlsx_bytes)
    breaks = parse_break_sentences(cells)
    parsed = {(b.series.lower(), b.break_month) for b in breaks}
    expected = {(s.lower(), m) for s, m in KNOWN_BREAKS}
    return {
        "release_ym": release_ym,
        "description_cells": len(cells),
        "breaks": [b._asdict() for b in breaks],
        "n_breaks": len(breaks),
        "decline": break_log_decline(breaks, len(cells)),
        "coverage": {
            "expected_not_found": sorted(f"{s}@{m}" for s, m in expected - parsed),
            "found_not_expected": sorted(f"{s}@{m}" for s, m in parsed - expected),
        },
    }
