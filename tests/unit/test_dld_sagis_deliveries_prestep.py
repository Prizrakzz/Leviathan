"""D-LD TRANCHE 2 -- the PRODUCER-SIDE pre-step for silver_sagis_weekly_deliveries.

This file pins the producer change that unblocks the deliveries numbers card. It is deliberately
separate from (and lands BEFORE) the card's own test block: the card, its tables.yaml entry and the
F010 PIT trio are a later change, and this one must be green on its own -- the same shape the
silver_mpoc_exports_by_country pre-step took.

WHAT IS PINNED, AND WHY EACH PIN IS LOAD-BEARING
------------------------------------------------
1. ``week_ending_date`` -- the derived PIT anchor. The table shipped with NO date column of any
   kind: no vintage stamp, no ingest stamp, no year/month pair. ``TableSpec.knowledge_col()`` had
   nothing to return and ``query._guard`` raised before any SQL, so a card would have been a served
   table that refused 100% of its lookups.

   THE NEGATIVE HALF IS THE POINT: the one column that LOOKS like an anchor, ``week_ending``, is a
   bilingual English/Afrikaans date-RANGE LABEL -- ``'1 - 7 Oct/Okt'``, ``'29 Apr - 05 May 2006'``,
   ``'24/02 - 02/03/2018'``, ``'27/04-03/05/2013'`` -- and 0 of the 3,007 canonical rows are ISO.
   Declaring it ``date_col`` would pass the DDL lint and produce a LIVE PIT HOLE: the guard compiles
   to ``CAST(week_ending AS varchar) <= '<asof>'`` and under lexicographic comparison a label
   beginning ``'1 '`` / ``'2 '`` / ``'0'`` / ``'3'`` sorts below the ISO literal, so essentially
   every row in the table satisfies every as-of cutoff. Present, green and vacuous.
   ``test_the_free_text_label_can_never_be_the_anchor`` is what stops that shortcut coming back.

2. The parser widening, and its bound. ``parse_week_ending_end`` required a LETTER month token, and
   the deliveries files publish a purely numeric end from 2013-14 onward -- MEASURED against the
   canonical parquet, that is 763/3,007 = 25.4% coverage as-is and 3,007/3,007 = 100.0% with the
   ``dd/mm[/yyyy]`` fallback. The fallback is reached ONLY when the letter branch resolved nothing,
   which is why the sibling cannot move: ``silver_sagis_weekly_exports`` parses 1,204/1,204 on the
   letter branch alone and never enters the new code at all. Section 4 pins that no-regression
   directly, format by format.

AWS-free: the S3 coverage measurement above is reproduced here on the real era formats.
"""
from __future__ import annotations

import datetime as dt
import io
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.silver.flat_producer import encode_parquet, pa_schema_from_contract
from leviathan.transforms.bronze_to_silver.sagis_common import build_snapshot
from leviathan.transforms.bronze_to_silver.sagis_deliveries import (
    SILVER_ARROW_SCHEMA,
    DeliveryWeekRecord,
    _SILVER_COLUMNS,
    build_deliveries_silver,
)
from leviathan.transforms.bronze_to_silver.sagis_weekly_exports import (
    derive_week_ending_dates,
    parse_week_ending_end,
)

TABLE = "silver_sagis_weekly_deliveries"
_REPO = Path(__file__).resolve().parents[2]
_DDL = _REPO / "sql" / "athena" / "ddl" / f"{TABLE}.sql"


def _dt(y, m, d) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


def _snap(filename, published_at, crop="maize"):
    return build_snapshot(
        s3_key=f"raw/production/source=sagis_weekly/dataset=producer_deliveries/crop={crop}/{filename}",
        filename=filename, dataset="producer_deliveries", crop=crop, published_at=published_at,
    )


def _rec(snap, week, total=None, label=None):
    return DeliveryWeekRecord(
        snapshot=snap, season=snap.season, crop_label=snap.crop, week_number=week,
        week_ending_label=label, prog_total_mt=total,
    )


def _by_week(df, crop="maize") -> dict:
    return {int(r.week_number): r for r in df.itertuples(index=False) if r.crop == crop}


# =============================================================================================
# 1. The four measured label eras parse -- this is the 25.4% -> 100.0% widening.
# =============================================================================================
@pytest.mark.parametrize("label,expected", [
    # ERA A -- letter month, no year (the earliest maize/wheat files). Already parsed.
    ("1 - 7 Oct/Okt", (7, 10, None)),
    ("29 Oct/Okt - 4 Nov", (4, 11, None)),
    # ERA B -- letter month WITH a year, incl. the Dec->Jan cross-year week. Already parsed.
    ("31 Dec/Des - 6 Jan 2006", (6, 1, 2006)),
    ("29 Apr - 05 May 2006", (5, 5, 2006)),
    # ERA C/D -- PURELY NUMERIC dd/mm/yyyy, spaced and unspaced. These are the 2,244 rows that
    # returned None before the widening: 2013-14 onward, i.e. the whole modern table.
    ("24/02 - 02/03/2018", (2, 3, 2018)),
    ("27/04-03/05/2013", (3, 5, 2013)),
    ("01/08 - 07/08/2026", (7, 8, 2026)),
])
def test_every_measured_deliveries_era_now_parses(label, expected):
    assert parse_week_ending_end(label) == expected


def test_the_newest_published_week_lands_on_its_friday():
    """The data's own edge is the day-order proof. '01/08 - 07/08/2026' is dd/mm: the week ending
    FRIDAY 7 August 2026. Read as mm/dd it would be 8 July -- a month wrong, on a WEEKDAY, which is
    exactly the kind of error a plausible-looking date hides. 3,005 of 3,007 derived dates are
    Fridays, and the card's +5d lag is reasoned against that."""
    day, month, year = parse_week_ending_end("01/08 - 07/08/2026")
    assert dt.date(year, month, day) == dt.date(2026, 8, 7)
    assert dt.date(year, month, day).weekday() == 4          # Friday


def test_a_numeric_end_without_a_year_defers_to_the_season_carry():
    """Not every numeric label carries the year; the group-level carry-forward supplies it, exactly
    as it does for the letter-month era."""
    assert parse_week_ending_end("24/02 - 02/03") == (2, 3, None)
    # maize 2013-14: week 1 carries the year, the weeks after it do not -- the carry supplies it.
    got = derive_week_ending_dates("2013-14", [(1, "29/04 - 03/05/2013"), (2, "06/05 - 10/05")])
    assert got[1] == dt.date(2013, 5, 3)
    assert got[2] == dt.date(2013, 5, 10)


def test_the_dec_to_jan_wrap_still_bumps_the_year_on_numeric_labels():
    """The holiday-shutdown boundary is where a mis-carried year would be least visible. Month
    DECREASE is the wrap signal and it is format-agnostic."""
    got = derive_week_ending_dates("2017-18", [
        (40, "18/12 - 22/12/2017"), (41, "01/01 - 05/01/2018"), (42, "08/01 - 12/01"),
    ])
    assert got[40] == dt.date(2017, 12, 22)
    assert got[41] == dt.date(2018, 1, 5)
    assert got[42] == dt.date(2018, 1, 12)


def test_an_iso_label_resolves_instead_of_going_dark():
    """``sagis_deliveries.canonical_week_ending`` emits 'YYYY-MM-DD' whenever the source sheet
    carried a real date cell -- the row with the BEST source date. Before the widening that was the
    one shape with NO anchor, because the range splitter tore it at its first hyphen."""
    assert parse_week_ending_end("2020-11-06") == (6, 11, 2020)


@pytest.mark.parametrize("label", [
    "32/01/2018",       # impossible day
    "07/13/2026",       # month out of range: mm/dd order is REFUSED, never swapped to force a parse
    "07//08/2026",
    "week 12",
    "-",
])
def test_an_unparseable_or_ambiguous_label_stays_null(label):
    """Fail-soft, and deliberately so: a null week_ending_date drops the row from every as-of
    window (``null <= asof`` is UNKNOWN), which is honest. A guessed date would be cited."""
    assert parse_week_ending_end(label) is None


# =============================================================================================
# 2. The producer emits the anchor.
# =============================================================================================
def test_silver_columns_gained_the_anchor_and_kept_the_original_order():
    """APPENDED, never re-ordered: the nine original columns keep their declaration order so the
    F010 physical_columns list is an append and the Glue migration is a plain ADD COLUMNS."""
    assert _SILVER_COLUMNS == [
        "season", "crop", "week_number", "week_ending", "prog_total_mt", "prior_prog_total_mt",
        "pct_of_prior_yr", "z_vs_3yr_avg", "source", "week_ending_date",
    ]
    assert [f.name for f in SILVER_ARROW_SCHEMA] == _SILVER_COLUMNS
    assert SILVER_ARROW_SCHEMA.field("week_ending_date").type == pa.date32()


def test_the_anchor_is_a_real_date_object_on_the_week_end():
    """Held as a python ``datetime.date`` so the flat publisher encodes date32[day] -- never a
    string, which would sort lexically and mis-compare at window edges."""
    snap = _snap("ProdProgressive-Mielies_2017_18_Week02.xlsx", _dt(2018, 3, 9))
    df = build_deliveries_silver([
        _rec(snap, 1, 1000.0, "17/02 - 23/02/2018"),
        _rec(snap, 2, 2500.0, "24/02 - 02/03/2018"),
    ])
    rows = _by_week(df)
    assert rows[1].week_ending_date == dt.date(2018, 2, 23)
    assert rows[2].week_ending_date == dt.date(2018, 3, 2)
    assert all(type(v) is dt.date for v in df["week_ending_date"])


def test_the_anchor_is_the_week_end_not_a_publication_guess():
    """SAGIS posts the cumulative file some days AFTER the week closes, but the DATA stamp stays on
    the week's own last day: the publication guess lives in the card's publication_lag_days (+5d),
    where it is auditable and tunable, not baked irreversibly into the row."""
    snap = _snap("ProdProgressive-Mielies_2026_27_Week15.xlsx", _dt(2026, 8, 14))
    df = build_deliveries_silver([_rec(snap, 15, 9_000_000.0, "01/08 - 07/08/2026")])
    assert set(df["week_ending_date"]) == {dt.date(2026, 8, 7)}


def test_each_crop_carries_its_own_season_calendar_and_its_own_anchor():
    """Four crops on three season calendars (maize early May, wheat early October, soybeans and
    sunflower late February). week_number is NOT comparable across crops, so the derivation runs
    per (season, crop) group -- a shared carry would smear one crop's year onto another's."""
    maize = _snap("ProdProgressive-Mielies_2025_26_Week01.xlsx", _dt(2025, 5, 9), crop="maize")
    wheat = _snap("ProdProgressive-Koring_2025_26_Week01.xlsx", _dt(2025, 10, 10), crop="wheat")
    df = build_deliveries_silver([
        _rec(maize, 1, 100.0, "28/04 - 02/05/2025"),
        _rec(wheat, 1, 50.0, "29/09 - 03/10/2025"),
    ])
    assert _by_week(df, "maize")[1].week_ending_date == dt.date(2025, 5, 2)
    assert _by_week(df, "wheat")[1].week_ending_date == dt.date(2025, 10, 3)


def test_an_unlabelled_week_yields_a_null_anchor_and_does_not_break_the_carry():
    """A grade-only week can reach selection with no label at all. It must produce an honest null,
    never a crash and never a carried-forward neighbour's date."""
    snap = _snap("ProdProgressive-Mielies_2017_18_Week03.xlsx", _dt(2018, 3, 16))
    df = build_deliveries_silver([
        _rec(snap, 1, 1000.0, "17/02 - 23/02/2018"),
        _rec(snap, 2, 2000.0, None),
        _rec(snap, 3, 3000.0, "03/03 - 09/03"),
    ])
    rows = _by_week(df)
    assert rows[1].week_ending_date == dt.date(2018, 2, 23)
    assert rows[2].week_ending_date is None
    assert rows[3].week_ending_date == dt.date(2018, 3, 9)     # carry survives the gap


def test_the_empty_frame_still_carries_the_anchor_column():
    df = build_deliveries_silver([])
    assert list(df.columns) == _SILVER_COLUMNS
    assert df.empty


# =============================================================================================
# 3. The INV-2 writer schema: the anchor must survive the publisher as date32[day].
# =============================================================================================
def _contract(with_anchor: bool = True) -> dict:
    """The F010 contract shape this producer must be re-run against (the 10-column form)."""
    cols = [
        {"name": "season", "target_arrow_type": "string", "nullable": False},
        {"name": "crop", "target_arrow_type": "string", "nullable": False},
        {"name": "week_number", "target_arrow_type": "int64", "nullable": False},
        {"name": "week_ending", "target_arrow_type": "string", "nullable": True},
        {"name": "prog_total_mt", "target_arrow_type": "float64", "nullable": True},
        {"name": "prior_prog_total_mt", "target_arrow_type": "float64", "nullable": True},
        {"name": "pct_of_prior_yr", "target_arrow_type": "float64", "nullable": True},
        {"name": "z_vs_3yr_avg", "target_arrow_type": "float64", "nullable": True},
        {"name": "source", "target_arrow_type": "string", "nullable": True},
    ]
    if with_anchor:
        cols.append({"name": "week_ending_date", "target_arrow_type": "date32[day]",
                     "nullable": True})
    return {"table_name": TABLE, "physical_columns": cols}


def _two_week_frame():
    snap = _snap("ProdProgressive-Mielies_2017_18_Week02.xlsx", _dt(2018, 3, 9))
    return build_deliveries_silver([
        _rec(snap, 1, 1000.0, "17/02 - 23/02/2018"),
        _rec(snap, 2, 2500.0, "24/02 - 02/03/2018"),
    ])


def test_the_anchor_encodes_as_date32_under_the_inv2_writer_schema():
    """date32[day] end to end -- the same physical type sagis_weekly_exports' week_ending_date and
    mpoc_exports' year_ending_date carry, which is what makes the Athena guard a DATE compare."""
    contract = _contract()
    assert str(pa_schema_from_contract(contract).field("week_ending_date").type) == "date32[day]"
    table = pq.read_table(io.BytesIO(encode_parquet(_two_week_frame(), contract)))
    assert str(table.schema.field("week_ending_date").type) == "date32[day]"
    assert table.column("week_ending_date").to_pylist() == [dt.date(2018, 2, 23),
                                                            dt.date(2018, 3, 2)]


def test_an_all_null_anchor_column_still_encodes_date32_not_arrow_null():
    """The INV-2 hazard this whole schema pin exists for: an all-null derived column left to
    inference becomes arrow ``null`` and the crawler mints a table Athena cannot compare."""
    snap = _snap("ProdProgressive-Mielies_2017_18_Week01.xlsx", _dt(2018, 3, 2))
    df = build_deliveries_silver([_rec(snap, 1, 1000.0, None)])
    table = pq.read_table(io.BytesIO(encode_parquet(df, _contract())))
    assert str(table.schema.field("week_ending_date").type) == "date32[day]"
    assert table.column("week_ending_date").to_pylist() == [None]


def test_encode_fails_closed_until_the_contract_declares_the_anchor():
    """THE SEQUENCING PIN. The F010 contract must gain week_ending_date BEFORE the producer is
    re-run. flat_producer.encode_parquet says so with an error; the deliveries task publishes
    through _sb_producer_publish, which instead SELECTS the contract's columns and would drop the
    anchor SILENTLY -- so the task carries its own guard (section 5)."""
    with pytest.raises(ValueError, match=r"extra=\['week_ending_date'\]"):
        encode_parquet(_two_week_frame(), _contract(with_anchor=False))


# =============================================================================================
# 4. NO REGRESSION on the sibling: silver_sagis_weekly_exports parses 1,204/1,204 as-is.
# =============================================================================================
@pytest.mark.parametrize("text,expected", [
    ("3 - 9 May 2003", (9, 5, 2003)),
    ("10 - 16 May", (16, 5, None)),
    ("31 May - 6 Jun", (6, 6, None)),
    ("27 Dec - 2 Jan 2004", (2, 1, 2004)),
    ("2 - 8Aug", (8, 8, None)),
    ("30 Apr - 6 May '05", (6, 5, 2005)),
    ("07 Oct/Okt - 14 Oct/Okt 2016", (14, 10, 2016)),
    ("1 - 7 Mar/Mrt 2014", (7, 3, 2014)),
    ("30 Sep - 6 Oct/Okt", (6, 10, None)),
    ("14 May/Mei - 20 May/Mei 2016", (20, 5, 2016)),
    ("02 Dec/Des - 08 Dec/Des 2023", (8, 12, 2023)),
])
def test_the_exports_letter_month_formats_are_byte_identical(text, expected):
    """Every format present in the live exports table (all 1,204 rows parse) resolves on the LETTER
    branch, which runs FIRST and returns before the fallback is reachable. The widening therefore
    cannot change one exports value -- that is the safety argument, pinned rather than asserted."""
    assert parse_week_ending_end(text) == expected


@pytest.mark.parametrize("text", [None, "", "   ", "garbage", "5 -", "- 9 Xyz", "9 Foo 2003"])
def test_the_exports_unparseable_set_stays_unparseable(text):
    """The fallback must not turn a REFUSAL into a value. '9 Foo 2003' matches the letter-month
    shape but resolves no month, and it must still be None afterwards."""
    assert parse_week_ending_end(text) is None


def test_the_exports_producer_output_shape_is_untouched():
    """The pre-step is scoped to ONE table: the sibling's column list must not drift a column."""
    from leviathan.transforms.bronze_to_silver.sagis_weekly_exports import OUTPUT_COLUMNS
    assert OUTPUT_COLUMNS == [
        "season", "crop", "week_number", "week_ending", "week_ending_date", "prog_exports_mt",
        "pct_of_prior_yr", "z_vs_3yr_avg", "source",
    ]


def test_the_producer_metrics_are_unchanged_by_the_anchor():
    """The derivation is a pure TIMING column: it never touches a measured value, so the stored
    no-lookahead comparisons the card serves AS STORED must be bit-for-bit what they were."""
    recs = []
    for start, total in ((2020, 100.0), (2021, 110.0), (2022, 120.0), (2023, 150.0)):
        snap = _snap(f"ProdProgressive-Mielies_{start}_{str(start + 1)[-2:]}_Week10.xlsx",
                     _dt(start + 1, 1, 1))
        recs.append(_rec(snap, 10, total, "01/07 - 05/07"))
    df = build_deliveries_silver(recs)
    row = df[df["season"] == "2023-24"].iloc[0]
    assert row["prior_prog_total_mt"] == pytest.approx(120.0)
    assert row["pct_of_prior_yr"] == pytest.approx(1.25)          # a RATIO, never x100
    assert row["z_vs_3yr_avg"] == pytest.approx(4.0)              # sample std over [100,110,120]


# =============================================================================================
# 5. The task-level sequencing guard + the checked-in DDL.
# =============================================================================================
def test_the_task_guard_names_the_undeclared_column_instead_of_dropping_it(monkeypatch):
    """_sb_producer_publish.df_to_parquet_bytes does ``df[[f.name for f in schema]]``: an
    undeclared producer column is dropped SILENTLY, the run looks clean, the parquet is unchanged
    and the card stays unbuildable. The guard turns that into a named refusal."""
    from jobs.batch import sagis_deliveries_task as task

    class _Reg:
        def table(self, _name):
            return {"physical_columns": [{"name": c} for c in _SILVER_COLUMNS[:-1]]}

    monkeypatch.setattr("leviathan.silver.registry.load_registry", lambda: _Reg())
    with pytest.raises(ValueError, match="week_ending_date"):
        task.assert_contract_declares_every_column(_two_week_frame())


def test_the_task_guard_passes_once_the_contract_declares_the_anchor(monkeypatch):
    from jobs.batch import sagis_deliveries_task as task

    class _Reg:
        def table(self, _name):
            return {"physical_columns": [{"name": c} for c in _SILVER_COLUMNS]}

    monkeypatch.setattr("leviathan.silver.registry.load_registry", lambda: _Reg())
    task.assert_contract_declares_every_column(_two_week_frame())          # no raise


def test_the_checked_in_ddl_declares_the_anchor_as_a_date():
    """config_check.check_numbers_schema_pins reads THIS file to pin the card's date_col /
    knowledge_date_col, so the card fails the build-time lint until the column is here."""
    sql = _DDL.read_text(encoding="utf-8").lower()
    assert "week_ending_date    date" in sql
    for col in ("season", "crop", "week_number", "week_ending", "prog_total_mt",
                "prior_prog_total_mt", "pct_of_prior_yr", "z_vs_3yr_avg", "source"):
        assert col in sql
    assert "partitioned by" not in sql            # flat / projection-forbidden: no partition grid


def test_the_free_text_label_can_never_be_the_anchor():
    """The trap this whole pre-step exists to close, stated as a measurement rather than a warning:
    the free-text label sorts BELOW an ISO as-of literal, so a guard built on it admits the row no
    matter how far in the future the week is."""
    future_label = "01/08 - 07/08/2026"
    assert future_label <= "2025-06-01"                       # lexicographic: admitted, wrongly
    derived = parse_week_ending_end(future_label)
    assert dt.date(derived[2], derived[1], derived[0]).isoformat() > "2025-06-01"   # correctly out
