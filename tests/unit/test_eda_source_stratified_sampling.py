from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.eda.inventory import SilverTable, TableInventory, inventory_table
from leviathan.eda.reader import ReadResult, StratumDimension, read_for_analysis
from leviathan.eda.snapshot import (
    SnapshotError,
    deterministic_seed,
    freeze_read_result,
)


def _contract() -> dict:
    return {
        "table_name": "silver_strata_demo",
        "layer": "silver",
        "s3_bucket": "test-leviathan",
        "s3_prefix": "silver/strata_demo",
        "s3_root": "s3://test-leviathan/silver/strata_demo",
        "partition_mode": "projected",
        "partition_keys": [
            {"name": "commodity", "glue_type": "string", "projected": True}
        ],
        "physical_columns": [
            {"name": "region"},
            {"name": "date"},
            {"name": "value"},
        ],
        "fingerprint": {},
    }


def _inventory(tmp_path: Path) -> tuple[dict, TableInventory]:
    contract = _contract()
    root = tmp_path / "silver/strata_demo"
    root.mkdir(parents=True)
    for file_number, commodity in enumerate(("corn", "soy")):
        regions: list[str] = []
        dates: list[str] = []
        values: list[float] = []
        for region in ("north", "south"):
            for month in (1, 2):
                for day in range(1, 6):
                    regions.append(region)
                    dates.append(f"2024-{month:02d}-{day + file_number * 5:02d}")
                    values.append(float(len(values) + file_number * 100))
        target = root / f"commodity={commodity}/part-{file_number}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.table({"region": regions, "date": dates, "value": values}),
            target,
            row_group_size=4,
        )
    return contract, inventory_table(
        SilverTable("silver_strata_demo", contract), local_root=tmp_path
    )


def test_oversized_read_is_source_wide_entity_time_stratified_and_complete(
    tmp_path: Path,
) -> None:
    contract, inventory = _inventory(tmp_path)

    first = read_for_analysis(
        inventory,
        "campaign-strata",
        contract=contract,
        full_row_limit=1,
        full_compressed_byte_limit=1,
        sample_row_limit=8,
        batch_size=3,
    )
    second = read_for_analysis(
        inventory,
        "campaign-strata",
        contract=contract,
        full_row_limit=1,
        full_compressed_byte_limit=1,
        sample_row_limit=8,
        batch_size=7,
    )

    assert first.table.equals(second.table)
    assert first.source_row_count == inventory.total_rows == 40
    assert first.row_count == 8
    assert {
        (row["commodity"], row["region"], row["date"][:7])
        for row in first.table.to_pylist()
    } == {
        (commodity, region, month)
        for commodity in ("corn", "soy")
        for region in ("north", "south")
        for month in ("2024-01", "2024-02")
    }
    dimensions = first.coverage_catalog["analysis_stratum_dimensions"]
    assert dimensions == [
        {
            "column": "commodity",
            "roles": ["partition", "entity"],
            "transform": "identity",
        },
        {"column": "region", "roles": ["entity"], "transform": "identity"},
        {"column": "date", "roles": ["time"], "transform": "calendar_month"},
    ]
    strata = first.coverage_catalog["analysis_strata"]
    assert first.coverage_catalog["analysis_strata_complete"] is True
    assert first.coverage_catalog["analysis_stratum_count"] == 8
    assert sum(item["source_row_count"] for item in strata) == 40
    assert sum(item["sampled_row_count"] for item in strata) == 8
    assert all(item["represented"] for item in strata)
    assert sum(item.selected_rows for item in first.row_group_selections) == 8


def test_complete_catalog_keeps_unrepresented_strata_when_cap_is_smaller(
    tmp_path: Path,
) -> None:
    contract, inventory = _inventory(tmp_path)

    result = read_for_analysis(
        inventory,
        "campaign-strata-small",
        contract=contract,
        full_row_limit=1,
        full_compressed_byte_limit=1,
        sample_row_limit=7,
    )

    strata = result.coverage_catalog["analysis_strata"]
    assert len(strata) == 8
    assert sum(item["source_row_count"] for item in strata) == 40
    assert sum(item["sampled_row_count"] for item in strata) == 7
    assert sum(not item["represented"] for item in strata) == 1


def test_snapshot_accepts_reader_sample_without_sampling_or_relabelling() -> None:
    table = pa.table(
        {
            "region": ["north", "south", "north"],
            "date": ["2024-01-01", "2024-01-02", "2024-02-01"],
            "value": [1.0, 2.0, 3.0],
        }
    )
    contract = _contract()
    inventory = TableInventory(
        table_name="silver_strata_demo",
        layer="silver",
        bucket="test-leviathan",
        root_uri=contract["s3_root"],
        partition_mode="flat",
        partition_keys=(),
        contract_sha256="contract",
        registry_fingerprint={},
        objects=(),
        source_mode="local",
    )
    seed = deterministic_seed("campaign-strata", inventory.table_name)
    result = ReadResult(
        table=table,
        table_name=inventory.table_name,
        manifest_sha256=inventory.manifest_sha256,
        object_count=2,
        row_count=3,
        exactness="sampled",
        source_row_count=40,
        source_compressed_bytes=0,
        sample_seed=seed,
        sampling_strata=(
            StratumDimension("region", ("entity",), "identity"),
            StratumDimension("date", ("time",), "calendar_month"),
        ),
        sampling_strategy="source-wide stratified sample",
    )

    frozen = freeze_read_result(result, inventory, "campaign-strata")

    assert frozen.table.equals(table)
    assert frozen.decision.source_row_count == 40
    assert frozen.decision.snapshot_row_count == 3
    assert frozen.decision.stratum_columns == ("region", "date")
    assert frozen.decision.reason == "source-wide stratified sample"

    bad = ReadResult(
        **{**result.__dict__, "sample_seed": seed + 1}
    )
    with pytest.raises(SnapshotError, match="seed"):
        freeze_read_result(bad, inventory, "campaign-strata")
