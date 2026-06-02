"""Probe 1994 WASDE: verify Y-grouping reconstructs colon rows correctly.

Uses the still-valid Textract job result (no re-upload needed within 7 days).
"""
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
print(f"Total blocks: {len(all_blocks)}")

# --- Show raw bounding boxes for page 10 (World Wheat) ---
page10 = [b for b in all_blocks if b.get("BlockType") == "LINE" and b.get("Page") == 10]
print(f"\n=== PAGE 10 RAW ({len(page10)} LINE blocks) ===")
for b in page10[:30]:
    bbox = b["Geometry"]["BoundingBox"]
    print(f"  L={bbox['Left']:.3f} T={bbox['Top']:.3f}: {b['Text']!r}")

# --- Y-group page 10 at various tolerances ---
for tol in [0.003, 0.005, 0.008]:
    rows_by_y = defaultdict(list)
    for b in page10:
        bbox = b["Geometry"]["BoundingBox"]
        y_bucket = round(bbox["Top"] / tol)
        rows_by_y[y_bucket].append((bbox["Left"], b["Text"]))
    print(f"\n--- Y-grouping tolerance={tol} ---")
    for y_bucket in sorted(rows_by_y.keys())[:25]:
        tokens = sorted(rows_by_y[y_bucket])
        line = " ".join(t for _, t in tokens)
        print(f"  {repr(line)}")

# --- Also try reconstructing all pages with Y-grouping and test _parse_colon_page ---
print("\n=== TESTING parse_wasde_pdf_scanned FIX (Y-grouped) ===")
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leviathan.transforms.raw_to_bronze.usda_wasde import _parse_colon_page

line_blocks = [b for b in all_blocks if b.get("BlockType") == "LINE"]
rows_by_page_y = defaultdict(list)
for b in line_blocks:
    page = b.get("Page", 1)
    bbox = b.get("Geometry", {}).get("BoundingBox", {})
    y_bucket = (page, round(bbox.get("Top", 0) / 0.005))
    rows_by_page_y[y_bucket].append((bbox.get("Left", 0), b.get("Text", "")))

text_lines = []
prev_page = None
for (page, y_bucket) in sorted(rows_by_page_y.keys()):
    if prev_page is not None and page != prev_page:
        text_lines.append("")
    prev_page = page
    tokens = sorted(rows_by_page_y[(page, y_bucket)])
    text_lines.append(" ".join(t for _, t in tokens))

full_text = "\n".join(text_lines)

# Try with require_sep=True (current behavior) - should return 0
rows_strict = _parse_colon_page(full_text, "1994-01-12")
print(f"require_sep=True  -> {len(rows_strict)} rows")

# Show reconstructed text around "Supply and Use" heading on page 10
lines = full_text.splitlines()
for i, line in enumerate(lines):
    if "World Wheat Supply and Use" in line:
        print(f"\nHeading at line {i}: {line!r}")
        print("Next 8 lines:")
        for j in range(i+1, min(i+9, len(lines))):
            print(f"  [{j}]: {lines[j]!r}")
        break
