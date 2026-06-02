"""Check scanned WASDE raw key coverage and compare to bronze."""
import boto3
from leviathan.transforms.raw_to_text.wasde_scanned import _is_scanned_key
from leviathan.storage.s3 import list_s3_keys

BUCKET = "leviathan-dev-shahem-001"
REGION = "us-east-1"

all_keys = list_s3_keys(BUCKET, "raw/production/source=usda_wasde/", aws_region=REGION)
scanned = sorted(k for k in all_keys if _is_scanned_key(k))
print(f"Total scanned raw keys: {len(scanned)}")
by_year = {}
for k in scanned:
    y = k.split("release_date=")[1][:4]
    by_year[y] = by_year.get(y, 0) + 1
for yr in sorted(by_year):
    print(f"  {yr}: {by_year[yr]}")
