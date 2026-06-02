"""Diagnose why 1989+ WASDE files produce near-zero rows.

Downloads a 1989-02 file (rows=9, clearly broken) and a 1988-12 file (rows=272, working),
runs Textract on both, then prints:
1. The reconstructed Y-grouped lines for each (first 80 lines after stripping narrative pages)
2. What _parse_colon_page sees and whether headings are found
3. What _inject_scanned_seps produces
"""
from __future__ import annotations
import io, sys, time, textwrap
import boto3
import pypdf

sys.path.insert(0, ".")
from leviathan.transforms.raw_to_bronze.usda_wasde import (
    parse_wasde_pdf_scanned,
    _parse_colon_page,
    _inject_scanned_seps,
    _SCANNED_Y_TOLERANCE,
)
from leviathan.storage.s3 import s3_download_with_retry, get_thread_local_s3_client

BUCKET = "leviathan-dev-shahem-001"
REGION = "us-east-1"
SKIP_PAGES = 8
POLL_INTERVAL = 5

FILES = {
    "1988-12 (good, rows=272)": "raw/production/source=usda_wasde/release_date=1988-12-12/wasde1288.pdf",
    "1989-02 (bad,  rows=9)":   "raw/production/source=usda_wasde/release_date=1989-02-09/wasde0289.pdf",
    "1989-07 (bad,  rows=1)":   "raw/production/source=usda_wasde/release_date=1989-07-12/wasde0789.pdf",
}


def strip_pages(pdf_bytes: bytes) -> bytes:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)
    if total <= SKIP_PAGES:
        return pdf_bytes
    writer = pypdf.PdfWriter()
    for page in reader.pages[SKIP_PAGES:]:
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def submit_and_collect(s3_client, textract_client, key: str) -> list[dict]:
    pdf_bytes = s3_download_with_retry(BUCKET, key, s3_client)
    stripped = strip_pages(pdf_bytes)
    tmp_key = f"text/tmp/diag/{key.split('/')[-1]}"
    s3_client.put_object(Bucket=BUCKET, Key=tmp_key, Body=stripped, ContentType="application/pdf")
    job_id = textract_client.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": BUCKET, "Name": tmp_key}}
    )["JobId"]
    print(f"  Textract job={job_id[:16]}... submitted", flush=True)
    while True:
        time.sleep(POLL_INTERVAL)
        resp = textract_client.get_document_text_detection(JobId=job_id)
        if resp["JobStatus"] in ("SUCCEEDED", "FAILED"):
            break
        print("  polling...", flush=True)
    blocks: list[dict] = []
    kwargs: dict = {"JobId": job_id}
    while True:
        resp = textract_client.get_document_text_detection(**kwargs)
        for b in resp.get("Blocks", []):
            if b.get("BlockType") == "LINE":
                blocks.append(b)
        nt = resp.get("NextToken")
        if not nt:
            break
        kwargs["NextToken"] = nt
    s3_client.delete_object(Bucket=BUCKET, Key=tmp_key)
    return blocks


def reconstruct_lines(blocks: list[dict]) -> list[tuple[int, str]]:
    """Return [(page, text), ...] grouped by Y bucket, sorted page+Y+X."""
    from collections import defaultdict
    buckets: dict[tuple, list[tuple[float, str]]] = defaultdict(list)
    for b in blocks:
        pg = b.get("Page", 1)
        bb = b.get("Geometry", {}).get("BoundingBox", {})
        top = bb.get("Top", 0)
        left = bb.get("Left", 0)
        y_bucket = round(top / _SCANNED_Y_TOLERANCE)
        buckets[(pg, y_bucket)].append((left, b.get("Text", "")))
    rows = []
    for (pg, yb), frags in sorted(buckets.items()):
        text = " ".join(t for _, t in sorted(frags))
        rows.append((pg, text))
    return rows


def main():
    s3 = get_thread_local_s3_client(REGION)
    textract = boto3.client("textract", region_name=REGION)

    for label, key in FILES.items():
        print(f"\n{'='*70}")
        print(f"FILE: {label}")
        print(f"KEY:  {key}")
        print('='*70)

        blocks = submit_and_collect(s3, textract, key)
        lines = reconstruct_lines(blocks)

        # --- Section 1: First 100 reconstructed lines ---
        print(f"\n--- Reconstructed lines (first 100 of {len(lines)}) ---")
        for i, (pg, text) in enumerate(lines[:100]):
            print(f"  [{pg:2d}] {text}")

        # --- Section 2: How many rows does the full parser produce? ---
        release_date = key.split("release_date=")[1].split("/")[0]
        df = parse_wasde_pdf_scanned(blocks, release_date)
        print(f"\n--- parse_wasde_pdf_scanned → {len(df)} rows ---")
        if len(df):
            print(df[["table_name","region","market_year","attribute","value"]].to_string(max_rows=20))

        # --- Section 3: Which headings does _parse_colon_page find? ---
        print("\n--- Heading scan (lines containing 'Supply and Use') ---")
        for i, (pg, text) in enumerate(lines):
            if "supply and use" in text.lower():
                print(f"  line {i:4d} [pg {pg}]: {text[:120]}")

        # --- Section 4: Show what inject_scanned_seps does on first S&U block ---
        print("\n--- _inject_scanned_seps on first Supply and Use block ---")
        # Build page text the same way parse_wasde_pdf_scanned does
        from collections import defaultdict
        page_lines: dict[int, list[str]] = defaultdict(list)
        for pg, text in lines:
            page_lines[pg].append(text)

        for pg in sorted(page_lines):
            page_text = "\n".join(page_lines[pg])
            if "supply and use" not in page_text.lower():
                continue
            # Split into blocks by double-newline equivalent (headings)
            import re
            heading_re = re.compile(r"supply\s+and\s+use", re.I)
            raw_blocks = heading_re.split(page_text)
            print(f"\n  Page {pg}: {len(raw_blocks)-1} heading(s) found")
            # Show injected block for first heading
            if len(raw_blocks) > 1:
                block_text = "Supply and Use" + raw_blocks[1]
                injected = _inject_scanned_seps(block_text.splitlines())
                print(f"  First 30 lines of injected block:")
                for ln in injected[:30]:
                    print(f"    | {ln}")
            break


if __name__ == "__main__":
    main()
