"""One-shot probe: inspect unit_id and value magnitudes in bronze ESR Parquet."""
import boto3
import io
import pandas as pd

s3 = boto3.client("s3", region_name="us-east-1")
bucket = "leviathan-dev-shahem-001"

# Collect a few keys across different commodity codes
probe_codes = [401, 801, 101]  # corn, soybeans, HRW wheat
all_keys = []

paginator = s3.get_paginator("list_objects_v2")
for code in probe_codes:
    prefix = f"bronze/production/source=usda_esr/commodity_code={code}/"
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            all_keys.append((code, obj["Key"]))
        break  # just first page

print(f"Keys found: {len(all_keys)}")
for code, k in all_keys[:2]:
    print(f"  {code}: {k}")

# Read one Parquet per commodity code
for code, key in all_keys[:3]:
    print(f"\n{'='*60}")
    print(f"commodity_code={code}: {key}")
    obj = s3.get_object(Bucket=bucket, Key=key)
    df = pd.read_parquet(io.BytesIO(obj["Body"].read()))
    print(f"  shape: {df.shape}")
    print(f"  columns: {list(df.columns)}")
    print(f"  unit_id unique: {df['unit_id'].unique().tolist()}")
    print(f"  weekly_exports (first 5): {df['weekly_exports'].head().tolist()}")
    print(f"  weekly_exports describe:\n{df['weekly_exports'].describe()}")
    print(f"  sample row: {df.iloc[0].to_dict()}")
