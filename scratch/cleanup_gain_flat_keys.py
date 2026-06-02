"""Delete stale text/ keys that use the old flat format (no document= partition).

Old format: text/source={src}/country={c}/publication_date={d}/document.json
New format: text/source={src}/country={c}/publication_date={d}/document={slug}/document.json

Run AFTER all rekey jobs complete and counts match raw PDF counts.
Pass --dry-run first to confirm what will be deleted.
"""
from __future__ import annotations

import argparse
import sys

import boto3

BUCKET = "leviathan-dev-shahem-001"

SOURCES = [
    "usda_gain_cocoa", "usda_gain_coffee", "usda_gain_coffee_semiannual",
    "usda_gain_corn", "usda_gain_cotton", "usda_gain_cotton_monthly",
    "usda_gain_grain_monthly", "usda_gain_orange_juice", "usda_gain_palm_oil",
    "usda_gain_rapeseed", "usda_gain_rice", "usda_gain_soybean_meal",
    "usda_gain_soybean_oil", "usda_gain_soybeans", "usda_gain_sugar",
    "usda_gain_sugar_semiannual", "usda_gain_wheat",
]

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

s3 = boto3.client("s3", region_name="us-east-1")
pag = s3.get_paginator("list_objects_v2")

stale: list[str] = []
for source in SOURCES:
    prefix = f"text/source={source}/"
    for page in pag.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parts = key.split("/")
            # Old format ends with: .../publication_date=YYYYMMDD/document.json
            # New format ends with: .../publication_date=YYYYMMDD/document={slug}/document.json
            if parts[-1] == "document.json" and not parts[-2].startswith("document="):
                stale.append(key)

print(f"Stale flat keys found: {len(stale)}")
if args.dry_run:
    for k in stale[:20]:
        print(f"  {k}")
    if len(stale) > 20:
        print(f"  ... and {len(stale) - 20} more")
    print("\n[DRY RUN] No deletions performed.")
    sys.exit(0)

# Batch delete in groups of 1000
deleted = 0
for i in range(0, len(stale), 1000):
    batch = stale[i:i + 1000]
    s3.delete_objects(
        Bucket=BUCKET,
        Delete={"Objects": [{"Key": k} for k in batch]},
    )
    deleted += len(batch)
    print(f"Deleted {deleted}/{len(stale)}")

print(f"Done. {deleted} stale keys removed.")
