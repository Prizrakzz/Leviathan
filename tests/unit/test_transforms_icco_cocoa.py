"""SILVER-F051 -- ICCO cocoa producer (half-orphan restore) unit + contract tests.

Covers: raw QBCS JSON -> bronze; authoritative-release selection per cocoa year (latest current
release, per-metric non-null fallback, prior-vintage never overwrites current); balance-sheet
math (su_ratio, trend/dev no-lookahead + insufficient-history); natural-key uniqueness; and the
INV-2 explicit-schema + SILVER-F015 shadow-publisher wiring (all measures float64; nothing written
in dry-run; shadow lands in a NON-canonical prefix).
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
from leviathan.storage.paths import silver_icco_cocoa_key
from leviathan.transforms.bronze_to_silver.icco_cocoa import SILVER_COLUMNS, build_icco_silver
from leviathan.transforms.raw_to_bronze.icco_cocoa import BRONZE_COLUMNS, extract_icco_bronze


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


def _release(rd, cy_cur, cur, cy_prior=None, prior=None):
    doc = {"release_date": rd, "cocoa_year_current": cy_cur, "current": cur}
    if cy_prior:
        doc["cocoa_year_prior"] = cy_prior
        doc["prior"] = prior
    return doc


def _m(prod, grind, stocks, surplus):
    return {"world_production_kt": prod, "world_grindings_kt": grind,
            "end_season_stocks_kt": stocks, "surplus_deficit_kt": surplus}


# ---------------------------------------------------------------------------
# raw JSON -> bronze
# ---------------------------------------------------------------------------
def test_raw_to_bronze_shape():
    doc = _release("2012-11-30", "2011/12", _m(4052, 3921, 1864, 90),
                   "2010/11", _m(3962, 3941, 1754, -19))
    b = extract_icco_bronze(doc)
    assert list(b.columns) == BRONZE_COLUMNS
    assert len(b) == 8  # 2 vintages x 4 metrics
    assert set(b["vintage"]) == {"current", "prior"}
    cur = b[b["vintage"] == "current"].set_index("metric")["value_kt"]
    assert cur["world_production_kt"] == 4052 and cur["world_grindings_kt"] == 3921
    assert (b["source"] == "icco_qbcs").all()


def test_raw_to_bronze_missing_release_raises():
    with pytest.raises(ValueError, match="release_date"):
        extract_icco_bronze({"current": _m(1, 2, 3, 4)})


# ---------------------------------------------------------------------------
# authoritative-release selection
# ---------------------------------------------------------------------------
def test_latest_current_release_wins():
    early = extract_icco_bronze(_release("2012-02-29", "2011/12", _m(4304, 3992, 1777, -71)))
    late = extract_icco_bronze(_release("2012-11-30", "2011/12", _m(4052, 3921, 1864, 90)))
    s = build_icco_silver(pd.concat([early, late], ignore_index=True))
    row = s[s["cocoa_year"] == "2011/12"].iloc[0]
    assert row["production_kt"] == 4052 and row["grindings_kt"] == 3921  # the LATE release
    assert row["latest_release_date"] == "2012-11-30"


def test_per_metric_fallback_when_latest_drops_a_metric():
    # the latest release omits surplus_deficit -> it falls back to the earlier release that had it,
    # while production/grindings/stocks take the latest.
    early = extract_icco_bronze(_release("2015-02-27", "2014/15", _m(4168, 4164, 1570, -17)))
    late = extract_icco_bronze(_release("2015-05-29", "2014/15", _m(4168, 4164, 1570, None)))
    s = build_icco_silver(pd.concat([early, late], ignore_index=True))
    row = s[s["cocoa_year"] == "2014/15"].iloc[0]
    assert row["surplus_deficit_kt"] == -17          # fell back to the release that carried it
    assert row["latest_release_date"] == "2015-05-29"


def test_prior_vintage_never_overwrites_current():
    # 2010/11 appears as current in an early bulletin and as prior in a later one; the prior
    # figure must NOT overwrite the authoritative current value.
    cur = extract_icco_bronze(_release("2011-11-30", "2010/11", _m(4250, 3914, 1834, 347)))
    later = extract_icco_bronze(_release("2012-11-30", "2011/12", _m(4052, 3921, 1864, 90),
                                         "2010/11", _m(3962, 3941, 1754, -19)))
    s = build_icco_silver(pd.concat([cur, later], ignore_index=True))
    row = s[s["cocoa_year"] == "2010/11"].iloc[0]
    assert row["production_kt"] == 4250 and row["grindings_kt"] == 3914  # the CURRENT figure


# ---------------------------------------------------------------------------
# derived math
# ---------------------------------------------------------------------------
def test_su_ratio_and_trend_no_lookahead():
    releases = [
        _release("2010-11-30", "2009/10", _m(3600, 3500, 1400, 64)),
        _release("2011-11-30", "2010/11", _m(4250, 3914, 1834, 300)),
        _release("2012-11-30", "2011/12", _m(4052, 3921, 1864, 90)),
    ]
    b = pd.concat([extract_icco_bronze(r) for r in releases], ignore_index=True)
    s = build_icco_silver(b).sort_values("cocoa_year").reset_index(drop=True)
    # su_ratio = end_stocks / grindings
    assert s.loc[0, "su_ratio"] == pytest.approx(1400 / 3500)
    # trend: first row NaN (min_periods=2, no lookahead), dev = grindings - trend
    assert pd.isna(s.loc[0, "grindings_3yr_trend"])
    assert s.loc[1, "grindings_3yr_trend"] == pytest.approx((3500 + 3914) / 2)
    for i in range(len(s)):
        if pd.notna(s.loc[i, "grindings_3yr_trend"]):
            assert s.loc[i, "grindings_trend_dev"] == pytest.approx(
                s.loc[i, "grindings_kt"] - s.loc[i, "grindings_3yr_trend"])


def test_su_ratio_guards_zero_grindings():
    b = extract_icco_bronze(_release("2020-11-30", "2019/20", _m(4000, 0, 1500, 0)))
    s = build_icco_silver(b)
    assert pd.isna(s.iloc[0]["su_ratio"])


def test_natural_key_unique_and_columns():
    releases = [_release("2011-11-30", "2010/11", _m(4250, 3914, 1834, 300)),
                _release("2012-11-30", "2011/12", _m(4052, 3921, 1864, 90))]
    s = build_icco_silver(pd.concat([extract_icco_bronze(r) for r in releases], ignore_index=True))
    assert list(s.columns) == SILVER_COLUMNS
    assert not s.duplicated(subset=["cocoa_year"]).any()


def test_empty_bronze_raises():
    with pytest.raises(ValueError):
        build_icco_silver(pd.DataFrame(columns=BRONZE_COLUMNS))


# ---------------------------------------------------------------------------
# INV-2 schema + shadow publisher
# ---------------------------------------------------------------------------
def _silver_df():
    releases = [_release("2011-11-30", "2010/11", _m(4250, 3914, 1834, 300)),
                _release("2012-11-30", "2011/12", _m(4052, 3921, 1864, 90))]
    return build_icco_silver(pd.concat([extract_icco_bronze(r) for r in releases], ignore_index=True))


def test_flat_publish_dry_run_writes_nothing():
    plan = build_flat_publish(df=_silver_df(), contract=load_registry().table("silver_icco_cocoa"),
                              canonical_key=silver_icco_cocoa_key(), auth=_dryrun_auth(),
                              s3_client=None, job="test", manifest_store=lambda k, b: None)
    manifest = plan.run()
    assert manifest.state.value == "VALIDATED"
    # every balance-sheet measure pinned float64 (INV-2)
    for col in ("production_kt", "grindings_kt", "end_stocks_kt", "su_ratio"):
        assert plan.schema.field(col).type == pa.float64()


def test_flat_publish_shadow_lands_non_canonical():
    s3 = _FakeS3()
    plan = build_flat_publish(df=_silver_df(), contract=load_registry().table("silver_icco_cocoa"),
                              canonical_key=silver_icco_cocoa_key(), auth=_shadow_auth(),
                              s3_client=s3, job="test", manifest_store=lambda k, b: None)
    plan.run()
    keys = [k for (_, k) in s3.store]
    assert len(keys) == 1 and "_shadow" in keys[0] and keys[0] != silver_icco_cocoa_key()
    schema = pq.read_schema(io.BytesIO(next(iter(s3.store.values()))))
    assert schema.field("su_ratio").type == pa.float64()
