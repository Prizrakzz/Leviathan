"""SILVER-F050 -- AMS cotton-quality producer (half-orphan restore) unit + contract tests.

Covers: national-only (us_total) scope selection with regional/appendix rows dropped; one wide row
per commodity x geography x season; source_pages aggregation + provenance carry; conflicting
national metrics fail closed; and the INV-2 NULL-TYPE regression -- an all-null avg_micronaire /
avg_strength column writes as ``double`` (never Arrow ``null``) through the SILVER-F015 publisher.

AMS-1 (D-LD Tranche 2) adds the PIT-anchor section at the bottom: the DERIVED ``release_date``
column that gives this date-less table something for the numbers as-of guard to bind to.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.common.publish_guard import Authorization, PublishMode
from leviathan.silver import ddl as D
from leviathan.silver.flat_producer import build_flat_publish
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_ams_cotton_key
from leviathan.transforms.bronze_to_silver.ams_cotton_quality import (
    SILVER_COLUMNS,
    ams_release_date,
    build_ams_cotton_silver,
)

_REPO = Path(__file__).resolve().parents[2]
_HAND_DDL = _REPO / "sql" / "athena" / "ddl" / "silver_ams_cotton_quality.sql"
# The 12 pre-AMS-1 physical columns, in catalog order. Pinned as a literal so the widen can only
# ever APPEND: a reordered or dropped sibling column is a regression, not a migration.
_PRE_AMS1_COLUMNS = [
    "commodity", "season", "geography", "percent_tenderable", "samples_classed", "avg_staple",
    "avg_micronaire", "avg_strength", "source_pages", "source_raw_key", "source_file_etag",
    "source",
]
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_RAW_KEY = "raw/production/source=usda_ams_cotton_classing/report_type=annual_quality/season=1986/1986ACQ.pdf"


class _FakeS3:
    def __init__(self):
        self.store: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[(Bucket, Key)] = bytes(Body)
        return {"ETag": '"x"'}

    def copy_object(self, Bucket, Key, CopySource, **kw):
        self.store[(Bucket, Key)] = self.store[(CopySource["Bucket"], CopySource["Key"])]
        return {}


def _shadow_auth():
    return Authorization(mode=PublishMode.SHADOW, may_mutate_canonical=False, readiness=True, reason="t")


def _dryrun_auth():
    return Authorization(mode=PublishMode.DRY_RUN, may_mutate_canonical=False, readiness=True, reason="t")


def _brow(season, geography, scope, metric, value, page, etag="e0"):
    return {"season": season, "geography": geography, "extraction_scope": scope, "metric": metric,
            "value": value, "unit": "x", "source_page": page, "source_raw_key": _RAW_KEY,
            "source_file_etag": etag, "source": "usda_ams_cotton_classing_annual"}


def _bronze_1986():
    # national narrative (avg_staple, p1) + national summary (percent_tenderable, p2) + regional junk.
    return pd.DataFrame([
        _brow(1986, "us_total", "national_narrative", "avg_staple", 34.6, 1),
        _brow(1986, "us_total", "national_summary", "percent_tenderable", 44.1, 2),
        _brow(1986, "unknown", "regional_or_appendix", "percent_tenderable", 56.5, 3),
        _brow(1986, "unknown", "regional_or_appendix", "avg_staple", 34.1, 4),
        _brow(1986, "unknown", "regional_or_appendix", "avg_strength", 29.0, 7),
    ])


def test_national_only_and_wide_row():
    s = build_ams_cotton_silver(_bronze_1986())
    assert list(s.columns) == SILVER_COLUMNS
    assert len(s) == 1
    row = s.iloc[0]
    assert row["commodity"] == "cotton" and row["geography"] == "us_total" and row["season"] == 1986
    assert row["percent_tenderable"] == pytest.approx(44.1)
    assert row["avg_staple"] == pytest.approx(34.6)
    # regional avg_strength did NOT leak into the national row
    assert pd.isna(row["avg_strength"])
    assert pd.isna(row["avg_micronaire"])
    # source_pages = the national metric pages only (1, 2) -- not the regional pages
    assert row["source_pages"] == "1,2"
    assert row["source_raw_key"] == _RAW_KEY


def test_all_null_measure_columns_present_and_null():
    s = build_ams_cotton_silver(_bronze_1986())
    assert s["avg_micronaire"].isna().all()
    assert s["avg_strength"].isna().all()


def test_conflicting_national_metric_fails_closed():
    bronze = pd.concat([
        _bronze_1986(),
        pd.DataFrame([_brow(1986, "us_total", "national_summary", "percent_tenderable", 99.9, 2)]),
    ], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        build_ams_cotton_silver(bronze)


def test_no_national_rows_fails_closed():
    bronze = pd.DataFrame([_brow(1986, "unknown", "regional_or_appendix", "avg_staple", 34.0, 3)])
    with pytest.raises(ValueError, match="national"):
        build_ams_cotton_silver(bronze)


def test_multi_season_one_row_each():
    bronze = pd.concat([
        _bronze_1986(),
        pd.DataFrame([_brow(1987, "us_total", "national_summary", "percent_tenderable", 67.0, 7)]),
    ], ignore_index=True)
    s = build_ams_cotton_silver(bronze)
    assert len(s) == 2
    assert not s.duplicated(subset=["commodity", "geography", "season"]).any()


# ---------------------------------------------------------------------------
# INV-2 null-type fix through the publisher.
# ---------------------------------------------------------------------------
def _contract():
    """The F010 contract, carrying the AMS-1 additive TARGET column.

    ``configs/silver/tables/*.yaml`` is GENERATED from the frozen R0 baseline and is regenerated by
    the orchestrator only AFTER the Glue widen + baseline re-capture, so between this change and
    that apply the checked-in contract still declares 12 columns while the producer emits 13. The
    shim appends the migration target the generator will produce (string, last, nullable false) and
    becomes a no-op the moment the regeneration lands -- which is exactly the WIRING_WAVE1
    "registry carries the additive TARGET" discipline, expressed in the test rather than by
    hand-editing a generated file.
    """
    contract = load_registry().table("silver_ams_cotton_quality")
    cols = contract.get("physical_columns", [])
    if not any(c["name"] == "release_date" for c in cols):
        contract = dict(contract)
        contract["physical_columns"] = list(cols) + [{
            "name": "release_date", "glue_type": "string", "arrow_type": "string",
            "parquet_physical_type": "BYTE_ARRAY", "target_arrow_type": "string", "nullable": False,
        }]
    return contract


def _value_valid_silver():
    # EVERY value_column populated so the SILVER-V001 floor passes; avg_micronaire / avg_strength stay
    # ALL-NULL to exercise the null-type pin, which is the only thing these two tests are about.
    #
    # THE SET GREW TO THREE (D-LD Tranche 2, 2026-08-18) and this fixture has to track it, because the
    # floor is computed FROM the contract: landing the numbers card made `build_contract` derive
    # value_columns from the CARD'S METRIC KEYS for this wide table (gen_registry_from_baseline.py:549),
    # so `avg_staple` -- a served metric, and one of the two the card actually leads with -- joined
    # percent_tenderable and samples_classed. It is REAL data on the live table (only avg_micronaire and
    # avg_strength are the 0/27 null_typed pair, which is why those two and not this one are excluded
    # from the card), so the 0.5 default floor is right for it and needs no override; what was wrong was
    # a fixture that populated two of three value columns and then asserted a publish succeeds.
    # samples_classed keeps its own calibrated 0.25 override (8 of 27 seasons carry it) -- untouched.
    rows = []
    for season, pt, sc, st in [(1986, 44.1, 900.0, 34.6), (1987, 67.0, 950.0, 35.1)]:
        rows.append(_brow(season, "us_total", "national_summary", "percent_tenderable", pt, 2))
        rows.append(_brow(season, "us_total", "national_summary", "samples_classed", sc, 2))
        rows.append(_brow(season, "us_total", "national_narrative", "avg_staple", st, 1))
    return build_ams_cotton_silver(pd.DataFrame(rows))


def test_null_typed_columns_write_as_double_dry_run():
    s = _value_valid_silver()
    plan = build_flat_publish(df=s, contract=_contract(), canonical_key=silver_ams_cotton_key(),
                              auth=_dryrun_auth(), s3_client=None, job="test",
                              manifest_store=lambda k, b: None)
    plan.run()
    # INV-2: all-null measures pinned double, NOT arrow null.
    assert plan.schema.field("avg_micronaire").type == pa.float64()
    assert plan.schema.field("avg_strength").type == pa.float64()


def test_shadow_parquet_has_double_not_null_type():
    s = _value_valid_silver()
    s3 = _FakeS3()
    plan = build_flat_publish(df=s, contract=_contract(), canonical_key=silver_ams_cotton_key(),
                              auth=_shadow_auth(), s3_client=s3, job="test",
                              manifest_store=lambda k, b: None)
    plan.run()
    keys = [k for (_, k) in s3.store]
    assert len(keys) == 1 and "_shadow" in keys[0] and keys[0] != silver_ams_cotton_key()
    schema = pq.read_schema(io.BytesIO(next(iter(s3.store.values()))))
    # the exact s3-lane hazard: physical was Arrow-null; the pin makes it double.
    assert schema.field("avg_micronaire").type == pa.float64()
    assert schema.field("avg_strength").type == pa.float64()
    assert not pa.types.is_null(schema.field("avg_micronaire").type)


# ===========================================================================================
# AMS-1 (D-LD Tranche 2) -- the DERIVED PIT anchor.
#
# The table shipped with NO date column of any kind: `season` is a crop-year INTEGER, which no
# as-of guard branch can bind to (the guard needs a knowledge/date column or BOTH year_col and
# month_col). `release_date` is the conservative, never-leak publication stamp that closes that,
# the silver_conab_coffee survey_release_date idiom.
# ===========================================================================================
def _bronze_seasons(seasons):
    rows = []
    for s in seasons:
        rows.append(_brow(s, "us_total", "national_summary", "percent_tenderable", 70.0, 2))
        rows.append(_brow(s, "us_total", "national_narrative", "avg_staple", 35.0, 1))
    return pd.DataFrame(rows)


# The season axis MEASURED on the canonical parquet 2026-08-18 (s3://leviathan-dev-shahem-001/
# silver/ams_cotton_quality/part-000.parquet, 9,798 B): 27 seasons, thin and holed -- 1986-1998,
# then 2008, 2009, 2011, 2015, 2016, 2017, then 2018-2025. The gaps are missing REPORTS.
_LIVE_SEASONS = (list(range(1986, 1999)) + [2008, 2009, 2011, 2015, 2016, 2017]
                 + list(range(2018, 2026)))


def test_release_date_is_the_conservative_september_pin():
    """Season Y's report is published during Y+1; the derived stamp is 1 September of Y+1 -- the
    start of the NEXT classing season, by which the prior season's summary is unambiguously out."""
    assert ams_release_date(2023) == "2024-09-01"
    assert ams_release_date(2025) == "2026-09-01"
    assert ams_release_date(1986) == "1987-09-01"
    # accepts the shapes a parquet/pandas season column actually arrives in
    assert ams_release_date(2023.0) == "2024-09-01"
    assert ams_release_date("2023") == "2024-09-01"


def test_release_date_never_leaks_and_orders_with_the_season():
    """CONSERVATIVE BY CONSTRUCTION: the stamp is always well AFTER the crop it describes was
    planted, grown, harvested and classed -- so the as-of guard can never hand out a season's
    quality early. And it is strictly increasing in season, so `release_date DESC` and `season DESC`
    agree; that is what makes the latest-vintage collapse deterministic."""
    stamps = [ams_release_date(s) for s in _LIVE_SEASONS]
    assert all(_ISO_DATE.match(s) for s in stamps)
    # strictly after the END of the crop's own calendar year (never mid-crop, the ESR R2 lexical trap)
    for season, stamp in zip(_LIVE_SEASONS, stamps):
        assert stamp > f"{season}-12-31", (season, stamp)
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)


def test_release_date_is_derived_for_every_row_measured_season_axis():
    """PARSE COVERAGE on the real season axis: 27/27 seasons get a stamp, no season silently
    NULL-anchored (a null PIT anchor is dropped by `null <= asof`, i.e. an invisible loss)."""
    silver = build_ams_cotton_silver(_bronze_seasons(_LIVE_SEASONS))
    assert len(silver) == 27
    assert int(silver["release_date"].notna().sum()) == 27
    assert list(silver["release_date"]) == [f"{s + 1}-09-01" for s in sorted(_LIVE_SEASONS)]
    assert all(isinstance(v, str) for v in silver["release_date"])


def test_release_date_is_appended_last_and_no_sibling_column_moved():
    """The widen may only APPEND. The 12 pre-AMS-1 columns keep their identity and order, so the
    ALTER TABLE ADD COLUMNS catalog widen matches the physical write."""
    assert SILVER_COLUMNS == _PRE_AMS1_COLUMNS + ["release_date"]
    silver = build_ams_cotton_silver(_bronze_1986())
    assert list(silver.columns) == _PRE_AMS1_COLUMNS + ["release_date"]


def test_null_or_non_integral_season_fails_loud():
    with pytest.raises(ValueError, match="null season"):
        ams_release_date(None)
    with pytest.raises(ValueError, match="null season"):
        ams_release_date(float("nan"))
    for bad in (2023.5, "not-a-year"):
        with pytest.raises(ValueError, match="integral crop year"):
            ams_release_date(bad)


def test_hand_ddl_declares_release_date_last_as_string():
    """`check_numbers_schema_pins` resolves a card's knowledge_date_col against this file, and
    `diff_structured` compares hand-DDL-vs-live-Glue IN ORDER -- so the column must be present AND
    last, or the D-LD card build fails on one and the catalog drift check on the other."""
    parsed = D.parse_ddl(_HAND_DDL.read_text(encoding="utf-8"))
    names = [n for n, _ in parsed.columns]
    assert names == _PRE_AMS1_COLUMNS + ["release_date"]
    assert dict(parsed.columns)["release_date"] == "string"
    assert parsed.partition_keys == () and parsed.partition_mode == "flat"


def test_publisher_writes_release_date_as_a_string_and_keeps_the_null_typed_pins():
    """The AMS-1 column rides the same INV-2 writer schema as everything else: string, never
    inferred -- and the SILVER-F050 all-null `double` pins do not regress alongside it."""
    silver = _value_valid_silver()
    s3 = _FakeS3()
    plan = build_flat_publish(df=silver, contract=_contract(), canonical_key=silver_ams_cotton_key(),
                              auth=_shadow_auth(), s3_client=s3, job="test",
                              manifest_store=lambda k, b: None)
    plan.run()
    schema = pq.read_schema(io.BytesIO(next(iter(s3.store.values()))))
    assert schema.names[-1] == "release_date"
    assert schema.field("release_date").type == pa.string()
    assert schema.field("avg_micronaire").type == pa.float64()
    assert schema.field("avg_strength").type == pa.float64()
    table = pq.read_table(io.BytesIO(next(iter(s3.store.values()))))
    assert table.column("release_date").to_pylist() == ["1987-09-01", "1988-09-01"]
