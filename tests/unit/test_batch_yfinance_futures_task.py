"""Unit tests for the yfinance futures silver Batch task publish helper (A-W4 CLASS-B retrofit).

The task publishes the flat ``silver_futures_prices`` table through the shadow-first publisher;
``--publish-mode`` defaults to dry-run (nothing written). These tests exercise ``_publish_futures``
directly with injected guard verdicts.
"""
from __future__ import annotations

import pandas as pd
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_futures_prices_key
from leviathan.transforms.bronze_to_silver.yfinance_futures import SILVER_COLUMNS

from jobs.batch import yfinance_futures_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_CONTRACT = load_registry().table("silver_futures_prices")
_BUCKET = _CONTRACT["s3_bucket"]
_SENTINEL = b"OLD-CANONICAL-FUTURES"


def _silver_df() -> pd.DataFrame:
    """One full 11-column canonical silver row (v1.5 adds `unit`); date is a timestamp for the
    timestamp[us] schema."""
    return pd.DataFrame([{
        "date": pd.Timestamp("2012-07-20"), "leviathan_slug": "corn_cbot",
        "close": 800.0, "log_return": 0.012, "price_z_2yr": 2.0,
        "realized_vol_30d": 0.31, "momentum_60d": 0.15, "momentum_1yr": 0.42,
        "vol_regime": 1, "source": "yfinance", "unit": "US cents/bushel",
    }])


def test_silver_columns_match_contract() -> None:
    contract_cols = [c["name"] for c in _CONTRACT["physical_columns"]]
    assert SILVER_COLUMNS == contract_cols


def test_dry_run_writes_nothing_but_validates() -> None:
    state = task._publish_futures(_silver_df(), _CONTRACT, dryrun_authorization(), None, _BUCKET,
                                  force_overwrite=True)
    assert state is ManifestState.VALIDATED


def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical() -> None:
    s3 = FakeS3()
    canonical_key = silver_futures_prices_key()
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL
    etag_before = s3._etag(_SENTINEL)

    state = task._publish_futures(_silver_df(), _CONTRACT, shadow_authorization(), s3, _BUCKET,
                                  force_overwrite=True)

    assert state is ManifestState.VALIDATED
    assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL
    assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before
    assert any("_shadow" in k for k in s3.keys())
    for _, key in s3.store:
        if key == canonical_key or "/_manifests/" in key:
            continue
        assert "/_shadow/" in key


def test_canonical_overwrites_the_futures_silver_object() -> None:
    s3 = FakeS3()
    canonical_key = silver_futures_prices_key()
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL

    state = task._publish_futures(_silver_df(), _CONTRACT, canonical_authorization(), s3, _BUCKET,
                                  force_overwrite=True)

    assert state is ManifestState.CERTIFIED
    assert (_BUCKET, canonical_key) in s3.store
    assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL
