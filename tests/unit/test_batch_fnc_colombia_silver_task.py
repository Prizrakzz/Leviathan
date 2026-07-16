"""Unit tests for the FNC Colombia silver Batch task (helpers + A-W4 CLASS-B retrofit).

The three fnc silver tables are partitioned (projected); the A-W4 retrofit routes the
per-(commodity, year) write through the shadow-first publisher (ShadowPublisher, PROJECTED
strategy) rather than the flat ``build_flat_publish`` path -- the parquet body carries the
``year`` partition column, so the single-object flat encode does not fit. ``--publish-mode``
defaults to dry-run (nothing written); the fixture tests exercise ``_publish_projected`` directly
with injected guard verdicts.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import (
    silver_fnc_colombia_area_department_key,
    silver_fnc_colombia_exports_port_type_key,
    silver_fnc_colombia_monthly_key,
)

from jobs.batch import fnc_colombia_silver_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_MONTHLY_CONTRACT = load_registry().table("silver_fnc_colombia_monthly")
_BUCKET = _MONTHLY_CONTRACT["s3_bucket"]
_SENTINEL = b"OLD-CANONICAL-FNC-MONTHLY"


def _monthly_row(year: int, month: int) -> dict[str, object]:
    return {
        "leviathan_slug": "arabica_coffee",
        "country": "colombia",
        "year": year,
        "month": month,
        "date": date(year, month, 1),
        "production_bags_60kg": 1.0,
        "ex_dock_price_usd_cents_per_lb": None,
        "internal_price_cop_per_125kg": None,
        "exports_bags_60kg": None,
        "exports_value_usd_m": None,
        "source": "fnc_colombia",
    }


def _two_year_monthly() -> pd.DataFrame:
    return pd.DataFrame([
        _monthly_row(2024, 1),
        _monthly_row(2024, 2),
        _monthly_row(2023, 12),
    ])[task.MONTHLY_OUTPUT_COLUMNS]


# ---------------------------------------------------------------------------
# Preserved build helpers
# ---------------------------------------------------------------------------

def test_filter_years_keeps_selected_years() -> None:
    df = pd.DataFrame({"year": [2023, 2024], "value": [1, 2]})
    filtered = task._filter_years(df, {2024})
    assert filtered["year"].tolist() == [2024]


def test_path_helpers_do_not_overlap_other_silver_prefixes() -> None:
    paths = {
        silver_fnc_colombia_monthly_key(2024),
        silver_fnc_colombia_area_department_key(2024),
        silver_fnc_colombia_exports_port_type_key(2024),
    }
    assert paths == {
        "silver/fnc_colombia/monthly/commodity=arabica_coffee/year=2024/part-000.parquet",
        "silver/fnc_colombia/area_department/commodity=arabica_coffee/year=2024/part-000.parquet",
        "silver/fnc_colombia/exports_port_type/commodity=arabica_coffee/year=2024/part-000.parquet",
    }
    assert all(not path.startswith("silver/production/") for path in paths)
    assert all(not path.startswith("silver/nass_") for path in paths)


# ---------------------------------------------------------------------------
# Arg surface (A-W4 CLASS-B retrofit) -- the DAG routes --publish-mode shadow
# ---------------------------------------------------------------------------

def test_publish_mode_shadow_is_accepted(monkeypatch) -> None:
    # Regression: argparse used to exit 2 ("unrecognized arguments: --publish-mode shadow").
    monkeypatch.setattr(
        "sys.argv",
        ["fnc_colombia_silver_task.py", "--publish-mode", "shadow", "--years", "2024"],
    )
    args = task._parse_args()
    assert args.publish_mode == "shadow"
    assert args.years == "2024"


def test_dry_run_flag_aliases_publish_mode(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fnc_colombia_silver_task.py", "--dry-run"])
    args = task._parse_args()
    assert args.dry_run is True


def test_force_overwrite_string_still_parses(monkeypatch) -> None:
    # The submit wrapper passes force_overwrite as a "true"/"false" string.
    monkeypatch.setattr(
        "sys.argv",
        ["fnc_colombia_silver_task.py", "--force-overwrite", "true"],
    )
    args = task._parse_args()
    assert args.force_overwrite is True


# ---------------------------------------------------------------------------
# Shadow-first publish (A-W4 CLASS-B retrofit)
# ---------------------------------------------------------------------------

def test_monthly_body_columns_include_only_the_year_partition_extra() -> None:
    # Every contracted physical column is produced; the only extra body column is the
    # ``year`` partition key (carried in the parquet body AND the object path).
    contract_cols = [c["name"] for c in _MONTHLY_CONTRACT["physical_columns"]]
    assert set(contract_cols) <= set(task.MONTHLY_OUTPUT_COLUMNS)
    assert set(task.MONTHLY_OUTPUT_COLUMNS) - set(contract_cols) == {"year"}


def test_dry_run_writes_nothing_but_validates() -> None:
    state, published, skipped = task._publish_projected(
        _two_year_monthly(), task.MONTHLY_OUTPUT_COLUMNS, _MONTHLY_CONTRACT,
        silver_fnc_colombia_monthly_key, dryrun_authorization(), None, _BUCKET,
        force_overwrite=True,
    )
    assert state is ManifestState.VALIDATED
    assert published == 2      # two year partitions (2023, 2024)
    assert skipped == 0


def test_empty_frame_publishes_nothing() -> None:
    state, published, skipped = task._publish_projected(
        pd.DataFrame(columns=task.MONTHLY_OUTPUT_COLUMNS), task.MONTHLY_OUTPUT_COLUMNS,
        _MONTHLY_CONTRACT, silver_fnc_colombia_monthly_key, dryrun_authorization(), None, _BUCKET,
        force_overwrite=True,
    )
    assert state is None
    assert published == 0
    assert skipped == 0


def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical() -> None:
    s3 = FakeS3()
    canonical_key = silver_fnc_colombia_monthly_key(2024)
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL
    etag_before = s3._etag(_SENTINEL)

    state, published, _skipped = task._publish_projected(
        _two_year_monthly(), task.MONTHLY_OUTPUT_COLUMNS, _MONTHLY_CONTRACT,
        silver_fnc_colombia_monthly_key, shadow_authorization(), s3, _BUCKET,
        force_overwrite=True,
    )

    assert state is ManifestState.VALIDATED
    assert published == 2
    # canonical byte-identical, no promotion happened.
    assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL
    assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before
    assert any("_shadow" in k for k in s3.keys())
    # every written data object (control-plane manifest excluded) sits under _shadow/.
    for _, key in s3.store:
        if key == canonical_key or "/_manifests/" in key:
            continue
        assert "/_shadow/" in key


def test_canonical_overwrites_the_fnc_monthly_partition() -> None:
    s3 = FakeS3()
    canonical_key = silver_fnc_colombia_monthly_key(2024)
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL

    state, published, _skipped = task._publish_projected(
        _two_year_monthly(), task.MONTHLY_OUTPUT_COLUMNS, _MONTHLY_CONTRACT,
        silver_fnc_colombia_monthly_key, canonical_authorization(), s3, _BUCKET,
        force_overwrite=True,
    )

    assert state is ManifestState.CERTIFIED
    assert published == 2
    assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL
    # the 2023 partition's canonical object was also promoted.
    assert (_BUCKET, silver_fnc_colombia_monthly_key(2023)) in s3.store


def test_canonical_skips_existing_without_force_overwrite() -> None:
    s3 = FakeS3()
    kept = silver_fnc_colombia_monthly_key(2024)
    s3.store[(_BUCKET, kept)] = _SENTINEL

    state, published, skipped = task._publish_projected(
        _two_year_monthly(), task.MONTHLY_OUTPUT_COLUMNS, _MONTHLY_CONTRACT,
        silver_fnc_colombia_monthly_key, canonical_authorization(), s3, _BUCKET,
        force_overwrite=False,
    )

    assert state is ManifestState.CERTIFIED
    assert published == 1      # only the 2023 partition (2024 already existed)
    assert skipped == 1
    assert s3.store[(_BUCKET, kept)] == _SENTINEL      # existing 2024 canonical untouched
