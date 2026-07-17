"""Unit tests for CFTC disaggregated COT parsing under the 2026 headerless change.

CFTC dropped the header row from the live weekly ``newcot`` TXT files
(f_disagg.txt / c_disagg.txt) in 2026 — line 1 is now the first *data* row.  The
excerpts below are REAL rows lifted verbatim from the live futures-only file on
2026-07-17 (report_date 2026-07-07).  Two concerns are covered:

  1. jobs.ingest.fetch_cftc_cot._validate_txt must accept the headerless weekly
     layout while still failing closed on wrong payloads (and must keep accepting
     the legacy headered backfill layout).
  2. leviathan.transforms.raw_to_bronze.cftc_cot.parse_cot_txt must stitch the
     canonical header back on and produce byte-for-byte the same bronze it would
     from a headered file — proving no column misalignment.
"""
from __future__ import annotations

import pytest

from jobs.ingest import fetch_cftc_cot as fetcher
from leviathan.transforms.raw_to_bronze.cftc_cot import (
    _CANONICAL_COLUMNS,
    _CANONICAL_HEADER,
    _HEADER_MARKER,
    _ensure_header,
    parse_cot_txt,
)

# --- REAL headerless data rows (verbatim from the live f_disagg.txt) ---------
_WHEAT_ROW = (
    '"WHEAT-SRW - CHICAGO BOARD OF TRADE",260707,2026-07-07,001602,CBT ,00,001 ,'
    '  412570,   69423,   82252,   81009,   17286,   17328,   73719,  134151,'
    '   75664,   37409,   26707,   24740,  379292,  378128,   33278,   34442,'
    '  392043,   68280,   75004,   76848,   17302,   16766,   66557,  134926,'
    '   71211,   40318,   25929,   20047,  360027,  361185,   32016,   30858,'
    '   20527,    1143,    7248,    4710,     533,      13,   10926,    2989,'
    '     689,     206,    3893,    1578,   19265,   16943,    1262,    3584,'
    '    5847,   -2100,    4233,   -1828,    -761,    1290,    4617,   -2512,'
    '    1977,   -2922,   -1067,    1879,    2913,    5039,    2934,     808,'
    '  100.0,   16.8,   19.9,   19.6,    4.2,    4.2,   17.9,   32.5,   18.3,'
    '    9.1,    6.5,    6.0,   91.9,   91.7,    8.1,    8.3,  100.0,   17.4,'
    '   19.1,   19.6,    4.4,    4.3,   17.0,   34.4,   18.2,   10.3,    6.6,'
    '    5.1,   91.8,   92.1,    8.2,    7.9,  100.0,    5.6,   35.3,   22.9,'
    '    2.6,    0.1,   53.2,   14.6,    3.4,    1.0,   19.0,    7.7,   93.9,'
    '   82.5,    6.1,   17.5,    374,     69,     84,     25,      8,     13,'
    '     57,     64,     67,     68,     33,     47,    288,    260,    373,'
    '     69,     82,     25,      8,     12,     56,     65,     67,     73,'
    '     30,     45,    286,    256,    126,     14,     58,     13,      4,.,'
    '     10,     10,      4,.,     21,     10,     52,     98,    13.2,    13.5,'
    '    22.3,    23.0,    10.7,    10.7,    17.2,    17.1,    13.8,    14.2,'
    '    22.5,    23.9,    10.5,    11.8,    16.8,    18.4,    53.7,    22.2,'
    '    65.2,    34.9,    53.7,    18.8,    63.4,    30.7,'
    '"(CONTRACTS OF 5,000 BUSHELS)","001602","CBT ","001 ","A10","FutOnly"'
)

_CORN_ROW = (
    '"CORN - CHICAGO BOARD OF TRADE",260707,2026-07-07,002602,CBT ,00,002 ,'
    ' 1711613,  339364,  734442,  347528,   20104,   13901,  287447,  302446,'
    '  232157,  190706,   74727,  159030, 1570133, 1536807,  141480,  174806,'
    '  641701,  135555,  173115,  130580,   10157,    1345,  178001,  268656,'
    '   25301,  115615,  120831,    1368,  587765,  600773,   53936,   40928,'
    ' 1069912,  203809,  561327,  226235,   19234,    3269,  244256,  168600,'
    '   72046,  189851,   68656,   42902,  982368,  936034,   87544,  133878,'
    '  -20425,  -23049,   18988,    9111,    -151,   -1047,   -5844,  -57841,'
    '   -1245,   -6120,    9074,   12836,  -15358,  -19386,   -5067,   -1039,'
    '  100.0,   19.8,   42.9,   20.3,    1.2,    0.8,   16.8,   17.7,   13.6,'
    '   11.1,    4.4,    9.3,   91.7,   89.8,    8.3,   10.2,  100.0,   21.1,'
    '   27.0,   20.3,    1.6,    0.2,   27.7,   41.9,    3.9,   18.0,   18.8,'
    '    0.2,   91.6,   93.6,    8.4,    6.4,  100.0,   19.0,   52.5,   21.1,'
    '    1.8,    0.3,   22.8,   15.8,    6.7,   17.7,    6.4,    4.0,   91.8,'
    '   87.5,    8.2,   12.5,    834,    284,    327,     35,      8,     19,'
    '     85,     69,     78,    105,     79,     79,    600,    583,    681,'
    '    205,    225,     27,      8,.,     42,     69,     26,     90,     62,'
    '      8,    387,    376,    743,    204,    310,     34,      6,     12,'
    '     78,     50,     47,     84,     81,     49,    451,    504,    11.3,'
    '    10.5,    19.4,    18.2,     9.5,     7.7,    16.3,    13.7,    20.5,'
    '    21.3,    31.6,    31.8,    19.1,    21.3,    30.1,    31.5,    14.8,'
    '    11.7,    23.1,    20.7,    14.1,    11.3,    22.0,    19.1,'
    '"(CONTRACTS OF 5,000 BUSHELS)","002602","CBT ","002 ","A10","FutOnly"'
)

# Two-row headerless payload as it lands in raw S3 (bytes, LF-terminated).
_HEADERLESS_EXCERPT = (_WHEAT_ROW + "\n" + _CORN_ROW + "\n").encode("utf-8")
# The same two rows with the canonical header stitched on (legacy backfill form).
_HEADERED_EXCERPT = (_CANONICAL_HEADER + "\n" + _WHEAT_ROW + "\n" + _CORN_ROW + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Fixture sanity — a transcription slip in the verbatim rows fails loudly here.
# ---------------------------------------------------------------------------

def test_fixture_rows_have_the_fixed_191_field_width() -> None:
    import csv

    for row in (_WHEAT_ROW, _CORN_ROW):
        assert len(next(csv.reader([row]))) == fetcher._EXPECTED_FIELD_COUNT


# ---------------------------------------------------------------------------
# Bronze parser: header stitching
# ---------------------------------------------------------------------------

def test_ensure_header_prepends_for_headerless() -> None:
    out = _ensure_header(_HEADERLESS_EXCERPT)
    first_line = out.split(b"\n", 1)[0].decode()
    assert first_line.startswith(_HEADER_MARKER)
    assert out.endswith(_HEADERLESS_EXCERPT)  # original bytes preserved after header


def test_ensure_header_passthrough_for_headered() -> None:
    assert _ensure_header(_HEADERED_EXCERPT) is _HEADERED_EXCERPT


def test_ensure_header_fails_closed_on_wrong_field_count() -> None:
    bad = b'"CORN - CHICAGO BOARD OF TRADE",002602,10,20\n'  # 4 fields, not 191
    with pytest.raises(ValueError, match="expected 191"):
        _ensure_header(bad)


def test_canonical_header_covers_kept_columns_at_stable_positions() -> None:
    # The bronze parser selects by name; these must exist for the stitch to work.
    assert _CANONICAL_COLUMNS[0] == "Market_and_Exchange_Names"
    assert _CANONICAL_COLUMNS[2] == "Report_Date_as_YYYY-MM-DD"
    assert _CANONICAL_COLUMNS[7] == "Open_Interest_All"
    assert _CANONICAL_COLUMNS[13] == "M_Money_Positions_Long_All"
    assert _CANONICAL_COLUMNS[14] == "M_Money_Positions_Short_All"
    assert _CANONICAL_COLUMNS[190] == "FutOnly_or_Combined"


# ---------------------------------------------------------------------------
# Bronze parser: end-to-end column alignment (the corruption guard)
# ---------------------------------------------------------------------------

def test_parse_headerless_produces_correctly_aligned_bronze() -> None:
    df = parse_cot_txt(_HEADERLESS_EXCERPT, "weekly_2026-07-07")
    by_slug = {r["leviathan_slug"]: r for _, r in df.iterrows()}

    assert set(by_slug) == {"soft_red_winter_wheat_cbot", "corn_cbot"}

    wheat = by_slug["soft_red_winter_wheat_cbot"]
    assert wheat["report_date"] == "2026-07-07"
    # NOTE: cftc_code loses its leading zeros (001602 -> "1602") because pandas
    # infers CFTC_Contract_Market_Code as int64. This is PRE-EXISTING parser
    # behaviour, identical for headered backfill files (see the parity test
    # below), and out of scope for the headerless fetch fix.
    assert wheat["cftc_code"] == "1602"
    assert int(wheat["open_interest"]) == 412570
    assert int(wheat["mm_long"]) == 73719
    assert int(wheat["mm_short"]) == 134151
    assert int(wheat["mm_spread"]) == 75664
    assert int(wheat["mm_net"]) == -60432          # 73719 - 134151
    assert wheat["source"] == "cftc_cot"

    corn = by_slug["corn_cbot"]
    assert corn["cftc_code"] == "2602"             # 002602 int-coerced (pre-existing)
    assert int(corn["open_interest"]) == 1711613
    assert int(corn["mm_long"]) == 287447
    assert int(corn["mm_short"]) == 302446
    assert int(corn["mm_net"]) == -14999           # 287447 - 302446


def test_headerless_and_headered_yield_identical_bronze() -> None:
    # Backfill (headered) and weekly (headerless) must reduce to the same bronze.
    hl = parse_cot_txt(_HEADERLESS_EXCERPT, "hl")
    hd = parse_cot_txt(_HEADERED_EXCERPT, "hd")
    from pandas.testing import assert_frame_equal

    assert_frame_equal(hl, hd)


# ---------------------------------------------------------------------------
# Fetcher validation: accept both layouts, fail closed on wrong payloads
# ---------------------------------------------------------------------------

def test_validate_accepts_headerless_weekly() -> None:
    fetcher._validate_txt(_HEADERLESS_EXCERPT, "f_disagg.txt")  # no raise


def test_validate_accepts_headered_backfill() -> None:
    fetcher._validate_txt(_HEADERED_EXCERPT, "fut_disagg_2024.txt")  # no raise


def test_validate_rejects_html_error_page() -> None:
    html = b"<!DOCTYPE html>\n<html><head><title>404</title></head><body>Not Found</body></html>"
    with pytest.raises(RuntimeError):
        fetcher._validate_txt(html, "f_disagg.txt")


def test_validate_rejects_wrong_field_count() -> None:
    # Looks like a market row but truncated to 3 fields (and even carries the
    # sentinel) — must still fail closed on the structural field-count check.
    bad = b'"CORN - CHICAGO BOARD OF TRADE",002602,123\n'
    with pytest.raises(RuntimeError, match="191"):
        fetcher._validate_txt(bad, "f_disagg.txt")


def test_validate_rejects_non_market_first_field() -> None:
    # 191 fields but the first is not a "<COMMODITY> - <EXCHANGE>" market name.
    row = ",".join(["notamarket"] + ["002602"] + ["0"] * 189) + "\n"
    with pytest.raises(RuntimeError, match="market name"):
        fetcher._validate_txt(row.encode("utf-8"), "f_disagg.txt")
