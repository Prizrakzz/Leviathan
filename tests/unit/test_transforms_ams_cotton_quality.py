"""SILVER-F050 -- AMS cotton-quality producer (half-orphan restore) unit + contract tests.

Covers: national-only (us_total) scope selection with regional/appendix rows dropped; one wide row
per commodity x geography x season; source_pages aggregation + provenance carry; conflicting
national metrics fail closed; and the INV-2 NULL-TYPE regression -- an all-null avg_micronaire /
avg_strength column writes as ``double`` (never Arrow ``null``) through the SILVER-F015 publisher.
"""
from __future__ import annotations

import io

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.common.publish_guard import Authorization, PublishMode
from leviathan.silver.flat_producer import build_flat_publish
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_ams_cotton_key
from leviathan.transforms.bronze_to_silver.ams_cotton_quality import (
    SILVER_COLUMNS,
    build_ams_cotton_silver,
)

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
    return load_registry().table("silver_ams_cotton_quality")


def _value_valid_silver():
    # both value_columns (percent_tenderable, samples_classed) populated so the V001 floor passes;
    # avg_micronaire / avg_strength stay ALL-NULL to exercise the null-type pin.
    rows = []
    for season, pt, sc in [(1986, 44.1, 900.0), (1987, 67.0, 950.0)]:
        rows.append(_brow(season, "us_total", "national_summary", "percent_tenderable", pt, 2))
        rows.append(_brow(season, "us_total", "national_summary", "samples_classed", sc, 2))
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
