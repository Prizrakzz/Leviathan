"""Probe 1994 WASDE — check heading format and separator pattern."""
import boto3
import time
from collections import defaultdict

BUCKET = "leviathan-dev-shahem-001"
s3 = boto3.client("s3", region_name="us-east-1")
textract = boto3.client("textract", region_name="us-east-1")

key = "raw/production/source=usda_wasde/release_date=1994-01-12/wasde0194.pdf"
raw = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
tmp_key = "text/tmp/debug_probe.pdf"
s3.put_object(Bucket=BUCKET, Key=tmp_key, Body=raw)

resp = textract.start_document_text_detection(
    DocumentLocation={"S3Object": {"Bucket": BUCKET, "Name": tmp_key}}
)
jid = resp["JobId"]
print("Job:", jid)
while True:
    time.sleep(4)
    r = textract.get_document_text_detection(JobId=jid)
    if r["JobStatus"] in ("SUCCEEDED", "FAILED"):
        print("Status:", r["JobStatus"])
        break

all_blocks = list(r.get("Blocks", []))
while r.get("NextToken"):
    r = textract.get_document_text_detection(JobId=jid, NextToken=r["NextToken"])
    all_blocks.extend(r.get("Blocks", []))

s3.delete_object(Bucket=BUCKET, Key=tmp_key)

# Print all LINE text to look for "Supply and Use" and ===== patterns
lines_by_page = defaultdict(list)
for b in all_blocks:
    if b.get("BlockType") == "LINE":
        lines_by_page[b.get("Page", 0)].append(b["Text"])

total_pages = max(lines_by_page)
total_lines = sum(len(v) for v in lines_by_page.values())
print(f"Pages: {total_pages}, lines: {total_lines}")

# Find all headings and separators
print("\n--- SEARCHING FOR HEADINGS ---")
for pg in sorted(lines_by_page.keys()):
    for txt in lines_by_page[pg]:
        if any(kw in txt for kw in ["Supply and Use", "supply and use", "SUPPLY AND USE", "====="]):
            print(f"  p{pg}: {txt!r}")

# Show first 5 lines of each table page (pages 9+)
print("\n--- TABLE PAGE FIRST LINES ---")
for pg in sorted(lines_by_page.keys()):
    if pg >= 9:
        first = lines_by_page[pg][:8]
        print(f"  p{pg}: {[l for l in first]}")
