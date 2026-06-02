"""Probe 1985 WASDE scanned PDF — show table pages from Textract LINE output."""
import boto3
import time
from collections import defaultdict

BUCKET = "leviathan-dev-shahem-001"
s3 = boto3.client("s3", region_name="us-east-1")
textract = boto3.client("textract", region_name="us-east-1")

key = "raw/production/source=usda_wasde/release_date=1985-01-11/wasde0185.pdf"
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

# Paginate to collect ALL blocks
all_blocks = list(r.get("Blocks", []))
while r.get("NextToken"):
    r = textract.get_document_text_detection(JobId=jid, NextToken=r["NextToken"])
    all_blocks.extend(r.get("Blocks", []))

s3.delete_object(Bucket=BUCKET, Key=tmp_key)

by_page = defaultdict(list)
for b in all_blocks:
    if b.get("BlockType") == "LINE":
        by_page[b.get("Page", 0)].append(b["Text"])

print(f"Total pages seen: {max(by_page)}, total lines: {sum(len(v) for v in by_page.values())}")
for pg in sorted(by_page.keys()):
    if pg < 8 or pg > 16:
        continue
    print(f"\n=== PAGE {pg} ===")
    for line in by_page[pg]:
        print(" ", repr(line))
