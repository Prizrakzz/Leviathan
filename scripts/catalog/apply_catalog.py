"""Apply an immutable reviewed catalog plan; never modifies S3 data."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.catalog.aws import run_athena_statement  # noqa: E402
from leviathan.catalog.ddl import render_registry_ddls  # noqa: E402
from leviathan.catalog.reconcile import verify_plan_hash  # noqa: E402
from leviathan.catalog.registry import load_dataset_registry  # noqa: E402


def drop_table_sql(database: str, table: str) -> str:
    return f"DROP TABLE IF EXISTS `{database}`.`{table}`"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--confirm-plan-sha", required=True)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--workgroup", default="primary")
    parser.add_argument("--allow-retire", action="store_true")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if not verify_plan_hash(plan):
        raise SystemExit("plan hash is invalid; regenerate the plan")
    if plan["plan_sha256"] != args.confirm_plan_sha:
        raise SystemExit("--confirm-plan-sha does not match the plan")

    registry = load_dataset_registry(args.registry)
    if plan["registry_sha256"] != registry.content_sha256:
        raise SystemExit("registry changed after the plan was generated")
    rendered = render_registry_ddls(registry)
    athena = boto3.client("athena", region_name=args.aws_region)
    results = f"s3://{registry.bucket}/athena-results/catalog-reconciliation/"

    for action in plan["actions"]:
        kind = action["action"]
        table = action["table"]
        if kind in {"noop", "unmanaged"}:
            continue
        if kind == "retire":
            if not args.allow_retire:
                raise SystemExit(
                    f"plan contains retire action for {table}; pass --allow-retire"
                )
            run_athena_statement(
                athena,
                sql=drop_table_sql(registry.database, table),
                database=None,
                output_location=results,
                workgroup=args.workgroup,
            )
            continue
        if kind == "replace":
            run_athena_statement(
                athena,
                sql=drop_table_sql(registry.database, table),
                database=None,
                output_location=results,
                workgroup=args.workgroup,
            )
        run_athena_statement(
            athena,
            sql=rendered[table],
            database=registry.database,
            output_location=results,
            workgroup=args.workgroup,
        )
    print(json.dumps({"applied_plan_sha256": plan["plan_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
