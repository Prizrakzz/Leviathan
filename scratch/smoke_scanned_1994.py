"""Smoke test: run the fixed parse_wasde_pdf_scanned against a real 1994 WASDE PDF."""
import io
import sys
import time
import boto3

from leviathan.storage.s3 import list_s3_keys
from leviathan.transforms.raw_to_text.wasde_scanned import _is_scanned_key
from jobs.batch.wasde_bronze_scanned_task import (
    _collect_line_blocks,
    _strip_narrative_pages,
    _TMP_PREFIX,
    _POLL_INTERVAL_SECONDS,
)
from leviathan.transforms.raw_to_bronze.usda_wasde import parse_wasde_pdf_scanned

BUCKET = "leviathan-dev-shahem-001"
REGION = "us-east-1"

s3 = boto3.client("s3", region_name=REGION)
textract = boto3.client("textract", region_name=REGION)

all_keys = list_s3_keys(BUCKET, "raw/production/source=usda_wasde/", aws_region=REGION)
keys_1994 = sorted(k for k in all_keys if _is_scanned_key(k) and "1994" in k)
print(f"1994 scanned keys found: {len(keys_1994)}")
if not keys_1994:
    print("ERROR: No 1994 keys found under raw prefix")
    sys.exit(1)

key = keys_1994[0]
print(f"Processing: {key}")

obj = s3.get_object(Bucket=BUCKET, Key=key)
pdf_bytes = _strip_narrative_pages(obj["Body"].read())
print(f"PDF bytes after stripping: {len(pdf_bytes)}")

# Upload to tmp and start Textract job
tmp_key = f"{_TMP_PREFIX}smoke-1994/input.pdf"
s3.put_object(Bucket=BUCKET, Key=tmp_key, Body=pdf_bytes, ContentType="application/pdf")
resp = textract.start_document_text_detection(
    DocumentLocation={"S3Object": {"Bucket": BUCKET, "Name": tmp_key}}
)
job_id = resp["JobId"]
print(f"Textract job submitted: {job_id}")

# Poll until complete
while True:
    status_resp = textract.get_document_text_detection(JobId=job_id)
    status = status_resp["JobStatus"]
    print(f"  status={status}")
    if status in ("SUCCEEDED", "FAILED"):
        break
    time.sleep(_POLL_INTERVAL_SECONDS)

if status == "FAILED":
    print(f"FAIL: Textract job failed: {status_resp.get('StatusMessage')}")
    sys.exit(1)

blocks = _collect_line_blocks(textract, job_id)
print(f"LINE blocks collected: {len(blocks)}")

s3.delete_object(Bucket=BUCKET, Key=tmp_key)

release_date = key.split("release_date=")[1].split("/")[0]
df = parse_wasde_pdf_scanned(blocks, release_date)
print(f"\nRows parsed: {len(df)}")

if len(df) == 0:
    print("FAIL: 0 rows — parser fix did not work against real data")
    sys.exit(1)

print("\nSample output (first 15 rows):")
print(df[["region", "market_year", "attribute", "value"]].head(15).to_string())

print("\nDistinct tables:")
for t in df["table_name"].unique():
    print(f"  {t}")

print("\nDistinct attributes:")
print(sorted(df["attribute"].unique()))

arg = df[(df["region"] == "Argentina") & (df["attribute"] == "imports")]
if not arg.empty:
    print(f"\nArgentina imports rows:\n{arg[['market_year','value']].to_string()}")

print("\nSMOKE TEST PASSED")

