"""SILVER-F057 -- NOAA ONI producer (full-orphan rebuild) unit + contract tests.

Covers the plan's required cases: exact (year, month, season) uniqueness; ONI phase-boundary
classification; source sentinel handling; each regional La Nina flag firing on the correct
historical episodes; chronological lag columns deterministic + no-lookahead. Plus the INV-2
explicit-schema + SILVER-F015 shadow-publisher wiring (dry-run writes nothing; shadow lands in a
NON-canonical prefix with int64 flags -- never arrow-null).

The golden fixture ``tests/fixtures/noaa_oni/oni.ascii.sample.txt`` is a REAL contiguous excerpt
of the NOAA CPC record (DJF 1950 .. NDJ 1999, incl. the 1997/98 super El Nino); the transform
reproduces the live physical silver bit-for-bit (validated separately against all 915 rows).
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from leviathan.common.publish_guard import Authorization, PublishMode
from leviathan.silver.flat_producer import build_flat_publish
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_oni_key
from leviathan.transforms.bronze_to_silver.noaa_oni import (
    SILVER_COLUMNS,
    build_oni_silver,
    classify_oni_phase,
)
from leviathan.transforms.raw_to_bronze.noaa_oni import (
    SEASON_TO_MONTH,
    extract_oni_bronze,
)

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "noaa_oni" / "oni.ascii.sample.txt"


# ---------------------------------------------------------------------------
# In-memory S3 so the F002 network guard never fires (shadow-write assertions).
# ---------------------------------------------------------------------------
class _FakeS3:
    def __init__(self):
        self.store: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[(Bucket, Key)] = bytes(Body)
        return {"ETag": '"x"'}

    def copy_object(self, Bucket, Key, CopySource, **kw):
        self.store[(Bucket, Key)] = self.store[(CopySource["Bucket"], CopySource["Key"])]
        return {}


def _dryrun_auth() -> Authorization:
    return Authorization(mode=PublishMode.DRY_RUN, may_mutate_canonical=False, readiness=True,
                         reason="test")


def _shadow_auth() -> Authorization:
    return Authorization(mode=PublishMode.SHADOW, may_mutate_canonical=False, readiness=True,
                         reason="test")


@pytest.fixture(scope="module")
def bronze() -> pd.DataFrame:
    return extract_oni_bronze(_FIXTURE.read_bytes())


@pytest.fixture(scope="module")
def silver(bronze) -> pd.DataFrame:
    return build_oni_silver(bronze)


# ---------------------------------------------------------------------------
# Bronze parse.
# ---------------------------------------------------------------------------
def test_bronze_parses_season_to_center_month(bronze):
    assert list(bronze.columns) == ["year", "month", "season", "oni_total", "oni_anom", "source"]
    assert len(bronze) == 600  # 50 years x 12 overlapping seasons
    # every season maps to its documented center month
    got = bronze.groupby("season")["month"].agg(lambda s: sorted(set(s))).to_dict()
    assert got == {k: [v] for k, v in SEASON_TO_MONTH.items()}
    assert (bronze["source"] == "noaa_oni").all()
    # the first real row is DJF 1950 with anom -1.53
    first = bronze.iloc[0]
    assert (first["year"], first["month"], first["season"]) == (1950, 1, "DJF")
    assert first["oni_anom"] == pytest.approx(-1.53)


def test_bronze_sentinel_stays_null():
    raw = b" SEAS  YR   TOTAL   ANOM\n  DJF 2050  -99.90  -99.90\n  JFM 2050  25.00   0.30\n"
    df = extract_oni_bronze(raw)
    assert df.iloc[0]["oni_anom"] is None or pd.isna(df.iloc[0]["oni_anom"])
    assert df.iloc[0]["oni_total"] is None or pd.isna(df.iloc[0]["oni_total"])
    assert df.iloc[1]["oni_anom"] == pytest.approx(0.30)


def test_bronze_empty_raises():
    with pytest.raises(ValueError):
        extract_oni_bronze(b" SEAS  YR   TOTAL   ANOM\n")


# ---------------------------------------------------------------------------
# Phase boundary classification (inclusive at +/-0.5).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("anom,expected", [
    (0.5, "el_nino"), (0.51, "el_nino"), (2.4, "el_nino"),
    (0.49, "neutral"), (0.0, "neutral"), (-0.49, "neutral"),
    (-0.5, "la_nina"), (-0.51, "la_nina"), (-1.53, "la_nina"),
    (None, "neutral"), (float("nan"), "neutral"),
])
def test_phase_boundary(anom, expected):
    assert classify_oni_phase(anom) == expected


def test_flags_track_phase(silver):
    assert (silver["el_nino_flag"] == (silver["phase"] == "el_nino").astype(int)).all()
    assert (silver["la_nina_flag"] == (silver["phase"] == "la_nina").astype(int)).all()
    # never both set
    assert (silver["el_nino_flag"] + silver["la_nina_flag"] <= 1).all()


# ---------------------------------------------------------------------------
# Natural key uniqueness.
# ---------------------------------------------------------------------------
def test_natural_key_unique(silver):
    assert not silver.duplicated(subset=["year", "month", "season"]).any()
    assert list(silver.columns) == SILVER_COLUMNS


def test_duplicate_bronze_raises(bronze):
    dup = pd.concat([bronze, bronze.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        build_oni_silver(dup)


# ---------------------------------------------------------------------------
# Lags: backward-looking, deterministic, first N NaN.
# ---------------------------------------------------------------------------
def test_lags_no_lookahead_and_deterministic(bronze, silver):
    anom = silver["oni_anom"].reset_index(drop=True)
    for n in (3, 6, 9, 12):
        col = silver[f"oni_lag{n}"].reset_index(drop=True)
        assert col.head(n).isna().all()                       # first N are NaN (no synthesis)
        # lag N at row i equals the anomaly N rows earlier
        assert col.iloc[n:].reset_index(drop=True).equals(anom.iloc[:-n].reset_index(drop=True))
    # deterministic across a rebuild
    again = build_oni_silver(bronze)
    assert again["oni_lag6"].equals(silver["oni_lag6"])


# ---------------------------------------------------------------------------
# Regional La Nina flags fire on the correct months / episodes.
# ---------------------------------------------------------------------------
def test_regional_flags_month_gating():
    # a synthetic La Nina spanning a full year: brazil fires only DJF-core (12,1,2); argentina all.
    rows = [{"year": 2000, "month": m, "season": f"S{m:02d}", "oni_anom": -1.0,
             "oni_total": 25.0, "source": "noaa_oni"} for m in range(1, 13)]
    s = build_oni_silver(pd.DataFrame(rows))
    braz = set(s[s["la_nina_brazil_flag"] == 1]["month"])
    arg = set(s[s["argentina_la_nina_flag"] == 1]["month"])
    assert braz == {1, 2, 12}
    assert arg == set(range(1, 13))
    # neither region flag fires when there is no La Nina
    neutral = build_oni_silver(pd.DataFrame(
        [{"year": 2001, "month": m, "season": f"S{m:02d}", "oni_anom": 0.0,
          "oni_total": 26.0, "source": "noaa_oni"} for m in range(1, 13)]))
    assert neutral["la_nina_brazil_flag"].sum() == 0
    assert neutral["argentina_la_nina_flag"].sum() == 0


def test_known_episode_1997_98_super_el_nino(silver):
    # OND 1997 was the peak of the 1997/98 super El Nino (ONI ~ +2.4).
    peak = silver[(silver["year"] == 1997) & (silver["month"] == 11)].iloc[0]
    assert peak["season"] == "OND"
    assert peak["oni_anom"] == pytest.approx(2.4)
    assert peak["phase"] == "el_nino" and peak["el_nino_flag"] == 1 and peak["la_nina_flag"] == 0
    # the 1950 La Nina onset: DJF/JFM/NDJ fire the Brazil DJF-core flag; FMA (month 3) does not.
    djf50 = silver[(silver["year"] == 1950) & (silver["month"] == 1)].iloc[0]
    fma50 = silver[(silver["year"] == 1950) & (silver["month"] == 3)].iloc[0]
    assert djf50["la_nina_brazil_flag"] == 1 and djf50["argentina_la_nina_flag"] == 1
    assert fma50["la_nina_brazil_flag"] == 0 and fma50["argentina_la_nina_flag"] == 1


# ---------------------------------------------------------------------------
# INV-2 schema + SILVER-F015 shadow publisher wiring.
# ---------------------------------------------------------------------------
def _contract():
    return load_registry().table("silver_noaa_oni")


def test_flat_publish_dry_run_writes_nothing(silver):
    plan = build_flat_publish(df=silver, contract=_contract(), canonical_key=silver_oni_key(),
                              auth=_dryrun_auth(), s3_client=None, job="test",
                              manifest_store=lambda k, b: None)
    manifest = plan.run()
    assert manifest.state.value == "VALIDATED"           # halts before any canonical touch
    assert manifest.validation_result["ok"] is True
    # INV-2: flags pinned int64, anomaly float64, season/phase string -- never arrow-null.
    assert plan.schema.field("el_nino_flag").type == pytest.importorskip("pyarrow").int64()
    assert plan.schema.field("oni_anom").type == pytest.importorskip("pyarrow").float64()


def test_flat_publish_shadow_lands_in_non_canonical_prefix(silver):
    s3 = _FakeS3()
    plan = build_flat_publish(df=silver, contract=_contract(), canonical_key=silver_oni_key(),
                              auth=_shadow_auth(), s3_client=s3, job="test",
                              manifest_store=lambda k, b: None)
    manifest = plan.run()
    assert manifest.state.value == "VALIDATED"
    # exactly one object, under a _shadow marker, NEVER the canonical silver key
    keys = [k for (_, k) in s3.store]
    assert len(keys) == 1
    assert "_shadow" in keys[0]
    assert keys[0] != silver_oni_key()
    # the shadow parquet carries the pinned INV-2 schema (int64 flags, not arrow-null)
    body = s3.store[next(iter(s3.store))]
    schema = pq.read_schema(io.BytesIO(body))
    assert schema.field("el_nino_flag").type == pytest.importorskip("pyarrow").int64()
    assert schema.field("la_nina_brazil_flag").type == pytest.importorskip("pyarrow").int64()
