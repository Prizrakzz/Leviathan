"""Deduplicate USDA GAIN PDFs in raw S3.

The same report can be stored under two different ``publication_date`` partitions
when a Batch crawl task runs twice and FAS updates its "posted" timestamp between
runs.  This script identifies such duplicates by grouping S3 keys on the GAIN
``report_id`` (e.g. ``AR2026-0006``) extracted from the PDF filename, verifies
all copies share the same ``ContentLength`` (byte-identical), and deletes the
older-partition copy/copies, keeping only the one with the latest
``publication_date`` in its S3 path.

Usage
-----
    # Preview what would be deleted (no S3 writes):
    python jobs/utils/deduplicate_gain_s3.py --dry-run

    # Delete confirmed duplicates (prompts for confirmation):
    python jobs/utils/deduplicate_gain_s3.py

    # Skip confirmation prompt:
    python jobs/utils/deduplicate_gain_s3.py --yes

    # Restrict to specific commodities:
    python jobs/utils/deduplicate_gain_s3.py --commodities wheat corn --dry-run

Environment variables
---------------------
    LEVIATHAN_BUCKET   — S3 bucket (default: leviathan-dev-shahem-001)
    AWS_DEFAULT_REGION — AWS region  (default: us-east-1)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

import boto3

BUCKET = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
RAW_PREFIX = "raw/production/"

ALL_GAIN_COMMODITIES = [
    "wheat",
    "corn",
    "soybeans",
    "rapeseed",
    "rice",
    "soybean_oil",
    "soybean_meal",
    "sugar",
    "cotton",
    "palm_oil",
    "cocoa",
    "orange_juice",
    "coffee",
]

# e.g. "AR2026-0006" in a PDF filename
_REPORT_ID_RE = re.compile(r"\b([A-Z]{2}\d{4}-\d{4})\b")
# e.g. "publication_date=20260401" in an S3 key path
_PUB_DATE_RE = re.compile(r"publication_date=(\d{8})")

DELETE_BATCH_SIZE = 1000  # S3 delete_objects max


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def list_objects_with_size(s3, bucket: str, prefix: str) -> list[tuple[str, int]]:
    """Return (key, size) for every S3 object under *prefix* (paginated)."""
    paginator = s3.get_paginator("list_objects_v2")
    results: list[tuple[str, int]] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            results.append((obj["Key"], obj["Size"]))
    return results


def delete_keys(s3, bucket: str, keys: list[str]) -> int:
    """Delete *keys* in batches. Returns count of successfully deleted keys."""
    deleted = 0
    for i in range(0, len(keys), DELETE_BATCH_SIZE):
        batch = keys[i : i + DELETE_BATCH_SIZE]
        response = s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
        )
        errors = response.get("Errors", [])
        for err in errors:
            print(
                f"  ERROR deleting {err['Key']}: {err['Code']} {err['Message']}",
                file=sys.stderr,
            )
        deleted += len(batch) - len(errors)
    return deleted


# ---------------------------------------------------------------------------
# Dedup logic
# ---------------------------------------------------------------------------


def _extract_report_id(key: str) -> str | None:
    filename = key.rsplit("/", 1)[-1]
    m = _REPORT_ID_RE.search(filename)
    return m.group(1) if m else None


def _extract_pub_date(key: str) -> str:
    m = _PUB_DATE_RE.search(key)
    return m.group(1) if m else ""


def find_duplicate_groups(
    objects: list[tuple[str, int]],
) -> tuple[
    dict[str, dict],           # report_id → {keeper, duplicates}
    list[tuple[str, list]],    # size-mismatched groups (skipped)
    list[str],                 # keys with no parseable report_id
]:
    """Group objects by report_id and identify duplicates.

    Returns
    -------
    groups_to_clean : dict
        Maps report_id → {"keeper": (key, size), "duplicates": [(key, size), ...]}
        Keeper is the copy with the latest publication_date; duplicates are to be
        deleted after size-identity verification.
    skipped : list of (report_id, [(key, size), ...])
        Groups where copies have different sizes — never auto-deleted.
    no_id_keys : list of str
        Object keys from which no report_id could be extracted (informational).
    """
    by_id: dict[str, list[tuple[str, int]]] = defaultdict(list)
    no_id_keys: list[str] = []

    for key, size in objects:
        rid = _extract_report_id(key)
        if rid:
            by_id[rid].append((key, size))
        else:
            no_id_keys.append(key)

    groups_to_clean: dict[str, dict] = {}
    skipped: list[tuple[str, list]] = []

    for rid, entries in by_id.items():
        if len(entries) < 2:
            continue

        sizes = {sz for _, sz in entries}
        if len(sizes) > 1:
            # Different byte sizes — may be distinct report versions; skip.
            skipped.append((rid, entries))
            continue

        # All copies are byte-identical (same size). Keep the one with the
        # latest publication_date; queue the rest for deletion.
        sorted_entries = sorted(
            entries,
            key=lambda e: _extract_pub_date(e[0]),
            reverse=True,
        )
        groups_to_clean[rid] = {
            "keeper": sorted_entries[0],
            "duplicates": sorted_entries[1:],
        }

    return groups_to_clean, skipped, no_id_keys


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deduplicate USDA GAIN PDFs in raw S3 by report_id.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--commodities",
        nargs="+",
        default=ALL_GAIN_COMMODITIES,
        metavar="COMMODITY",
        help=f"GAIN commodity names to check (default: all {len(ALL_GAIN_COMMODITIES)})",
    )
    parser.add_argument(
        "--bucket",
        default=BUCKET,
        help=f"S3 bucket (default: {BUCKET})",
    )
    parser.add_argument(
        "--region",
        default=AWS_REGION,
        help=f"AWS region (default: {AWS_REGION})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview deletions without making any S3 changes",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt before deleting",
    )
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    # Collect all duplicates across all requested commodities
    all_to_delete: list[str] = []  # keys to delete
    total_objects = 0

    for commodity in args.commodities:
        source = f"usda_gain_{commodity}"
        prefix = f"{RAW_PREFIX}source={source}/"
        objects = list_objects_with_size(s3, args.bucket, prefix)
        total_objects += len(objects)

        if not objects:
            print(f"  {source}: 0 objects — skipped")
            continue

        groups_to_clean, skipped, no_id_keys = find_duplicate_groups(objects)
        dupe_count = sum(len(g["duplicates"]) for g in groups_to_clean.values())

        suffix_parts = []
        if skipped:
            suffix_parts.append(f"{len(skipped)} group(s) size-mismatched → SKIPPED")
        if no_id_keys:
            suffix_parts.append(f"{len(no_id_keys)} key(s) have no report_id")
        suffix = f"  [{', '.join(suffix_parts)}]" if suffix_parts else ""

        print(
            f"  {source}: {len(objects)} total, "
            f"{len(objects) - dupe_count} unique, "
            f"{dupe_count} duplicate(s) to remove"
            f"{suffix}"
        )

        for rid, group in sorted(groups_to_clean.items()):
            keeper_key, keeper_size = group["keeper"]
            keeper_date = _extract_pub_date(keeper_key)
            print(f"    KEEP   [{rid}]  date={keeper_date}  {keeper_key.rsplit('/', 1)[-1]}")
            for dup_key, dup_size in group["duplicates"]:
                dup_date = _extract_pub_date(dup_key)
                print(f"    DELETE [{rid}]  date={dup_date}  {dup_key}")
                all_to_delete.append(dup_key)

        if skipped:
            for rid, entries in skipped:
                print(f"    SKIP   [{rid}]  — sizes differ: {[sz for _, sz in entries]}")

    print(f"\nScanned {total_objects} objects across {len(args.commodities)} commodity/ies.")
    print(f"Duplicates to delete: {len(all_to_delete)}")

    if not all_to_delete:
        print("No duplicates found. Nothing to do.")
        return

    if args.dry_run:
        print("\n[DRY RUN] No objects were deleted. Remove --dry-run to proceed.")
        return

    if not args.yes:
        answer = (
            input(f"\nDelete {len(all_to_delete)} duplicate object(s) from s3://{args.bucket}? [y/N] ")
            .strip()
            .lower()
        )
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    print(f"Deleting {len(all_to_delete)} object(s) ...")
    deleted = delete_keys(s3, args.bucket, all_to_delete)
    print(f"Done. Deleted {deleted} of {len(all_to_delete)} duplicate object(s).")


if __name__ == "__main__":
    main()
