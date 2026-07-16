"""Unit tests for the MODIS NDVI bronze->silver Batch task publish helper (A-W4 CLASS-B retrofit).

``silver_modis_ndvi`` is registered FLAT (partition_keys: []) but the producer writes MANY objects
(one per country/region/year), so the single-object ``build_flat_publish`` plan does not fit; the
write routes through the shadow-first publisher (ShadowPublisher, FLAT strategy) with a StagedObject
per output. ``--publish-mode`` defaults to dry-run (nothing written); these tests exercise
``_publish_modis`` directly with injected guard verdicts.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_modis_ndvi_key
from leviathan.transforms.bronze_to_silver.modis_ndvi import _empty_silver

from jobs.batch import modis_ndvi_bronze_to_silver_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_CONTRACT = load_registry().table("silver_modis_ndvi")
_BUCKET = _CONTRACT["s3_bucket"]
_COMMODITY = "corn_cbot"
_SENTINEL = b"OLD-CANONICAL-MODIS-NDVI"


def _silver_row(country: str, region: str, year: int, observed: date) -> dict[str, object]:
    return {
        "date": observed, "year": year, "period": 1,
        "commodity": _COMMODITY, "country": country, "region": region,
        "latitude": 42.0, "longitude": -93.5,
        "ndvi_raw": 0.72, "ndvi": 0.70, "pixel_reliability": 0,
        "ndvi_z_score": 1.1, "baseline_mean": 0.65, "baseline_std": 0.05,
        "ingest_date": "2026-06-01",
    }


def _two_object_silver() -> pd.DataFrame:
    return pd.DataFrame([
        _silver_row("united_states", "IA", 2020, date(2020, 6, 1)),
        _silver_row("united_states", "IA", 2020, date(2020, 6, 17)),
        _silver_row("united_states", "IL", 2019, date(2019, 6, 1)),
    ])[list(_empty_silver().columns)]


def test_silver_columns_match_contract() -> None:
    # The FLAT modis body carries exactly the contracted physical columns (no partition keys).
    contract_cols = [c["name"] for c in _CONTRACT["physical_columns"]]
    assert list(_empty_silver().columns) == contract_cols


def test_dry_run_writes_nothing_but_validates() -> None:
    state = task._publish_modis(_two_object_silver(), _COMMODITY, _CONTRACT, dryrun_authorization(),
                                None, _BUCKET, force_overwrite=True)
    assert state is ManifestState.VALIDATED


def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical() -> None:
    s3 = FakeS3()
    canonical_key = silver_modis_ndvi_key(_COMMODITY, "united_states", "IA", 2020)
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL
    etag_before = s3._etag(_SENTINEL)

    state = task._publish_modis(_two_object_silver(), _COMMODITY, _CONTRACT, shadow_authorization(),
                                s3, _BUCKET, force_overwrite=True)

    assert state is ManifestState.VALIDATED
    assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL
    assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before
    assert any("_shadow" in k for k in s3.keys())
    for _, key in s3.store:
        if key == canonical_key or "/_manifests/" in key:
            continue
        assert "/_shadow/" in key


def test_canonical_overwrites_the_modis_object() -> None:
    s3 = FakeS3()
    canonical_key = silver_modis_ndvi_key(_COMMODITY, "united_states", "IA", 2020)
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL

    state = task._publish_modis(_two_object_silver(), _COMMODITY, _CONTRACT, canonical_authorization(),
                                s3, _BUCKET, force_overwrite=True)

    assert state is ManifestState.CERTIFIED
    assert (_BUCKET, canonical_key) in s3.store
    assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL
    # the second (country, region, year) object was also promoted.
    assert (_BUCKET, silver_modis_ndvi_key(_COMMODITY, "united_states", "IL", 2019)) in s3.store
