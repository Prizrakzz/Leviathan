"""Unit tests for the CFTC COT silver Batch task publish helper (A-W4 CLASS-B retrofit).

The task publishes the flat ``silver_cot`` table through the shadow-first publisher; ``--publish-mode``
defaults to dry-run (nothing written). These tests exercise ``_publish_cot`` directly with injected
guard verdicts, proving the three-mode INV-6 contract.
"""
from __future__ import annotations

import pandas as pd
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_cot_key
from leviathan.transforms.bronze_to_silver.cftc_cot import SILVER_COLUMNS

from jobs.batch import cftc_cot_silver_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_CONTRACT = load_registry().table("silver_cot")
_BUCKET = _CONTRACT["s3_bucket"]          # where build_flat_publish writes (contract-pinned)
_SENTINEL = b"OLD-CANONICAL-COT"


def _silver_df() -> pd.DataFrame:
    """One full 11-column canonical silver row (value columns non-null clear the 0.5 floor)."""
    return pd.DataFrame([{
        "report_date": "2012-06-19", "leviathan_slug": "corn_cbot",
        "open_interest": 1_600_000, "mm_long": 400_000, "mm_short": 100_000,
        "mm_spread": 50_000, "mm_net": 300_000, "mm_pct_oi": 18.75,
        "mm_net_z_3yr": 1.9, "mm_pct_oi_z_3yr": 1.8, "source": "cftc_cot",
    }])


def test_silver_columns_match_contract() -> None:
    contract_cols = [c["name"] for c in _CONTRACT["physical_columns"]]
    assert SILVER_COLUMNS == contract_cols


def test_dry_run_writes_nothing_but_validates() -> None:
    # main() passes s3_client=None in dry-run; the plan reaches VALIDATED with nothing written.
    state = task._publish_cot(_silver_df(), _CONTRACT, dryrun_authorization(), None, _BUCKET,
                              force_overwrite=True)
    assert state is ManifestState.VALIDATED


def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical() -> None:
    s3 = FakeS3()
    canonical_key = silver_cot_key()
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL          # pre-seed a canonical sentinel
    etag_before = s3._etag(_SENTINEL)

    state = task._publish_cot(_silver_df(), _CONTRACT, shadow_authorization(), s3, _BUCKET,
                              force_overwrite=True)

    assert state is ManifestState.VALIDATED
    assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL              # canonical untouched
    assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before  # etag identical
    assert any("_shadow" in k for k in s3.keys())                      # staged under _shadow/
    # every data object other than canonical + the control-plane manifest lives under _shadow/
    for _, key in s3.store:
        if key == canonical_key or "/_manifests/" in key:
            continue
        assert "/_shadow/" in key


def test_canonical_overwrites_the_cot_silver_object() -> None:
    s3 = FakeS3()
    canonical_key = silver_cot_key()
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL

    state = task._publish_cot(_silver_df(), _CONTRACT, canonical_authorization(), s3, _BUCKET,
                              force_overwrite=True)

    assert state is ManifestState.CERTIFIED
    assert (_BUCKET, canonical_key) in s3.store
    assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL   # canonical overwritten
