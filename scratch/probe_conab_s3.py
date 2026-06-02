"""Probe CONAB S3 state: raw PDFs, raw XLS, bronze, silver."""
import boto3

s3 = boto3.client("s3", region_name="us-east-1")
pag = s3.get_paginator("list_objects_v2")
bucket = "leviathan-dev-shahem-001"

def count_prefix(prefix, suffix=None):
    total = 0
    keys = []
    for page in pag.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if suffix is None or k.endswith(suffix):
                total += 1
                keys.append(k)
    return total, keys

# --- Raw PDF bulletins ---
n_pdf, pdf_keys = count_prefix("raw/production/source=conab/crop_year=")
print(f"\n=== raw/source=conab PDF bulletins ===")
print(f"  Total objects: {n_pdf}")
exts = {}
for k in pdf_keys:
    ext = k.rsplit(".", 1)[-1].lower() if "." in k.split("/")[-1] else "no_ext"
    exts[ext] = exts.get(ext, 0) + 1
print(f"  By extension: {exts}")

# Show unique crop_years
crop_years = sorted(set(k.split("crop_year=")[1].split("/")[0] for k in pdf_keys))
print(f"  crop_years ({len(crop_years)}): {crop_years}")

# --- Raw XLS files ---
n_xls, xls_keys = count_prefix("raw/production/source=conab/bulletin_xls/")
print(f"\n=== raw/source=conab XLS files ===")
print(f"  Total objects: {n_xls}")
if xls_keys:
    safra_years = sorted(set(k.split("safra_year=")[1].split("/")[0] for k in xls_keys if "safra_year=" in k))
    print(f"  safra_years: {safra_years}")

# --- Bronze (conab_xls) ---
n_bronze, bronze_keys = count_prefix("bronze/production/source=conab_xls/")
print(f"\n=== bronze/source=conab_xls ===")
print(f"  Total partitions: {n_bronze}")
if bronze_keys:
    years = sorted(set(k.split("safra_year=")[1].split("/")[0] for k in bronze_keys if "safra_year=" in k))
    print(f"  safra_years: {years}")

# --- Bronze (conab) fallback ---
n_b2, b2_keys = count_prefix("bronze/production/source=conab/")
print(f"\n=== bronze/source=conab (direct) ===")
print(f"  Total: {n_b2}")

# --- Text layer ---
n_text, text_keys = count_prefix("text/source=conab/")
n_text2, text2_keys = count_prefix("text/production/source=conab/")
print(f"\n=== text/source=conab ===")
print(f"  text/ (no production/): {n_text}")
print(f"  text/production/: {n_text2}")

# --- Silver ---
n_silver, _ = count_prefix("silver/production/source=conab")
print(f"\n=== silver/production/source=conab* ===")
print(f"  Total: {n_silver}")

# --- Sample a few PDF keys ---
print(f"\n=== Sample raw PDF keys ===")
for k in sorted(pdf_keys)[:10]:
    print(f"  {k}")
if len(pdf_keys) > 10:
    print(f"  ... ({len(pdf_keys) - 10} more)")
