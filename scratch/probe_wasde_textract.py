"""Debug probe: compare TEXT vs TABLE Textract output on 1973 WASDE scanned PDF."""
import boto3
import time

BUCKET = "leviathan-dev-shahem-001"
KEY = "raw/production/source=usda_wasde/release_date=1973-09-17/wasde0973.pdf"
TMP_KEY = "text/tmp/debug_wasde0973.pdf"

s3 = boto3.client("s3", region_name="us-east-1")
textract = boto3.client("textract", region_name="us-east-1")

raw = s3.get_object(Bucket=BUCKET, Key=KEY)["Body"].read()
s3.put_object(Bucket=BUCKET, Key=TMP_KEY, Body=raw)
print(f"Uploaded {len(raw)//1024} KB to {TMP_KEY}")

# --- Run TABLES analysis ---
resp = textract.start_document_analysis(
    DocumentLocation={"S3Object": {"Bucket": BUCKET, "Name": TMP_KEY}},
    FeatureTypes=["TABLES"],
)
job_id = resp["JobId"]
print("Job:", job_id)

while True:
    time.sleep(3)
    r = textract.get_document_analysis(JobId=job_id)
    status = r["JobStatus"]
    print("Status:", status)
    if status in ("SUCCEEDED", "FAILED"):
        break

if status == "FAILED":
    print("FAILED:", r.get("StatusMessage"))
    s3.delete_object(Bucket=BUCKET, Key=TMP_KEY)
    raise SystemExit(1)

blocks = r.get("Blocks", [])
block_map = {b["Id"]: b for b in blocks}

type_counts = {}
for b in blocks:
    t = b.get("BlockType", "?")
    type_counts[t] = type_counts.get(t, 0) + 1
print("Block types:", type_counts)

# Print all LINE text to see document content
print("\n--- ALL LINES ---")
for b in blocks:
    if b.get("BlockType") == "LINE":
        print(f"  p{b.get('Page', '?')}: {b['Text']!r}")

# Print table cells
tables = [b for b in blocks if b.get("BlockType") == "TABLE"]
print(f"\n--- {len(tables)} TABLE(s) found ---")
for ti, tbl in enumerate(tables):
    cells = []
    for rel in tbl.get("Relationships", []):
        if rel["Type"] == "CHILD":
            for cid in rel["Ids"]:
                cell = block_map.get(cid, {})
                if cell.get("BlockType") == "CELL":
                    # get text of this cell
                    text_parts = []
                    for crel in cell.get("Relationships", []):
                        if crel["Type"] == "CHILD":
                            for wid in crel["Ids"]:
                                w = block_map.get(wid, {})
                                if w.get("BlockType") in ("WORD", "SELECTION_ELEMENT"):
                                    text_parts.append(w.get("Text", ""))
                    cells.append((
                        cell.get("RowIndex", 0),
                        cell.get("ColumnIndex", 0),
                        " ".join(text_parts),
                    ))
    cells.sort()
    print(f"\n  TABLE {ti+1} ({len(cells)} cells):")
    for row, col, text in cells[:50]:
        print(f"    [{row},{col}] {text!r}")

s3.delete_object(Bucket=BUCKET, Key=TMP_KEY)
