"""SILVER-F051 -- ICCO cocoa producer unit + contract tests.

Covers: the legacy raw QBCS JSON -> bronze (kept, called by nothing in the chain); the served silver
built from the RELEASES table (latest whole row per cocoa year, no per-metric splice, a restatement is
never a row); balance-sheet math (su_ratio, trend/dev no-lookahead + insufficient-history);
natural-key uniqueness; and the INV-2 explicit-schema + SILVER-F015 shadow-publisher wiring (all
measures float64; nothing written in dry-run; shadow lands in a NON-canonical prefix).

MOVED 2026-09-29 (data repairs ICCO-1, ICCO-3, ICCO-4): ``build_icco_silver`` now reads
``silver_icco_cocoa_releases`` (one row per season per bulletin, built from the banked PAGES), not
the positional bronze.  Every pin that fed it bronze now feeds it release rows; each keeps its claim,
except the one whose claim WAS the defect (the per-metric fallback), which says so.
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
from leviathan.transforms.bronze_to_silver.icco_cocoa import (
    RELEASES_COLUMNS,
    SILVER_COLUMNS,
    build_icco_silver,
)
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
    """A legacy QBCS summary JSON (the shape extract_icco_bronze reads)."""
    doc = {"release_date": rd, "cocoa_year_current": cy_cur, "current": cur}
    if cy_prior:
        doc["cocoa_year_prior"] = cy_prior
        doc["prior"] = prior
    return doc


def _m(prod, grind, stocks, surplus):
    return {"world_production_kt": prod, "world_grindings_kt": grind,
            "end_season_stocks_kt": stocks, "surplus_deficit_kt": surplus}


def _row(rd, cy, prod, grind, stocks, surplus, *, missing=None, source="dateline"):
    """One silver_icco_cocoa_releases row: what the bulletin of ``rd`` stated about season ``cy``."""
    row = {c: None for c in RELEASES_COLUMNS}
    row.update(release_date=rd, release_date_source=source, cocoa_year=cy,
               bulletin_volume="XXXVIII", bulletin_issue=int(rd[5:7]) // 3 + 1,
               production_kt=prod, grindings_kt=grind, end_stocks_kt=stocks,
               surplus_deficit_kt=surplus, missing_reason=missing)
    return row


def _rel(*rows):
    return pd.DataFrame(list(rows), columns=RELEASES_COLUMNS)


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
# authoritative-release selection (from the releases table)
# ---------------------------------------------------------------------------
def test_latest_current_release_wins():
    s = build_icco_silver(_rel(_row("2012-02-29", "2011/12", 4304, 3992, 1777, -71),
                               _row("2012-11-30", "2011/12", 4052, 3921, 1864, 90)))
    row = s[s["cocoa_year"] == "2011/12"].iloc[0]
    assert row["production_kt"] == 4052 and row["grindings_kt"] == 3921  # the LATE release
    assert row["latest_release_date"] == "2012-11-30"


def test_per_metric_fallback_when_latest_drops_a_metric():
    """MOVED, AND ITS CLAIM REVERSED BY THE LIST (ICCO-3, T-ICCO-9).  This pin asserted that a metric
    the latest release omits "falls back to the release that carried it" -- the per-metric splice that
    minted the served 2014/15 row out of May-2015 production and a Feb-2015 surplus (production x 0.99
    - grindings - surplus = -20.7 kt, the one row of fifteen that failed the identity).  The row is now
    the latest release's WHOLE row: the omitted metric stays MISSING.  Kept from the old claim: the
    latest release is the one read, and latest_release_date names it."""
    s = build_icco_silver(_rel(_row("2015-02-27", "2014/15", 4232, 4207, 1609, -17),
                               _row("2015-05-29", "2014/15", 4168, 4164, 1570, None)))
    row = s[s["cocoa_year"] == "2014/15"].iloc[0]
    assert pd.isna(row["surplus_deficit_kt"])        # never borrowed from Feb-2015
    assert row["production_kt"] == 4168
    assert row["latest_release_date"] == "2015-05-29"


def test_prior_vintage_never_overwrites_current():
    """MOVED (cause: ICCO-2(b) -- the "prior" vintage was the same season's previous estimate filed
    under the prior season's name, so it no longer exists).  Claim kept in the releases model: a
    figure the page marks a/ (restated from an earlier bulletin) is never a row, so it can never
    overwrite what a release itself stated; the season carries its LATEST statement, here 2010/11 as
    revised in Nov-2012."""
    s = build_icco_silver(_rel(_row("2011-11-30", "2010/11", 4250, 3914, 1834, 347),
                               _row("2012-11-30", "2010/11", 4313, 3929, 1774, 341),
                               _row("2012-11-30", "2011/12", 4052, 3921, 1864, 90)))
    row = s[s["cocoa_year"] == "2010/11"].iloc[0]
    assert row["production_kt"] == 4313 and row["latest_release_date"] == "2012-11-30"


def test_a_withheld_row_is_never_a_figure_of_the_season():
    s = build_icco_silver(_rel(_row("2026-05-29", "2024/25", 4723, 4628, 1320, 48),
                               _row("2026-08-31", "2025/26", None, None, None, None, missing="withheld")))
    assert list(s["cocoa_year"]) == ["2024/25"]


# ---------------------------------------------------------------------------
# derived math
# ---------------------------------------------------------------------------
def test_su_ratio_and_trend_no_lookahead():
    s = build_icco_silver(_rel(_row("2010-11-30", "2009/10", 3600, 3500, 1400, 64),
                               _row("2011-11-30", "2010/11", 4250, 3914, 1834, 300),
                               _row("2012-11-30", "2011/12", 4052, 3921, 1864, 90)))
    s = s.sort_values("cocoa_year").reset_index(drop=True)
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
    s = build_icco_silver(_rel(_row("2020-11-30", "2019/20", 4000, 0, 1500, 0)))
    assert pd.isna(s.iloc[0]["su_ratio"])


def test_natural_key_unique_and_columns():
    s = build_icco_silver(_rel(_row("2011-11-30", "2010/11", 4250, 3914, 1834, 300),
                               _row("2012-11-30", "2011/12", 4052, 3921, 1864, 90)))
    assert list(s.columns) == SILVER_COLUMNS
    assert not s.duplicated(subset=["cocoa_year"]).any()


def test_empty_bronze_raises():
    """MOVED (cause: the silver reads the releases table).  Claim kept: nothing to build from raises."""
    with pytest.raises(ValueError):
        build_icco_silver(pd.DataFrame(columns=RELEASES_COLUMNS))


# ---------------------------------------------------------------------------
# INV-2 schema + shadow publisher
# ---------------------------------------------------------------------------
def _silver_df():
    return build_icco_silver(_rel(_row("2011-11-30", "2010/11", 4250, 3914, 1834, 300),
                                  _row("2012-11-30", "2011/12", 4052, 3921, 1864, 90)))


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
