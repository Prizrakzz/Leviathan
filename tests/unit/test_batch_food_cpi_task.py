"""Unit tests for the World Bank food-CPI silver Batch task publish helper (A-W4 CLASS-B retrofit).

The task publishes the flat ``silver_food_cpi`` table through the shadow-first publisher;
``--publish-mode`` defaults to dry-run (nothing written). These tests exercise ``_publish_food_cpi``
directly with injected guard verdicts.
"""
from __future__ import annotations

import pandas as pd
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_food_cpi_key
from leviathan.transforms.bronze_to_silver.world_bank_food_cpi import SILVER_COLUMNS

from jobs.batch import food_cpi_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_CONTRACT = load_registry().table("silver_food_cpi")
_BUCKET = _CONTRACT["s3_bucket"]
_SENTINEL = b"OLD-CANONICAL-FOOD-CPI"


def _silver_df() -> pd.DataFrame:
    """One full 8-column canonical silver row (value columns non-null clear the 0.5 floor)."""
    return pd.DataFrame([{
        "country_iso": "RUS", "country_name": "Russia", "year": 2015,
        "cpi_yoy_pct": 15.5, "cpi_yoy_z_5yr": 2.1, "cpi_yoy_z_10yr": 1.7,
        "cpi_available": 1, "source": "wb_food_cpi",
    }])


def test_silver_columns_match_contract() -> None:
    contract_cols = [c["name"] for c in _CONTRACT["physical_columns"]]
    assert SILVER_COLUMNS == contract_cols


def test_dry_run_writes_nothing_but_validates() -> None:
    state = task._publish_food_cpi(_silver_df(), _CONTRACT, dryrun_authorization(), None, _BUCKET,
                                   force_overwrite=True)
    assert state is ManifestState.VALIDATED


def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical() -> None:
    s3 = FakeS3()
    canonical_key = silver_food_cpi_key()
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL
    etag_before = s3._etag(_SENTINEL)

    state = task._publish_food_cpi(_silver_df(), _CONTRACT, shadow_authorization(), s3, _BUCKET,
                                   force_overwrite=True)

    assert state is ManifestState.VALIDATED
    assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL
    assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before
    assert any("_shadow" in k for k in s3.keys())
    for _, key in s3.store:
        if key == canonical_key or "/_manifests/" in key:
            continue
        assert "/_shadow/" in key


def test_canonical_overwrites_the_food_cpi_silver_object() -> None:
    s3 = FakeS3()
    canonical_key = silver_food_cpi_key()
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL

    state = task._publish_food_cpi(_silver_df(), _CONTRACT, canonical_authorization(), s3, _BUCKET,
                                   force_overwrite=True)

    assert state is ManifestState.CERTIFIED
    assert (_BUCKET, canonical_key) in s3.store
    assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL
