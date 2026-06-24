from __future__ import annotations

from datetime import date

import pandas as pd

from leviathan.catalog.registry import (
    AthenaSpec,
    ColumnSpec,
    DatasetSpec,
    PartitionSpec,
)
from leviathan.certification.source_certification import (
    SourceContract,
    certify_dataframe,
    load_source_contracts,
)


def _dataset(
    *,
    status: str = "active",
    natural_key: tuple[str, ...] = ("commodity", "year"),
    freshness_days: int | None = None,
) -> DatasetSpec:
    return DatasetSpec(
        dataset_id="silver_example",
        layer="silver",
        role="feature_source",
        status=status,
        s3_prefix="silver/example/",
        file_format="PARQUET",
        schema=(
            ColumnSpec("commodity", "string", False),
            ColumnSpec("year", "int", False),
            ColumnSpec("date", "date", False),
            ColumnSpec("unit", "string", True),
            ColumnSpec("category", "string", True),
            ColumnSpec("value", "double", True),
            ColumnSpec("revision", "double", True),
        ),
        natural_key=natural_key,
        partitions=(PartitionSpec("commodity", "string"),),
        owner_transform=None,
        owner_task=None,
        primary_timestamps=("date",),
        freshness_days=freshness_days,
        historical_start=None,
        historical_end=None,
        core_fundamental=True,
        athena=AthenaSpec(
            table="silver_example",
            database="leviathan_dev",
            location="silver/example/",
            storage_template=None,
            properties={},
            smoke_query='SELECT * FROM "leviathan_dev"."silver_example" LIMIT 1',
            serde=None,
            input_format=None,
            output_format=None,
        ),
    )


def test_certify_dataframe_passes_clean_source() -> None:
    df = pd.DataFrame({
        "commodity": ["corn", "corn"],
        "year": [2023, 2024],
        "date": ["2023-01-01", "2024-01-01"],
        "unit": ["mt", "mt"],
        "category": ["production", "production"],
        "value": [10.0, 11.0],
        "revision": [0.0, 1.5],
    })
    report = certify_dataframe(
        _dataset(),
        df,
        contract=SourceContract(
            "silver_example",
            expected_units={"unit": ("mt",)},
            expected_categories={"category": ("production",)},
            required_nonzero_revision_columns=("revision",),
        ),
        as_of=date(2024, 1, 2),
    )
    assert report["certification_status"] == "pass"
    assert report["row_count"] == 2
    assert report["duplicate_count"] == 0
    assert report["nonzero_revision_count"]["revision"] == 1


def test_duplicate_natural_key_blocks() -> None:
    df = pd.DataFrame({
        "commodity": ["corn", "corn"],
        "year": [2024, 2024],
        "date": ["2024-01-01", "2024-01-01"],
        "value": [10.0, 10.0],
        "revision": [0.0, 0.0],
    })
    report = certify_dataframe(_dataset(), df, as_of=date(2024, 1, 2))
    assert report["certification_status"] == "block"
    assert report["duplicate_count"] == 1
    assert any("duplicate" in item for item in report["blockers"])


def test_blocked_registry_status_and_missing_revisions_block() -> None:
    df = pd.DataFrame({
        "commodity": ["coffee", "coffee"],
        "year": [2023, 2024],
        "date": ["2023-01-01", "2024-01-01"],
        "value": [100.0, 101.0],
        "revision": [0.0, 0.0],
    })
    report = certify_dataframe(
        _dataset(status="blocked_pending_phase2"),
        df,
        contract=SourceContract(
            "silver_example",
            required_nonzero_revision_columns=("revision",),
        ),
        as_of=date(2024, 1, 2),
    )
    assert report["certification_status"] == "block"
    assert "dataset registry status is blocked_pending_phase2" in report["blockers"]
    assert "revision has zero nonzero revisions" in report["blockers"]


def test_unexpected_unit_and_category_block() -> None:
    df = pd.DataFrame({
        "commodity": ["corn"],
        "year": [2024],
        "date": ["2024-01-01"],
        "unit": ["bushels"],
        "category": ["parser_noise"],
        "value": [10.0],
        "revision": [1.0],
    })
    report = certify_dataframe(
        _dataset(),
        df,
        contract=SourceContract(
            "silver_example",
            expected_units={"unit": ("mt",)},
            expected_categories={"category": ("production",)},
        ),
        as_of=date(2024, 1, 2),
    )
    assert report["certification_status"] == "block"
    assert report["unexpected_unit_count"]["unit"] == 1
    assert report["unexpected_category_count"]["category"] == 1


def test_stale_dataset_warns_not_blocks() -> None:
    df = pd.DataFrame({
        "commodity": ["corn"],
        "year": [2024],
        "date": ["2024-01-01"],
        "value": [10.0],
        "revision": [1.0],
    })
    report = certify_dataframe(
        _dataset(freshness_days=7),
        df,
        as_of=date(2024, 2, 1),
    )
    assert report["certification_status"] == "warn"
    assert report["freshness"]["is_stale"] is True


def test_load_source_contracts(tmp_path) -> None:
    path = tmp_path / "contracts.yaml"
    path.write_text(
        "contracts:\n"
        "  - dataset_id: silver_example\n"
        "    expected_units:\n"
        "      unit: [mt, bushels]\n"
        "    expected_categories:\n"
        "      category: [production]\n"
        "    required_nonzero_revision_columns: [revision]\n"
        "    known_limitations:\n"
        "      - annual cadence only\n",
        encoding="utf-8",
    )
    contracts = load_source_contracts(path)
    contract = contracts["silver_example"]
    assert contract.expected_units["unit"] == ("mt", "bushels")
    assert contract.expected_categories["category"] == ("production",)
    assert contract.required_nonzero_revision_columns == ("revision",)
    assert contract.known_limitations == ("annual cadence only",)
