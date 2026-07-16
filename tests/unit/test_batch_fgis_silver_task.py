"""Unit tests for the USDA FGIS silver Batch task publish helper (A-W4 CLASS-B retrofit).

``silver_fgis`` is partitioned (projected); the retrofit routes the per-(leviathan_slug,
marketing_year) write through the shadow-first publisher (ShadowPublisher, PROJECTED strategy)
rather than the flat ``build_flat_publish`` path -- the parquet body carries the leviathan_slug
and marketing_year partition columns. ``--publish-mode`` defaults to dry-run (nothing written);
these tests exercise ``_publish_fgis`` directly with injected guard verdicts.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_fgis_key
from leviathan.transforms.bronze_to_silver.usda_fgis import OUTPUT_COLUMNS

from jobs.batch import fgis_silver_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_CONTRACT = load_registry().table("silver_fgis")
_BUCKET = _CONTRACT["s3_bucket"]
_SENTINEL = b"OLD-CANONICAL-FGIS"


def _silver_row(slug: str, marketing_year: int, week: int, week_end: date) -> dict[str, object]:
    return {
        "leviathan_slug": slug,
        "marketing_year": marketing_year,
        "week_of_marketing_year": week,
        "week_ending_date": week_end,
        "destination_country": "japan",
        "exports_mt_weekly": 12345.0,
        "exports_mt_ctd": 67890.0,
        "source": "usda_fgis_export_inspections",
    }


def _two_partition_silver() -> pd.DataFrame:
    return pd.DataFrame([
        _silver_row("corn_cbot", 2024, 1, date(2024, 9, 7)),
        _silver_row("corn_cbot", 2024, 2, date(2024, 9, 14)),
        _silver_row("soybeans_cbot", 2023, 1, date(2023, 9, 7)),
    ])[OUTPUT_COLUMNS]


def test_silver_columns_match_contract() -> None:
    # Every contracted physical column is produced; the only extra body columns are the
    # (leviathan_slug, marketing_year) partition keys (carried in the body AND the path).
    contract_cols = [c["name"] for c in _CONTRACT["physical_columns"]]
    assert set(contract_cols) <= set(OUTPUT_COLUMNS)
    assert set(OUTPUT_COLUMNS) - set(contract_cols) == {"leviathan_slug", "marketing_year"}


def test_dry_run_writes_nothing_but_validates() -> None:
    state = task._publish_fgis(_two_partition_silver(), _CONTRACT, dryrun_authorization(), None,
                               _BUCKET, slug_filter=None, my_filter=None, force_overwrite=True)
    assert state is ManifestState.VALIDATED


def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical() -> None:
    s3 = FakeS3()
    canonical_key = silver_fgis_key("corn_cbot", 2024)
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL
    etag_before = s3._etag(_SENTINEL)

    state = task._publish_fgis(_two_partition_silver(), _CONTRACT, shadow_authorization(), s3,
                               _BUCKET, slug_filter=None, my_filter=None, force_overwrite=True)

    assert state is ManifestState.VALIDATED
    assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL
    assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before
    assert any("_shadow" in k for k in s3.keys())
    for _, key in s3.store:
        if key == canonical_key or "/_manifests/" in key:
            continue
        assert "/_shadow/" in key


def test_canonical_overwrites_the_fgis_partition() -> None:
    s3 = FakeS3()
    canonical_key = silver_fgis_key("corn_cbot", 2024)
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL

    state = task._publish_fgis(_two_partition_silver(), _CONTRACT, canonical_authorization(), s3,
                               _BUCKET, slug_filter=None, my_filter=None, force_overwrite=True)

    assert state is ManifestState.CERTIFIED
    assert (_BUCKET, canonical_key) in s3.store
    assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL
    assert (_BUCKET, silver_fgis_key("soybeans_cbot", 2023)) in s3.store


def test_slug_filter_restricts_published_partitions() -> None:
    s3 = FakeS3()
    state = task._publish_fgis(_two_partition_silver(), _CONTRACT, canonical_authorization(), s3,
                               _BUCKET, slug_filter={"corn_cbot"}, my_filter=None,
                               force_overwrite=True)
    assert state is ManifestState.CERTIFIED
    assert (_BUCKET, silver_fgis_key("corn_cbot", 2024)) in s3.store
    # soybeans filtered out -> never promoted to canonical.
    assert (_BUCKET, silver_fgis_key("soybeans_cbot", 2023)) not in s3.store
