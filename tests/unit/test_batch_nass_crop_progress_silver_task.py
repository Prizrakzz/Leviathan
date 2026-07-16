"""Unit tests for the NASS crop-progress silver Batch task (selection helpers + A-W4 CLASS-B retrofit).

``silver_nass_crop_progress`` is partitioned (projected); the A-W4 retrofit routes the
per-(commodity, year) write through the shadow-first publisher (ShadowPublisher, PROJECTED strategy)
rather than the flat ``build_flat_publish`` path -- the parquet body carries the ``year`` partition
column. ``--publish-mode`` defaults to dry-run (nothing written); the fixture tests exercise
``_publish_nass_crop_progress`` directly with injected guard verdicts.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_nass_crop_progress_key

from jobs.batch import nass_crop_progress_silver_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_CONTRACT = load_registry().table("silver_nass_crop_progress")
_BUCKET = _CONTRACT["s3_bucket"]
_SENTINEL = b"OLD-CANONICAL-NASS-CROP-PROGRESS"


def _silver_row(slug: str, state: str, year: int, observed_date: date) -> dict[str, object]:
    return {
        "leviathan_slug": slug,
        "state": state,
        "year": year,
        "date": observed_date,
        "week_of_year": observed_date.isocalendar().week,
        "pct_planted": 1.0,
        "pct_emerged": None,
        "pct_good_excellent": None,
        "pct_poor_very_poor": None,
        "pct_harvested": None,
        "source": "usda_nass",
    }


def _two_partition_final() -> pd.DataFrame:
    return pd.DataFrame([
        _silver_row("corn_cbot", "IA", 2024, date(2024, 4, 7)),
        _silver_row("corn_cbot", "IL", 2024, date(2024, 4, 14)),
        _silver_row("soybeans_cbot", "IA", 2023, date(2023, 5, 7)),
    ])[task.OUTPUT_COLUMNS]


# ---------------------------------------------------------------------------
# Selection / transform helpers
# ---------------------------------------------------------------------------

def test_select_keys_filters_crop_progress_bronze_commodity_and_year() -> None:
    keys = [
        "bronze/production/source=usda_nass/series=crop_progress/commodity=corn_cbot/year=2024/part-000.parquet",
        "bronze/production/source=usda_nass/series=crop_progress/commodity=corn_cbot/year=2023/part-000.parquet",
        "bronze/production/source=usda_nass/series=annual/commodity=corn_cbot/year=2024/part-000.parquet",
    ]
    selected = task._select_keys(keys, bronze_commodities="corn_cbot", years="2024", limit=0)
    assert selected == [keys[0]]


def test_select_keys_limit_keeps_sorted_prefix() -> None:
    keys = [
        "bronze/production/source=usda_nass/series=crop_progress/commodity=corn_cbot/year=2025/part-000.parquet",
        "bronze/production/source=usda_nass/series=crop_progress/commodity=corn_cbot/year=2023/part-000.parquet",
        "bronze/production/source=usda_nass/series=crop_progress/commodity=corn_cbot/year=2024/part-000.parquet",
    ]
    selected = task._select_keys(keys, bronze_commodities="all", years="all", limit=2)
    assert ["/year=2023/", "/year=2024/"] == [
        f"/year={key.split('/year=')[1].split('/')[0]}/" for key in selected
    ]


def test_transform_keys_workers_match_sequential(monkeypatch) -> None:
    keys = ["key-a", "key-b"]

    def fake_load(_bucket: str, key: str, _region: str) -> pd.DataFrame:
        state = "IA" if key == "key-a" else "IL"
        return pd.DataFrame([_silver_row("corn_cbot", state, 2024, date(2024, 4, 7))])

    monkeypatch.setattr(task, "_load_and_transform", fake_load)

    sequential, sequential_errors = task._transform_keys("bucket", keys, "region", workers=1)
    parallel, parallel_errors = task._transform_keys("bucket", keys, "region", workers=2)

    sequential_df = pd.concat(sequential).sort_values("state").reset_index(drop=True)
    parallel_df = pd.concat(parallel).sort_values("state").reset_index(drop=True)

    assert sequential_errors == 0
    assert parallel_errors == 0
    pd.testing.assert_frame_equal(sequential_df, parallel_df)


def test_transform_keys_ignores_empty_outputs(monkeypatch) -> None:
    keys = ["empty", "non-empty"]

    def fake_load(_bucket: str, key: str, _region: str) -> pd.DataFrame:
        if key == "empty":
            return pd.DataFrame(columns=task.OUTPUT_COLUMNS)
        return pd.DataFrame([_silver_row("corn_cbot", "IA", 2024, date(2024, 4, 7))])

    monkeypatch.setattr(task, "_load_and_transform", fake_load)

    frames, errors = task._transform_keys("bucket", keys, "region", workers=2)

    assert errors == 0
    assert len(frames) == 1
    assert frames[0].iloc[0]["state"] == "IA"


def test_transform_keys_aggregates_worker_errors(monkeypatch) -> None:
    keys = ["good", "bad"]

    def fake_load(_bucket: str, key: str, _region: str) -> pd.DataFrame:
        if key == "bad":
            raise ValueError("boom")
        return pd.DataFrame([_silver_row("corn_cbot", "IA", 2024, date(2024, 4, 7))])

    monkeypatch.setattr(task, "_load_and_transform", fake_load)

    frames, errors = task._transform_keys("bucket", keys, "region", workers=2)

    assert errors == 1
    assert len(frames) == 1
    assert frames[0].iloc[0]["state"] == "IA"


# ---------------------------------------------------------------------------
# Shadow-first publish (A-W4 CLASS-B retrofit)
# ---------------------------------------------------------------------------

def test_silver_columns_match_contract() -> None:
    # Every contracted physical column is produced; the only extra body column is the
    # ``year`` partition key (carried in the parquet body AND the object path).
    contract_cols = [c["name"] for c in _CONTRACT["physical_columns"]]
    assert set(contract_cols) <= set(task.OUTPUT_COLUMNS)
    assert set(task.OUTPUT_COLUMNS) - set(contract_cols) == {"year"}


def test_dry_run_writes_nothing_but_validates() -> None:
    state = task._publish_nass_crop_progress(_two_partition_final(), _CONTRACT, dryrun_authorization(),
                                             None, _BUCKET, force_overwrite=True)
    assert state is ManifestState.VALIDATED


def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical() -> None:
    s3 = FakeS3()
    canonical_key = silver_nass_crop_progress_key("corn_cbot", 2024)
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL
    etag_before = s3._etag(_SENTINEL)

    state = task._publish_nass_crop_progress(_two_partition_final(), _CONTRACT, shadow_authorization(),
                                             s3, _BUCKET, force_overwrite=True)

    assert state is ManifestState.VALIDATED
    assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL
    assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before
    assert any("_shadow" in k for k in s3.keys())
    for _, key in s3.store:
        if key == canonical_key or "/_manifests/" in key:
            continue
        assert "/_shadow/" in key


def test_canonical_overwrites_the_nass_crop_progress_partition() -> None:
    s3 = FakeS3()
    canonical_key = silver_nass_crop_progress_key("corn_cbot", 2024)
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL

    state = task._publish_nass_crop_progress(_two_partition_final(), _CONTRACT, canonical_authorization(),
                                             s3, _BUCKET, force_overwrite=True)

    assert state is ManifestState.CERTIFIED
    assert (_BUCKET, canonical_key) in s3.store
    assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL
    assert (_BUCKET, silver_nass_crop_progress_key("soybeans_cbot", 2023)) in s3.store
