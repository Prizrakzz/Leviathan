"""Unit tests for the UNICA biweekly silver Batch task publish helper (A-W4 CLASS-B retrofit).

The task publishes FOUR flat silver tables through the shadow-first publisher; ``--publish-mode``
defaults to dry-run (nothing written). These tests exercise ``_publish_table`` directly across all
four tables and all three modes with injected guard verdicts.
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import (
    silver_unica_biweekly_release_series_key,
    silver_unica_biweekly_season_history_key,
    silver_unica_corn_ethanol_key,
    silver_unica_monthly_ethanol_sales_key,
)
from leviathan.transforms.bronze_to_silver.unica_biweekly import (
    CORN_ETHANOL_COLUMNS,
    MONTHLY_ETHANOL_SALES_COLUMNS,
    RELEASE_SERIES_COLUMNS,
    SEASON_HISTORY_COLUMNS,
)

from jobs.batch import unica_biweekly_silver_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_REGISTRY = load_registry()
_SENTINEL = b"OLD-CANONICAL-UNICA"


def _season_history_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "harvest_year": "2023_2024", "fortnight_seq": 1, "fortnight_label": "15/04",
        "fortnight_date": datetime.date(2023, 4, 15), "region": "center_south",
        "cane_crushed_t": 1000.0, "sugar_produced_t": 60.0, "ethanol_total_m3": 400.0,
        "ethanol_anhydrous_m3": 150.0, "ethanol_hydrous_m3": 250.0,
        "source_idm": "idm1", "source_position_date": "16/04/2023",
    }])


def _release_series_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "harvest_year": "2023_2024", "position_date": "16/04/2023", "region": "center_south",
        "cane_crushed_current_t": 1000.0, "cane_crushed_prior_t": 900.0,
        "sugar_produced_current_t": 60.0, "sugar_produced_prior_t": 55.0,
        "ethanol_total_current_m3": 400.0, "ethanol_total_prior_m3": 380.0,
        "ethanol_anhydrous_current_m3": 150.0, "ethanol_anhydrous_prior_m3": 140.0,
        "ethanol_hydrous_current_m3": 250.0, "ethanol_hydrous_prior_m3": 240.0,
    }])


def _corn_ethanol_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "harvest_year": "2023_2024", "fortnight_seq": 1, "fortnight_label": "15/04",
        "fortnight_date": datetime.date(2023, 4, 15),
        "anhydrous_quinzenal_kl": 10.0, "hydrous_quinzenal_kl": 20.0, "total_quinzenal_kl": 30.0,
        "anhydrous_accum_kl": 100.0, "hydrous_accum_kl": 200.0, "total_accum_kl": 300.0,
        "source_idm": "idm1", "source_position_date": "16/04/2023",
    }])


def _monthly_ethanol_sales_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "harvest_year": "2023_2024", "month_num": 4, "month_label": "abr",
        "month_date": "2023-04-01", "is_partial": False,
        "total_current_m3": 500.0, "total_prior_m3": 480.0,
        "external_current_m3": 100.0, "external_prior_m3": 90.0,
        "internal_current_m3": 400.0, "internal_prior_m3": 390.0,
        "source_idm": "idm1", "source_position_date": "16/04/2023",
    }])


# registry table -> (df builder, canonical-key fn, transform column list)
_TABLES = {
    "silver_unica_biweekly_season_history":
        (_season_history_df, silver_unica_biweekly_season_history_key, SEASON_HISTORY_COLUMNS),
    "silver_unica_biweekly_release_series":
        (_release_series_df, silver_unica_biweekly_release_series_key, RELEASE_SERIES_COLUMNS),
    "silver_unica_corn_ethanol":
        (_corn_ethanol_df, silver_unica_corn_ethanol_key, CORN_ETHANOL_COLUMNS),
    "silver_unica_monthly_ethanol_sales":
        (_monthly_ethanol_sales_df, silver_unica_monthly_ethanol_sales_key,
         MONTHLY_ETHANOL_SALES_COLUMNS),
}
_TABLE_IDS = list(_TABLES)


@pytest.mark.parametrize("registry_table", _TABLE_IDS)
def test_silver_columns_match_contract(registry_table: str) -> None:
    _df, _key, transform_cols = _TABLES[registry_table]
    contract_cols = [c["name"] for c in _REGISTRY.table(registry_table)["physical_columns"]]
    assert transform_cols == contract_cols


@pytest.mark.parametrize("registry_table", _TABLE_IDS)
def test_dry_run_writes_nothing_but_validates(registry_table: str) -> None:
    df_fn, key_fn, _cols = _TABLES[registry_table]
    contract = _REGISTRY.table(registry_table)
    state = task._publish_table(df_fn(), contract, dryrun_authorization(), None, key_fn(),
                                force_overwrite=True, bucket=contract["s3_bucket"])
    assert state is ManifestState.VALIDATED


@pytest.mark.parametrize("registry_table", _TABLE_IDS)
def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical(registry_table: str) -> None:
    df_fn, key_fn, _cols = _TABLES[registry_table]
    contract = _REGISTRY.table(registry_table)
    bucket = contract["s3_bucket"]
    canonical_key = key_fn()
    s3 = FakeS3()
    s3.store[(bucket, canonical_key)] = _SENTINEL
    etag_before = s3._etag(_SENTINEL)

    state = task._publish_table(df_fn(), contract, shadow_authorization(), s3, canonical_key,
                                force_overwrite=True, bucket=bucket)

    assert state is ManifestState.VALIDATED
    assert s3.store[(bucket, canonical_key)] == _SENTINEL
    assert s3._etag(s3.store[(bucket, canonical_key)]) == etag_before
    assert any("_shadow" in k for k in s3.keys())
    for _, key in s3.store:
        if key == canonical_key or "/_manifests/" in key:
            continue
        assert "/_shadow/" in key


@pytest.mark.parametrize("registry_table", _TABLE_IDS)
def test_canonical_overwrites_the_silver_object(registry_table: str) -> None:
    df_fn, key_fn, _cols = _TABLES[registry_table]
    contract = _REGISTRY.table(registry_table)
    bucket = contract["s3_bucket"]
    canonical_key = key_fn()
    s3 = FakeS3()
    s3.store[(bucket, canonical_key)] = _SENTINEL

    state = task._publish_table(df_fn(), contract, canonical_authorization(), s3, canonical_key,
                                force_overwrite=True, bucket=bucket)

    assert state is ManifestState.CERTIFIED
    assert (bucket, canonical_key) in s3.store
    assert s3.store[(bucket, canonical_key)] != _SENTINEL
