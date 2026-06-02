"""Identify missing text keys and probe failing PDFs to diagnose error type."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import boto3
import pdfplumber

BUCKET = "leviathan-dev-shahem-001"
SOURCES = {
    "usda_gain_rapeseed": 2,
    "usda_gain_coffee": 7,
    "usda_gain_sugar": 26,
}

s3 = boto3.client("s3", region_name="us-east-1")
pag = s3.get_paginator("list_objects_v2")


def list_keys(prefix: str, suffix: str = "") -> set[str]:
    out = set()
    for page in pag.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if not suffix or k.endswith(suffix):
                out.add(k)
    return out


def raw_to_text_key(raw_key: str, source: str) -> str:
    """raw/production/source={src}/country={c}/publication_date={d}/report.pdf
       → text/source={src}/country={c}/publication_date={d}/document.json"""
    parts = raw_key.split("/")
    hive = {p.split("=")[0]: p.split("=")[1] for p in parts if "=" in p}
    return (
        f"text/source={source}/country={hive['country']}/"
        f"publication_date={hive['publication_date']}/document.json"
    )


for source, expected_missing in SOURCES.items():
    print(f"\n{'='*60}")
    print(f"Source: {source}  (expected ~{expected_missing} missing)")

    raw_keys = list_keys(f"raw/production/source={source}/", suffix=".pdf")
    text_keys = list_keys(f"text/source={source}/")

    missing_raw: list[str] = []
    for rk in sorted(raw_keys):
        tk = raw_to_text_key(rk, source)
        if tk not in text_keys:
            missing_raw.append(rk)

    print(f"  raw PDFs: {len(raw_keys)}  text docs: {len(text_keys)}  missing: {len(missing_raw)}")

    for rk in missing_raw[:5]:  # probe up to 5
        print(f"\n  Probing: {rk}")
        try:
            resp = s3.get_object(Bucket=BUCKET, Key=rk)
            data = resp["Body"].read()
            size = len(data)
            print(f"    size={size} bytes")

            # Check magic bytes
            magic = data[:8]
            if magic[:4] == b"%PDF":
                print(f"    magic=PDF OK  header={magic!r}")
            else:
                print(f"    magic=UNEXPECTED  header={magic!r}")

            # Try pdfplumber
            try:
                with pdfplumber.open(io.BytesIO(data)) as pdf:
                    n_pages = len(pdf.pages)
                    texts = [p.extract_text() or "" for p in pdf.pages[:3]]
                    total_chars = sum(len(t.strip()) for t in texts)
                    print(f"    pdfplumber: OK  pages={n_pages}  first3_chars={total_chars}")
            except Exception as e:
                print(f"    pdfplumber: FAILED  error={type(e).__name__}: {e}")

        except Exception as e:
            print(f"    S3 download failed: {e}")
