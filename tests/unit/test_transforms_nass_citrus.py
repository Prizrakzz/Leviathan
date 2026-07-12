"""SILVER-F056 -- NASS citrus producer (half-orphan restore) unit + contract tests.

Covers: forecast = current_forecast; revision = current - prior (NULL when no prior); the
first-in-bronze-order tie-break for repeated rows; hlb_trend_factor is Florida all_orange ONLY and
strictly no-lookahead; natural-key uniqueness; and the INV-2 schema + SILVER-F015 shadow-publisher
wiring.
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
from leviathan.storage.paths import silver_nass_citrus_key
from leviathan.transforms.bronze_to_silver.nass_citrus import SILVER_COLUMNS, build_nass_citrus_silver


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


def _brow(season, rd, month, crop, state, col_type, value, label="June"):
    return {"release_date": rd, "season": season, "report_month": month, "crop": crop,
            "state": state, "col_label": label, "col_type": col_type,
            "value_1000_boxes": value, "source": "usda_nass_citrus"}


def test_forecast_and_revision():
    b = pd.DataFrame([
        _brow("2003-04", "2004-01-12", 1, "all_orange", "texas", "prior_forecast", 1530.0),
        _brow("2003-04", "2004-01-12", 1, "all_orange", "texas", "current_forecast", 3.0, "July"),
    ])
    s = build_nass_citrus_silver(b)
    assert list(s.columns) == SILVER_COLUMNS
    row = s.iloc[0]
    assert row["forecast_1000_boxes"] == 3.0
    assert row["revision_1000_boxes"] == pytest.approx(3.0 - 1530.0)
    assert row["source"] == "usda_nass_citrus"


def test_revision_null_without_prior():
    b = pd.DataFrame([_brow("2010-11", "2011-01-12", 1, "grapefruit", "florida",
                            "current_forecast", 20000.0)])
    s = build_nass_citrus_silver(b)
    assert s.iloc[0]["forecast_1000_boxes"] == 20000.0
    assert pd.isna(s.iloc[0]["revision_1000_boxes"])


def test_first_in_bronze_order_wins_for_repeated_current():
    # a subtotal (top) row then a detail row for the same key: the FIRST (top-line) is authoritative.
    b = pd.DataFrame([
        _brow("2008-09", "2008-11-10", 11, "all_orange", "california", "current_forecast", 64500.0, "August"),
        _brow("2008-09", "2008-11-10", 11, "all_orange", "california", "current_forecast", 44000.0, "August"),
    ])
    s = build_nass_citrus_silver(b)
    assert s.iloc[0]["forecast_1000_boxes"] == 64500.0


def test_hlb_florida_all_orange_only_and_no_lookahead():
    rows = []
    # three seasons of florida all_orange (declining) + one texas row (must stay NaN hlb).
    for i, (season, rd, fc) in enumerate([
        ("2008-09", "2008-11-10", 170000.0),
        ("2009-10", "2009-11-10", 135000.0),
        ("2010-11", "2010-11-10", 120000.0),
    ]):
        rows.append(_brow(season, rd, 11, "all_orange", "florida", "current_forecast", fc))
    rows.append(_brow("2009-10", "2009-11-10", 11, "all_orange", "texas", "current_forecast", 1500.0))
    s = build_nass_citrus_silver(pd.DataFrame(rows))
    hlb = s.set_index(["season", "state"])["hlb_trend_factor"]
    # texas is never HLB-flagged
    assert pd.isna(hlb[("2009-10", "texas")])
    # the FIRST florida season has no prior baseline -> NaN (strict no-lookahead)
    assert pd.isna(hlb[("2008-09", "florida")])
    # a later florida season is a deviation from its trailing prior-season baseline
    assert hlb[("2010-11", "florida")] == pytest.approx(120000.0 / ((170000.0 + 135000.0) / 2) - 1.0)


def test_natural_key_unique_and_empty_raises():
    b = pd.DataFrame([
        _brow("2003-04", "2004-01-12", 1, "all_orange", "texas", "current_forecast", 3.0),
        _brow("2004-05", "2005-01-12", 1, "all_orange", "texas", "current_forecast", 5.0),
    ])
    s = build_nass_citrus_silver(b)
    assert not s.duplicated(subset=["season", "release_date", "crop", "state"]).any()
    with pytest.raises(ValueError):
        build_nass_citrus_silver(pd.DataFrame(columns=list(b.columns)))


# ---------------------------------------------------------------------------
# INV-2 schema + shadow publisher.
# ---------------------------------------------------------------------------
def _valid_silver():
    # both value_columns populated so the V001 floor passes.
    rows = []
    for season, rd in [("2003-04", "2004-01-12"), ("2004-05", "2005-01-12")]:
        rows.append(_brow(season, rd, 1, "all_orange", "florida", "prior_forecast", 100.0))
        rows.append(_brow(season, rd, 1, "all_orange", "florida", "current_forecast", 120.0, "July"))
    return build_nass_citrus_silver(pd.DataFrame(rows))


def _contract():
    return load_registry().table("silver_nass_citrus")


def test_flat_publish_dry_run_writes_nothing():
    plan = build_flat_publish(df=_valid_silver(), contract=_contract(),
                              canonical_key=silver_nass_citrus_key(), auth=_dryrun_auth(),
                              s3_client=None, job="test", manifest_store=lambda k, b: None)
    manifest = plan.run()
    assert manifest.state.value == "VALIDATED"
    assert plan.schema.field("forecast_1000_boxes").type == pa.float64()
    assert plan.schema.field("hlb_trend_factor").type == pa.float64()


def test_flat_publish_shadow_non_canonical():
    s3 = _FakeS3()
    plan = build_flat_publish(df=_valid_silver(), contract=_contract(),
                              canonical_key=silver_nass_citrus_key(), auth=_shadow_auth(),
                              s3_client=s3, job="test", manifest_store=lambda k, b: None)
    plan.run()
    keys = [k for (_, k) in s3.store]
    assert len(keys) == 1 and "_shadow" in keys[0] and keys[0] != silver_nass_citrus_key()
    schema = pq.read_schema(io.BytesIO(next(iter(s3.store.values()))))
    assert schema.field("report_month").type == pa.int64()
    assert schema.field("revision_1000_boxes").type == pa.float64()
