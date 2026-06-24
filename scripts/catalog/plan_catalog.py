"""Create a read-only Glue/Athena reconciliation plan."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.catalog.aws import list_glue_tables  # noqa: E402
from leviathan.catalog.reconcile import build_catalog_plan  # noqa: E402
from leviathan.catalog.registry import load_dataset_registry  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registry = load_dataset_registry(args.registry)
    glue = boto3.client("glue", region_name=args.aws_region)
    plan = build_catalog_plan(
        registry,
        list_glue_tables(glue, registry.database),
    )
    plan["generated_at"] = datetime.now(timezone.utc).isoformat()
    body = json.dumps(plan, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body + "\n", encoding="utf-8")
    print(body)


if __name__ == "__main__":
    main()
