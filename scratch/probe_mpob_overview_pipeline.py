"""Quick smoke test of the MPOB overview PDF pipeline against the local 2015 PDF."""
from pathlib import Path

pdf_bytes = Path("scratch/mpob_overview_2015.pdf").read_bytes()

# Test text extraction
from leviathan.transforms.raw_to_text.mpob_pdf import extract_mpob_overview

raw_key = "raw/production/source=mpob/release_type=overview_pdf/year=2015/overview.pdf"
doc = extract_mpob_overview(pdf_bytes, raw_key)
print("=== TEXT EXTRACTION ===")
print(f"sections: {len(doc['sections'])}")
print(f"section name: {doc['sections'][0]['name']}")
print(f"full_text chars: {len(doc['full_text'])}")
print(f"first 300 chars: {doc['full_text'][:300]!r}")
print()

# Test bronze extraction
from leviathan.transforms.raw_to_bronze.mpob_pdf import extract_mpob_overview_annual

df = extract_mpob_overview_annual(pdf_bytes, 2015, "2026-05-31")
print("=== BRONZE EXTRACTION ===")
print(df.to_string())
print()

# Test silver transform
from leviathan.transforms.bronze_to_silver.mpob_annual import (
    transform_mpob_annual_bronze_to_silver,
)

silver = transform_mpob_annual_bronze_to_silver(df)
print("=== SILVER TRANSFORM ===")
print(silver.to_string())
