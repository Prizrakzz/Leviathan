"""Validate registry, generated DDLs, Glue definitions, Parquet schemas, and Athena."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.catalog.aws import (  # noqa: E402
    athena_has_data_rows,
    list_glue_tables,
    run_athena_statement,
)
from leviathan.catalog.ddl import render_registry_ddls  # noqa: E402
from leviathan.catalog.reconcile import (  # noqa: E402
    desired_table_signature,
    live_table_signature,
    signature_differences,
)
from leviathan.catalog.registry import load_dataset_registry  # noqa: E402
from leviathan.catalog.schema_probe import probe_prefix, schema_mismatches  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--ddl-dir", type=Path, default=Path("sql/athena/ddl"))
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--max-parquet-files", type=int, default=3)
    parser.add_argument("--skip-parquet", action="store_true")
    parser.add_argument("--run-athena", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    registry = load_dataset_registry(args.registry)
    rendered = render_registry_ddls(registry)
    glue = boto3.client("glue", region_name=args.aws_region)
    s3 = boto3.client("s3", region_name=args.aws_region)
    athena = boto3.client("athena", region_name=args.aws_region)
    live = list_glue_tables(glue, registry.database)
    findings: list[dict] = []

    for dataset in registry.datasets:
        table = dataset.athena.table
        expected_ddl = rendered[table]
        path = args.ddl_dir / f"{table}.sql"
        if not path.exists():
            findings.append(
                {"severity": "blocking", "dataset": dataset.dataset_id, "issue": "ddl_missing"}
            )
        elif path.read_text(encoding="utf-8") != expected_ddl:
            findings.append(
                {"severity": "blocking", "dataset": dataset.dataset_id, "issue": "ddl_drift"}
            )

        live_table = live.get(table)
        if live_table is None:
            findings.append(
                {"severity": "blocking", "dataset": dataset.dataset_id, "issue": "glue_missing"}
            )
        else:
            differences = signature_differences(
                desired_table_signature(dataset, registry.bucket),
                live_table_signature(live_table),
            )
            if differences:
                findings.append(
                    {
                        "severity": "blocking",
                        "dataset": dataset.dataset_id,
                        "issue": "glue_drift",
                        "fields": differences,
                    }
                )

        if not args.skip_parquet and dataset.dataset_id != "metadata_s3_inventory":
            probe = probe_prefix(
                s3,
                bucket=registry.bucket,
                prefix=dataset.s3_prefix,
                max_files=args.max_parquet_files,
            )
            if not probe.sampled_files:
                findings.append(
                    {
                        "severity": "blocking" if dataset.status == "active" else "warning",
                        "dataset": dataset.dataset_id,
                        "issue": "no_parquet_sample",
                    }
                )
            mismatches = schema_mismatches(dataset, probe)
            if mismatches:
                if len(probe.schema_hashes) > 1:
                    findings.append(
                        {
                            "severity": "blocking",
                            "dataset": dataset.dataset_id,
                            "issue": "mixed_parquet_schema",
                            "schema_hashes": list(probe.schema_hashes),
                        }
                    )
                findings.append(
                    {
                        "severity": "blocking",
                        "dataset": dataset.dataset_id,
                        "issue": "parquet_schema_mismatch",
                        "details": mismatches,
                    }
                )

        if args.run_athena and live_table is not None:
            try:
                execution = run_athena_statement(
                    athena,
                    sql=dataset.athena.smoke_query,
                    database=registry.database,
                    output_location=f"s3://{registry.bucket}/athena-results/catalog-validation/",
                )
                scanned = int(
                    execution.get("Statistics", {}).get("DataScannedInBytes", 0)
                )
                if scanned > 100_000_000:
                    findings.append(
                        {
                            "severity": "blocking",
                            "dataset": dataset.dataset_id,
                            "issue": "athena_smoke_scan_too_large",
                            "bytes_scanned": scanned,
                        }
                    )
                if not athena_has_data_rows(
                    athena,
                    execution["QueryExecutionId"],
                ):
                    findings.append(
                        {
                            "severity": (
                                "warning"
                                if dataset.dataset_id == "metadata_s3_inventory"
                                or dataset.status != "active"
                                else "blocking"
                            ),
                            "dataset": dataset.dataset_id,
                            "issue": "athena_smoke_empty",
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                findings.append(
                    {
                        "severity": "blocking",
                        "dataset": dataset.dataset_id,
                        "issue": "athena_smoke_failed",
                        "error": str(exc),
                    }
                )

    managed = set(registry.by_table())
    for table in sorted(set(live) - managed - set(registry.retired_tables)):
        findings.append(
            {"severity": "blocking", "table": table, "issue": "unmanaged_live_table"}
        )
    for table in registry.retired_tables:
        if table in live:
            findings.append(
                {"severity": "blocking", "table": table, "issue": "retired_table_still_live"}
            )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registry_sha256": registry.content_sha256,
        "dataset_count": len(registry.datasets),
        "live_table_count": len(live),
        "blocking_count": sum(f["severity"] == "blocking" for f in findings),
        "warning_count": sum(f["severity"] == "warning" for f in findings),
        "findings": findings,
    }
    body = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body + "\n", encoding="utf-8")
    print(body)
    if report["blocking_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
