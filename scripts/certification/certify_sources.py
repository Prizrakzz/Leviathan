"""Run source-level certification reports for registered structured datasets."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from leviathan.catalog.registry import DatasetSpec, load_dataset_registry  # noqa: E402
from leviathan.certification.source_certification import (  # noqa: E402
    certify_dataframe,
    load_source_contracts,
)


def _dataset_uri(root: str, dataset: DatasetSpec, bucket: str) -> str:
    prefix = dataset.s3_prefix
    if root.startswith("s3://"):
        return f"{root.rstrip('/')}/{prefix}"
    if root == "s3":
        return f"s3://{bucket}/{prefix}"
    return str(Path(root) / prefix)


def _read_dataset(uri: str, columns: list[str] | None = None) -> pd.DataFrame:
    dataset = ds.dataset(uri, format="parquet", partitioning="hive")
    table = dataset.to_table(columns=columns)
    return table.to_pandas()


def _selected_columns(dataset: DatasetSpec, contract_columns: set[str]) -> list[str]:
    needed = set(dataset.natural_key)
    needed.update(dataset.primary_timestamps)
    needed.update(dataset.partition_names)
    for column in dataset.schema:
        if column.name in contract_columns:
            needed.add(column.name)
        if any(token in column.name.lower() for token in ("revision", "delta", "change", "surprise")):
            needed.add(column.name)
        if column.type.lower().split("(", 1)[0] in {"tinyint", "smallint", "int", "bigint", "float", "double", "decimal"}:
            needed.add(column.name)
    return [column.name for column in dataset.schema if column.name in needed]


def main() -> None:
    parser = argparse.ArgumentParser(description="Certify registered datasets for ML readiness.")
    parser.add_argument("--registry", default=str(PROJECT_ROOT / "configs" / "datasets" / "datasets.yaml"))
    parser.add_argument("--contracts", default=str(PROJECT_ROOT / "configs" / "datasets" / "source_contracts.yaml"))
    parser.add_argument("--root", default="s3", help="'s3', an s3://bucket URI, or a local lake root")
    parser.add_argument("--dataset-id", action="append", default=[])
    parser.add_argument("--include-diagnostic", action="store_true")
    parser.add_argument("--include-metadata", action="store_true")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "data" / "source_certification" / "phase2"))
    args = parser.parse_args()

    registry = load_dataset_registry(args.registry)
    contracts = load_source_contracts(args.contracts)
    wanted = set(args.dataset_id)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reports: list[dict] = []
    for dataset in registry.datasets:
        if wanted and dataset.dataset_id not in wanted:
            continue
        if dataset.layer not in {"silver", "gold"}:
            if not args.include_metadata:
                continue
        if dataset.role == "diagnostic" and not args.include_diagnostic:
            continue
        if dataset.status == "empty_pending_backfill":
            continue

        contract = contracts.get(dataset.dataset_id)
        contract_columns: set[str] = set()
        if contract:
            contract_columns.update(contract.expected_units)
            contract_columns.update(contract.expected_categories)
            contract_columns.update(contract.required_nonzero_revision_columns)
        columns = _selected_columns(dataset, contract_columns)
        uri = _dataset_uri(args.root, dataset, registry.bucket)
        try:
            df = _read_dataset(uri, columns=columns)
            report = certify_dataframe(dataset, df, contract=contract)
        except Exception as exc:  # noqa: BLE001
            report = {
                "dataset_id": dataset.dataset_id,
                "athena_table": dataset.athena.table,
                "registry_status": dataset.status,
                "certification_status": "block",
                "row_count": None,
                "blockers": [f"certification read/check failed: {exc}"],
                "warnings": [],
            }
        report["certified_at"] = datetime.now(timezone.utc).isoformat()
        reports.append(report)
        (output_dir / f"{dataset.dataset_id}.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    summary = {
        "certified_at": datetime.now(timezone.utc).isoformat(),
        "total": len(reports),
        "pass": sum(1 for report in reports if report["certification_status"] == "pass"),
        "warn": sum(1 for report in reports if report["certification_status"] == "warn"),
        "block": sum(1 for report in reports if report["certification_status"] == "block"),
        "blocked_datasets": [
            report["dataset_id"]
            for report in reports
            if report["certification_status"] == "block"
        ],
    }
    (output_dir / "_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["block"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
