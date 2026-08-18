"""Unit tests for the World Bank food-CPI silver Batch task publish helper (A-W4 CLASS-B retrofit).

The task publishes the flat ``silver_food_cpi`` table through the shadow-first publisher;
``--publish-mode`` defaults to dry-run (nothing written). These tests exercise ``_publish_food_cpi``
directly with injected guard verdicts.
"""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_food_cpi_key
from leviathan.transforms.bronze_to_silver.world_bank_food_cpi import PIT_COLUMNS, SILVER_COLUMNS

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

#: One full canonical silver row, superset of every column the producer can emit. The fixture
#: PROJECTS it onto whatever the F010 contract declares (see :func:`_silver_df`).
_ROW = {
    "country_iso": "RUS", "country_name": "Russia", "year": 2015,
    "cpi_yoy_pct": 15.5, "cpi_yoy_z_5yr": 2.1, "cpi_yoy_z_10yr": 1.7,
    "cpi_available": 1, "source": "wb_food_cpi",
    # D-LD PIT anchors (present once the catalog leg of the pre-step lands).
    "data_date": "2015-12-31", "release_date": "2026-07-13",
}


def _silver_df() -> pd.DataFrame:
    """One full canonical silver row in the CONTRACT's shape (value columns non-null clear the
    0.5 floor).

    The publisher writes the contract's explicit INV-2 arrow schema and ``encode_parquet`` rejects
    any extra/missing column, so the fixture follows the contract rather than pinning a fixed
    column count -- these stay tests of the PUBLISHER on both sides of the D-LD catalog migration.
    A contract column with no value here is a loud KeyError, never a silent null.
    """
    cols = [c["name"] for c in _CONTRACT["physical_columns"]]
    return pd.DataFrame([{c: _ROW[c] for c in cols}])


def test_silver_columns_match_contract() -> None:
    """The producer's column list IS the F010 contract's -- plus, ONLY until the catalog leg of the
    D-LD pre-step lands, the two derived PIT anchors appended in order.

    ``data_date`` / ``release_date`` are producer-derived (the WIRING WAVE-1 mechanism) and the
    contract is generator-owned: it catches up via the Glue migration + registry regeneration in
    this same wave. Stating the delta explicitly means the tolerance cannot outlive that migration
    (it degenerates to strict equality the moment the contract declares them) while any OTHER
    drift between writer and contract still fails here.
    """
    contract_cols = [c["name"] for c in _CONTRACT["physical_columns"]]
    pending = [c for c in PIT_COLUMNS if c not in contract_cols]
    assert SILVER_COLUMNS == contract_cols + pending


def test_run_refuses_until_the_contract_declares_the_pit_anchors() -> None:
    """CATALOG FIRST. A producer run against a contract that has not caught up would fail deep in
    the INV-2 encode; worse, a contract that dropped the anchors would republish a table no as-of
    guard can read. The task fails closed before the first World Bank request instead."""
    pre_remedy = dict(_CONTRACT)
    pre_remedy["physical_columns"] = [c for c in _CONTRACT["physical_columns"]
                                      if c["name"] not in PIT_COLUMNS]
    with pytest.raises(ValueError) as exc:
        task.check_pit_columns_declared(pre_remedy)
    msg = str(exc.value)
    assert "data_date" in msg and "release_date" in msg
    assert "ALTER TABLE ADD COLUMNS" in msg          # the remedy is named, not just the symptom

    post_remedy = dict(_CONTRACT)
    post_remedy["physical_columns"] = list(_CONTRACT["physical_columns"]) + [
        {"name": c, "glue_type": "string", "arrow_type": "large_string",
         "parquet_physical_type": "BYTE_ARRAY", "target_arrow_type": "string", "nullable": False}
        for c in PIT_COLUMNS if c not in {x["name"] for x in _CONTRACT["physical_columns"]}
    ]
    assert task.check_pit_columns_declared(post_remedy) is None


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
