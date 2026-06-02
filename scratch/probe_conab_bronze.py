"""Inspect a CONAB XLS bronze Parquet and sample a PDF."""
import boto3
import io
import pandas as pd

s3 = boto3.client("s3", region_name="us-east-1")
bucket = "leviathan-dev-shahem-001"
pag = s3.get_paginator("list_objects_v2")

# --- List all bronze conab_xls partitions ---
bronze_keys = []
for page in pag.paginate(Bucket=bucket, Prefix="bronze/production/source=conab_xls/"):
    for obj in page.get("Contents", []):
        bronze_keys.append(obj["Key"])

print(f"Bronze conab_xls partitions: {len(bronze_keys)}")
for k in sorted(bronze_keys):
    print(f"  {k}")

# --- Read one parquet ---
if bronze_keys:
    sample_key = sorted(bronze_keys)[0]
    print(f"\nReading: {sample_key}")
    obj = s3.get_object(Bucket=bucket, Key=sample_key)
    df = pd.read_parquet(io.BytesIO(obj["Body"].read()))
    print(f"  Shape: {df.shape}")
    print(f"  Columns: {list(df.columns)}")
    print(f"  Dtypes:\n{df.dtypes}")
    print(f"\nSample rows:")
    print(df.head(10).to_string())
    print(f"\nUnique commodities: {df['commodity'].unique().tolist() if 'commodity' in df.columns else 'N/A'}")
    print(f"Unique elements: {df['element'].unique().tolist() if 'element' in df.columns else 'N/A'}")
    print(f"Unique regions: {sorted(df['region'].unique().tolist()) if 'region' in df.columns else 'N/A'}")

# --- Also check the single .doc file ---
print("\n\n=== .doc file info ===")
for page in pag.paginate(Bucket=bucket, Prefix="raw/production/source=conab/"):
    for obj in page.get("Contents", []):
        if obj["Key"].endswith(".doc"):
            print(f"  Key: {obj['Key']}")
            print(f"  Size: {obj['Size']:,} bytes")
