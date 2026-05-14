"""Utility: delete all S3 objects under one or more key prefixes.

Usage:
    # Dry run — list what would be deleted:
    python jobs/purge_s3_prefix.py --prefixes silver/production/commodity=cocoa/ --dry-run

    # Real delete (prompts for confirmation):
    python jobs/purge_s3_prefix.py --prefixes silver/production/commodity=cocoa/

    # Multiple prefixes at once:
    python jobs/purge_s3_prefix.py --prefixes p1/ p2/

    # Skip confirmation prompt:
    python jobs/purge_s3_prefix.py --prefixes silver/production/commodity=cocoa/ --yes

Environment variables:
    LEVIATHAN_BUCKET  — S3 bucket name (default: leviathan-dev-shahem-001)
    AWS_DEFAULT_REGION — AWS region (default: us-east-1)
"""
from __future__ import annotations

import argparse
import os
import sys

import boto3

from leviathan.storage.s3 import list_s3_keys

BUCKET = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
DELETE_BATCH_SIZE = 1000  # S3 delete_objects max


def delete_keys(s3, bucket: str, keys: list[str]) -> int:
    """Delete keys in batches of DELETE_BATCH_SIZE. Returns number deleted."""
    deleted = 0
    for i in range(0, len(keys), DELETE_BATCH_SIZE):
        batch = keys[i : i + DELETE_BATCH_SIZE]
        response = s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
        )
        errors = response.get("Errors", [])
        if errors:
            for err in errors:
                print(f"  ERROR deleting {err['Key']}: {err['Code']} {err['Message']}", file=sys.stderr)
        deleted += len(batch) - len(errors)
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge S3 objects under given prefixes.")
    parser.add_argument("--prefixes", nargs="+", required=True, help="S3 key prefix(es) to purge")
    parser.add_argument("--bucket", default=BUCKET, help=f"S3 bucket (default: {BUCKET})")
    parser.add_argument("--region", default=AWS_REGION, help=f"AWS region (default: {AWS_REGION})")
    parser.add_argument("--dry-run", action="store_true", help="List keys without deleting")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    # Collect all keys across all prefixes
    all_keys: list[str] = []
    for prefix in args.prefixes:
        keys = list_s3_keys(args.bucket, prefix, aws_region=args.region)
        print(f"  s3://{args.bucket}/{prefix}  →  {len(keys)} objects")
        all_keys.extend(keys)

    if not all_keys:
        print("No objects found. Nothing to do.")
        return

    print(f"\nTotal objects to delete: {len(all_keys)}")

    if args.dry_run:
        print("\n[DRY RUN] First 20 keys that would be deleted:")
        for k in all_keys[:20]:
            print(f"  {k}")
        if len(all_keys) > 20:
            print(f"  ... and {len(all_keys) - 20} more")
        print("\n[DRY RUN] No objects were deleted. Remove --dry-run to proceed.")
        return

    if not args.yes:
        answer = input(f"\nDelete {len(all_keys)} objects from s3://{args.bucket}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    print(f"Deleting {len(all_keys)} objects ...")
    deleted = delete_keys(s3, args.bucket, all_keys)
    print(f"Done. Deleted {deleted} of {len(all_keys)} objects.")


if __name__ == "__main__":
    main()
