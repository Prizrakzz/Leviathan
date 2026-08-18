"""D-LD TRANCHE 2 -- the PRODUCER-SIDE pre-step for silver_mpoc_exports_by_country.

This file pins the two producer changes that DISCHARGE the D-PQ tranche-1a "guard" refusal of
``silver_mpoc_exports_by_country``. It is deliberately separate from (and lands BEFORE) the card's
own test block: the card, its tables.yaml entry and the F010 PIT trio are a later change, and this
one must be green on its own.

WHAT IS PINNED, AND WHY EACH PIN IS LOAD-BEARING
------------------------------------------------
1. ``year_ending_date`` -- the derived PIT anchor. The table shipped with NO date, NO month and NO
   vintage column, so ``TableSpec.knowledge_col()`` had nothing to return and ``query._guard`` raised
   on every read: a card would have been a served table that refused 100% of its lookups. One
   producer-derived column (``date(year, 12, 31)``, the WIRING-WAVE-1 idiom that
   silver_sagis_weekly_exports used for ``week_ending_date``) is the whole discharge. It is the PERIOD
   END and NOT a guessed publication date -- the publication guess belongs in the card's
   ``publication_lag_days`` where it stays auditable and tunable.

   THE NEGATIVE HALF IS ALSO PINNED: the D-LD plan's row 5 called this table ``wide/year_month``. It
   is not and cannot be -- there is no month column here (that is the sibling
   silver_mpoc_trade_stats_monthly) and ``year_month`` semantics raise without BOTH year_col and
   month_col. ``test_no_month_column_so_year_month_stays_inexpressible`` is what stops the wrong
   designation coming back.

2. The ``CHINA P.R`` / ``U.S.A`` aliases. MEASURED against the 15 raw MPOC pages in S3 on 2026-08-18:
   ``normalize_country`` returned ``None`` for those two live surface forms and ``_rows_for_release``
   dropped the row WITHOUT a warning -- 9 rows (china 2015-2017, usa 2015-2020). The silver table's
   china and usa "gaps" were INGEST LOSS, not source absence, and a desk reading the card would have
   narrated "China stopped taking Malaysian palm in 2015" off a normalizer alias hole. Re-measured
   with the fix: 145 shortlist labels across the 15 pages, minus the 15 excluded TOTAL rows, = 130
   destination rows, and ZERO labels now fail to normalize (was 121 rows / 9 unmapped).

AWS-free: the S3 measurement above is reproduced here on trimmed excerpts of the real page labels.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from leviathan.silver.flat_producer import encode_parquet, pa_schema_from_contract
from leviathan.silver.mpoc.adapter import normalize_country, parse_tables
from leviathan.transforms.bronze_to_silver.mpoc_exports_by_country import (
    OUTPUT_COLUMNS,
    MpocExportsRelease,
    transform_exports_by_country,
)

TABLE = "silver_mpoc_exports_by_country"
_REPO = Path(__file__).resolve().parents[2]
_DDL = _REPO / "sql" / "athena" / "ddl" / f"{TABLE}.sql"


# ---------------------------------------------------------------------------------------------
# Fixtures: the REAL label sets, trimmed. 2015 and 2019 are the two pages that carry the surface
# forms the normalizer used to drop (CHINA P.R -> 2015-2017, U.S.A -> 2015-2020).
# ---------------------------------------------------------------------------------------------
_PAGE_2015 = """
<table><tbody>
<tr><th>COUNTRY</th><th>JAN - DEC 2015</th><th>JAN - DEC 2014</th></tr>
<tr><td>INDIA</td><td>2,392,000</td><td>2,300,000</td></tr>
<tr><td>CHINA P.R</td><td>1,733,000</td><td>1,900,000</td></tr>
<tr><td>EU</td><td>2,432,424</td><td>2,500,000</td></tr>
<tr><td>PAKISTAN</td><td>1,100,000</td><td>1,050,000</td></tr>
<tr><td>U.S.A</td><td>1,015,000</td><td>990,000</td></tr>
<tr><td>TOTAL</td><td>8,672,424</td><td>8,740,000</td></tr>
</tbody></table>
"""

_PAGE_2019 = """
<table><tbody>
<tr><th>COUNTRY</th><th>JAN - DEC 2019</th><th>JAN - DEC 2018</th></tr>
<tr><td>INDIA</td><td>4,409,511</td><td>2,510,000</td></tr>
<tr><td>CHINA</td><td>1,900,000</td><td>1,850,000</td></tr>
<tr><td>U.S.A</td><td>900,000</td><td>870,000</td></tr>
<tr><td>TOTAL</td><td>7,209,511</td><td>5,230,000</td></tr>
</tbody></table>
"""


def _release(year: int, html: str) -> MpocExportsRelease:
    return MpocExportsRelease(year=year, tables=parse_tables(html))


def _rows(df) -> dict:
    return {(int(r.year), r.country): r for r in df.itertuples()}


# =============================================================================================
# 1. The derived PIT anchor.
# =============================================================================================
def test_output_columns_gained_the_anchor_and_kept_the_original_order():
    """APPENDED, never re-ordered: the four original columns keep their declaration order so the
    contract's physical_columns list is an append, not a rewrite."""
    assert OUTPUT_COLUMNS == ["year", "country", "exports_mt", "source", "year_ending_date"]


def test_the_anchor_is_a_real_date_object_on_the_period_end():
    """``date(year, 12, 31)`` -- the END of the calendar year the row measures, held as a python
    ``datetime.date`` so the flat publisher encodes date32[day] (never a string that would sort
    lexically and mis-compare at window edges)."""
    df = transform_exports_by_country([_release(2015, _PAGE_2015)])
    anchors = set(df["year_ending_date"])
    assert anchors == {dt.date(2015, 12, 31)}
    assert all(type(v) is dt.date for v in df["year_ending_date"])


def test_the_anchor_is_the_period_end_not_a_publication_guess():
    """The Jan-Dec book for year Y prints the FOLLOWING January, but the DATA stamp stays on
    31 December of Y: the publication guess lives in the card's publication_lag_days (+60d), where
    it is auditable and tunable, not baked irreversibly into the row."""
    df = transform_exports_by_country([_release(2019, _PAGE_2019)])
    assert set(df["year_ending_date"]) == {dt.date(2019, 12, 31)}
    assert dt.date(2020, 1, 1) not in set(df["year_ending_date"])


def test_every_row_carries_its_own_year_s_anchor_across_a_multi_year_load():
    df = transform_exports_by_country([_release(2019, _PAGE_2019), _release(2015, _PAGE_2015)])
    for r in df.itertuples():
        assert r.year_ending_date == dt.date(int(r.year), 12, 31)
    assert set(df["year_ending_date"]) == {dt.date(2015, 12, 31), dt.date(2019, 12, 31)}


def test_no_month_column_so_year_month_stays_inexpressible():
    """The D-LD plan called this card wide/year_month. It is NOT: no month column exists, and
    year_month semantics raise without year_col AND month_col. Corrected to data_date on the
    derived anchor -- pinned so the wrong designation cannot come back through this producer."""
    assert "month" not in OUTPUT_COLUMNS
    df = transform_exports_by_country([_release(2019, _PAGE_2019)])
    assert "month" not in df.columns


def test_the_empty_frame_still_carries_the_anchor_column():
    """A drift-free page with no mappable rows must still return the contracted shape, else the
    publisher's column check fails with a confusing 'missing' rather than an honest zero-row run."""
    empty_page = """
    <table><tbody><tr><th>COUNTRY</th><th>JAN - DEC 2020</th></tr>
    <tr><td>TOTAL</td><td>1,000</td></tr></tbody></table>
    """
    df = transform_exports_by_country([_release(2020, empty_page)])
    assert list(df.columns) == OUTPUT_COLUMNS
    assert df.empty


# =============================================================================================
# 2. The INV-2 writer schema: the anchor must survive the flat publisher as date32[day].
# =============================================================================================
def _contract_with_anchor(nullable_anchor: bool = False) -> dict:
    """The F010 contract shape this producer must be re-run against (the 5-column form)."""
    return {
        "table_name": TABLE,
        "physical_columns": [
            {"name": "year", "target_arrow_type": "int64", "nullable": False},
            {"name": "country", "target_arrow_type": "string", "nullable": False},
            {"name": "exports_mt", "target_arrow_type": "float64", "nullable": True},
            {"name": "source", "target_arrow_type": "string", "nullable": True},
            {"name": "year_ending_date", "target_arrow_type": "date32[day]",
             "nullable": nullable_anchor},
        ],
    }


def test_the_anchor_encodes_as_date32_under_the_inv2_writer_schema():
    """date32[day] end to end -- the same physical type sagis_weekly_exports' week_ending_date and
    conab_coffee's survey_release_date carry, which is what makes the Athena guard a DATE compare."""
    df = transform_exports_by_country([_release(2019, _PAGE_2019)])
    contract = _contract_with_anchor()
    schema = pa_schema_from_contract(contract)
    assert str(schema.field("year_ending_date").type) == "date32[day]"
    table = pq.read_table(io.BytesIO(encode_parquet(df, contract)))
    assert str(table.schema.field("year_ending_date").type) == "date32[day]"
    assert set(table.column("year_ending_date").to_pylist()) == {dt.date(2019, 12, 31)}


def test_the_anchor_is_never_null_so_a_non_nullable_contract_holds():
    """It is DERIVED from the page year, so it can never be missing -- the PIT guard is therefore
    never silently defeated by a null (``null <= asof`` is UNKNOWN and drops the row)."""
    df = transform_exports_by_country([_release(2015, _PAGE_2015), _release(2019, _PAGE_2019)])
    assert df["year_ending_date"].notna().all()
    encode_parquet(df, _contract_with_anchor(nullable_anchor=False))  # non-nullable field: no raise


def test_encode_fails_closed_until_the_contract_declares_the_anchor():
    """THE SEQUENCING PIN. flat_producer.encode_parquet requires df columns == contract
    physical_columns EXACTLY, so the F010 contract must gain year_ending_date BEFORE the producer is
    re-run -- re-running first is a hard error, not a silently-dropped column."""
    df = transform_exports_by_country([_release(2019, _PAGE_2019)])
    four_col = _contract_with_anchor()
    four_col["physical_columns"] = four_col["physical_columns"][:4]
    with pytest.raises(ValueError, match=r"extra=\['year_ending_date'\]"):
        encode_parquet(df, four_col)


# =============================================================================================
# 3. The normalizer aliases (the 9 silently-dropped rows).
# =============================================================================================
def test_the_two_live_surface_forms_normalize():
    """MEASURED 2026-08-18 against the raw pages: these two spellings appear on the 2015-2020 pages
    and folded to keys the alias map did not carry ('p.r. china'/'pr china' and 'u.s.a.' WITH the
    trailing dot were present; these two were not)."""
    assert normalize_country("CHINA P.R") == "china"
    assert normalize_country("U.S.A") == "usa"


@pytest.mark.parametrize("raw", ["china p.r", " CHINA  P.R ", "China P.R"])
def test_the_china_form_folds_case_and_whitespace(raw):
    assert normalize_country(raw) == "china"


@pytest.mark.parametrize("raw", ["u.s.a", " U.S.A ", "U.S.A*"])
def test_the_usa_form_folds_case_whitespace_and_footnote_marks(raw):
    assert normalize_country(raw) == "usa"


@pytest.mark.parametrize("raw,expect", [
    ("CHINA", "china"), ("P.R. China", "china"), ("PR CHINA", "china"),
    ("USA", "usa"), ("U.S.A.", "usa"), ("United States", "usa"),
    ("TURKIYE", "turkey"), ("TURKEY", "turkey"), ("SOUTH KOREA", "south_korea"),
    ("SAUDI ARABIA", "saudi_arabia"), ("EU", "eu"), ("NETHERLANDS", "netherlands"),
    ("TOTAL", "total"), ("Others", "others"),
])
def test_no_regression_on_the_spellings_that_already_worked(raw, expect):
    """The two new aliases must be ADDITIVE: every surface form the 15 pages already carried keeps
    its existing mapping, including the aggregate labels the producer excludes by name."""
    assert normalize_country(raw) == expect


def test_a_genuinely_unknown_label_still_returns_none():
    """The map stays a CLOSED vocabulary -- the fix is two spellings of two countries already in it,
    not a loosening that would let an unmodelled destination through under a wrong canonical name."""
    assert normalize_country("ATLANTIS") is None
    assert normalize_country("") is None


def test_the_alias_fix_recovers_the_dropped_rows_end_to_end():
    """China 2015 and USA 2015/2019 are exactly the rows that used to vanish between the page and
    silver. Absence in silver read to a caller as 'stopped buying'; it was ingest loss."""
    df = transform_exports_by_country([_release(2015, _PAGE_2015), _release(2019, _PAGE_2019)])
    rows = _rows(df)
    assert rows[(2015, "china")].exports_mt == 1_733_000.0
    assert rows[(2015, "usa")].exports_mt == 1_015_000.0
    assert rows[(2019, "usa")].exports_mt == 900_000.0
    assert rows[(2019, "china")].exports_mt == 1_900_000.0
    # 5 mappable 2015 rows + 3 mappable 2019 rows; TOTAL excluded on both pages.
    assert len(df) == 8
    assert "total" not in set(df["country"])


def test_a_label_the_vocabulary_cannot_map_is_logged_not_silently_dropped(caplog):
    """The durable half of the defect: the row is still skipped (fail-safe, never a wrong country),
    but it no longer disappears without a trace -- which is how 9 rows stayed lost for the table's
    whole life."""
    page = _PAGE_2019.replace("<td>CHINA</td>", "<td>ATLANTIS</td>")
    with caplog.at_level(logging.WARNING):
        df = transform_exports_by_country([_release(2019, page)])
    assert "atlantis" not in set(df["country"])
    assert any("ATLANTIS" in rec.getMessage() for rec in caplog.records)


# =============================================================================================
# 4. No regression: the sibling MPOC producers and the original grain rules are untouched.
# =============================================================================================
def test_the_sibling_mpoc_producers_did_not_gain_an_anchor():
    """The pre-step is scoped to ONE table. silver_mpoc_trade_stats_monthly is genuinely year x
    month (it is the table the plan's year_month designation actually belongs to) and
    silver_mpoc_stock_comparison already serves; neither may drift a column here."""
    from leviathan.transforms.bronze_to_silver.mpoc_stock_comparison import (
        OUTPUT_COLUMNS as STOCK_COLS,
    )
    from leviathan.transforms.bronze_to_silver.mpoc_trade_stats_monthly import (
        OUTPUT_COLUMNS as MONTHLY_COLS,
    )
    assert "year_ending_date" not in STOCK_COLS
    assert "year_ending_date" not in MONTHLY_COLS
    assert MONTHLY_COLS == ["year", "month", "exports_mt", "imports_mt", "source"]


def test_the_aggregate_rollups_are_still_excluded():
    """S2: the source TOTAL row is the sum of the SHORTLIST, not Malaysia's national exports, so it
    must never enter the grain -- no share is computable from this table."""
    df = transform_exports_by_country([_release(2015, _PAGE_2015)])
    assert set(df["country"]).isdisjoint({"total", "others", "world"})


def test_the_page_year_column_is_still_the_one_read():
    """The pages print the prior year beside the page year; picking the wrong column would silently
    shift the whole series by one year -- and now also mis-pair it with the anchor."""
    df = transform_exports_by_country([_release(2019, _PAGE_2019)])
    assert _rows(df)[(2019, "india")].exports_mt == 4_409_511.0   # 2019 col, not the 2018 one


# =============================================================================================
# 5. The checked-in DDL carries the anchor (config_check.check_numbers_schema_pins reads this file).
# =============================================================================================
def test_the_checked_in_ddl_declares_the_anchor_as_a_date():
    sql = _DDL.read_text(encoding="utf-8").lower()
    assert "year_ending_date date" in sql
    for col in ("year", "country", "exports_mt", "source"):
        assert col in sql
    assert "partitioned by" not in sql            # flat / projection-forbidden: no partition grid


def test_the_ddl_create_block_matches_the_generator_house_format():
    """THE REGENERATION PIN. This DDL is HAND-STAGED ahead of the producer re-run (the card's
    date_col must resolve at config_check time), so the one thing that can silently rot is the hand
    text drifting from what the generator will emit afterwards. Everything from CREATE onward is
    reproduced here in the legacy generator's exact house format -- 4-space indent, the name column
    ljust to the widest name (len('year_ending_date') = 16), one space before the type, arrow
    date32[day] -> Athena `date` -- so a regeneration is provably a semantic no-op and a hand
    misalignment fails HERE instead of surfacing as F011 drift.

    Only the leading comment block differs: the generator writes its own two-line header and would
    DROP the D-LD provenance note, which the header itself now says out loud."""
    text = _DDL.read_text(encoding="utf-8")
    head, _, create = text.partition("CREATE EXTERNAL")
    assert create, "the DDL lost its CREATE statement"
    assert all(ln.startswith("--") for ln in head.splitlines() if ln.strip()), \
        "everything before CREATE must be comment lines"
    cols = [("year", "bigint"), ("country", "string"), ("exports_mt", "double"),
            ("source", "string"), ("year_ending_date", "date")]
    width = max(len(n) for n, _ in cols)
    assert width == 16
    body = ",\n".join("    %s %s" % (n.ljust(width), t) for n, t in cols)
    expected = (
        "CREATE EXTERNAL TABLE IF NOT EXISTS silver_mpoc_exports_by_country (\n%s\n)\n"
        "STORED AS PARQUET\n"
        "LOCATION 's3://leviathan-dev-shahem-001/silver/mpoc_exports_by_country/'\n"
        "TBLPROPERTIES ('parquet.compression' = 'SNAPPY');\n" % body
    )
    assert "CREATE EXTERNAL" + create == expected


def test_the_ddl_column_order_is_the_producer_output_order():
    """The catalog column order must be the DataFrame order the publisher writes, anchor LAST --
    a flat parquet table read by position on a mismatched catalog is silently transposed data."""
    text = _DDL.read_text(encoding="utf-8")
    body = text[text.index("(", text.index("CREATE EXTERNAL")) + 1:text.index("\n)\n")]
    names = [ln.strip().split()[0] for ln in body.strip().splitlines()]
    assert names == OUTPUT_COLUMNS


# =============================================================================================
# 6. The producer's own coverage arithmetic (the S3 measurement, reproduced without S3).
# =============================================================================================
def test_every_shortlist_label_is_either_a_row_or_a_named_aggregate():
    """THE COVERAGE INVARIANT the 2026-08-18 S3 measurement asserts in the large: across the 15 raw
    pages there are 145 shortlist labels, 15 of them the excluded TOTAL row, and -- with the two
    aliases -- ZERO that fail to normalize, so silver carries 145 - 15 = 130 rows. Pinned here as
    the per-page identity (labels == rows + aggregates + unmapped) so a future vocabulary change
    cannot re-open a silent gap: any label the map stops covering breaks this, not just the two
    spellings that happened to be measured."""
    from leviathan.silver.mpoc.adapter import find_table_by_header
    from leviathan.transforms.bronze_to_silver.mpoc_exports_by_country import (
        _AGGREGATE_COUNTRIES,
        _EXPORTS_FIRST_COL,
    )
    for year, page in ((2015, _PAGE_2015), (2019, _PAGE_2019)):
        rel = _release(year, page)
        table = find_table_by_header(rel.tables, first_col=_EXPORTS_FIRST_COL)
        labels = [row[0] for row in table.rows if row]
        mapped = [normalize_country(x) for x in labels]
        assert None not in mapped, (year, [x for x, m in zip(labels, mapped) if m is None])
        aggregates = [m for m in mapped if m in _AGGREGATE_COUNTRIES]
        rows = transform_exports_by_country([rel])
        assert len(labels) == len(rows) + len(aggregates)
        assert len(aggregates) == 1                       # exactly the one TOTAL row per page
