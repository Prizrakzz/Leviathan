"""Export the live Glue database definition before catalog mutation."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.catalog.aws import list_glue_tables  # noqa: E402
from leviathan.catalog.registry import load_dataset_registry  # noqa: E402


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    registry = load_dataset_registry(args.registry)
    glue = boto3.client("glue", region_name=args.aws_region)
    document = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "database": glue.get_database(Name=registry.database)["Database"],
        "tables": list(list_glue_tables(glue, registry.database).values()),
    }
    body = json.dumps(document, indent=2, sort_keys=True, default=_json_default)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(body + "\n", encoding="utf-8")
    uri = None
    if args.upload:
        key = (
            "metadata/catalog_reconciliation/backups/"
            f"{args.output.stem}.json"
        )
        boto3.client("s3", region_name=args.aws_region).put_object(
            Bucket=registry.bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
        uri = f"s3://{registry.bucket}/{key}"
    print(json.dumps({"local": str(args.output.resolve()), "s3": uri}, indent=2))


if __name__ == "__main__":
    main()
