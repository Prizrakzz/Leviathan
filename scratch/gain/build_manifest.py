"""Build configs/sources/usda_gain_coffee_archive.yaml from probe output.

Reads from either:
  - scratch/gain/api_results.jsonl     (from probe_gain_api.py --save)
  - scratch/gain/crawl_results.jsonl   (from probe_gain_playwright.py)

Produces a clean, deduplicated, sorted YAML manifest consumed by
jobs/ingest/fetch_gain_coffee.py.

Usage
-----
    python scratch/gain/build_manifest.py --source api
    python scratch/gain/build_manifest.py --source playwright
    python scratch/gain/build_manifest.py  # auto-detects whichever file exists
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, date
from pathlib import Path
from urllib.parse import unquote

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SCRATCH_DIR = Path(__file__).parent
_REPO_ROOT = _SCRATCH_DIR.parent.parent  # scratch/ → Leviathan/
_OUT_MANIFEST = _REPO_ROOT / "configs" / "sources" / "usda_gain_coffee_archive.yaml"

_API_RESULTS = _SCRATCH_DIR / "api_results.jsonl"
_CRAWL_RESULTS = _SCRATCH_DIR / "crawl_results.jsonl"

# ---------------------------------------------------------------------------
# Country ISO2 mapping (must stay in sync with probe scripts)
# ---------------------------------------------------------------------------

COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "brazil": "BR",
    "colombia": "CO",
    "ethiopia": "ET",
    "vietnam": "VN",
    "viet nam": "VN",
    "indonesia": "ID",
    "honduras": "HN",
    "guatemala": "GT",
    "peru": "PE",
    "mexico": "MX",
    "uganda": "UG",
    "india": "IN",
    "tanzania": "TZ",
    "kenya": "KE",
    "cote d'ivoire": "CI",
    "côte d'ivoire": "CI",
    "ivory coast": "CI",
    "cameroon": "CM",
    "papua new guinea": "PG",
    "philippines": "PH",
    "laos": "LA",
    "lao p.d.r.": "LA",
    "lao pdr": "LA",
    "lao people": "LA",
}

TARGET_ISO2: set[str] = set(COUNTRY_NAME_TO_ISO2.values())


def _iso2_from_name(name: str) -> str | None:
    nl = name.lower().strip()
    for key, iso2 in COUNTRY_NAME_TO_ISO2.items():
        if key in nl:
            return iso2
    return None


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %Y",
    "%b %Y",
    "%m/%d/%Y",
    "%Y%m%d",
]


def _parse_date(raw: str) -> str | None:
    """Return YYYYMMDD string or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    # Already in YYYYMMDD
    if re.match(r"^\d{8}$", raw):
        return raw
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(raw[:len(fmt.replace("%", "XX").replace("X", "1"))], fmt)
            return dt.strftime("%Y%m%d")
        except ValueError:
            continue
    # Try partial: "May 2026" → 20260501 (approximate — use 1st of month)
    m = re.match(r"([A-Za-z]+)\s+(\d{4})", raw)
    if m:
        try:
            dt = datetime.strptime(f"01 {m.group(1)} {m.group(2)}", "%d %B %Y")
            return dt.strftime("%Y%m%d")
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Filename / URL parsing
# ---------------------------------------------------------------------------

# "Coffee Annual_Nairobi_Kenya_KE2026-0011.pdf"
_PDF_FILENAME_RE = re.compile(
    r"(?P<category>[^_]+(?:\s[^_]+)*)"
    r"_(?P<post>[^_]+)"
    r"_(?P<country_name>[^_]+)"
    r"_(?P<report_id>[A-Z]{2}\d{4}-\d{4})"
    r"\.pdf$",
    re.IGNORECASE,
)
# Date embedded in URL path: /gain-report/2026/05/ or /2026/05/
_URL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/")


def _parse_pdf_url(pdf_url: str) -> dict:
    """Extract structured fields from a GAIN PDF URL."""
    decoded = unquote(pdf_url)
    filename = decoded.rstrip("/").split("/")[-1]

    result: dict = {
        "category": "",
        "post": "",
        "country_name_in_url": "",
        "report_id": "",
        "filename_clean": filename.replace(" ", "_"),
        "pub_year": None,
        "pub_month": None,
    }

    m = _PDF_FILENAME_RE.match(filename)
    if m:
        result["category"] = m.group("category").strip()
        result["post"] = m.group("post").strip()
        result["country_name_in_url"] = m.group("country_name").strip()
        result["report_id"] = m.group("report_id").upper()

    dm = _URL_DATE_RE.search(pdf_url)
    if dm:
        result["pub_year"] = int(dm.group(1))
        result["pub_month"] = int(dm.group(2))

    return result


# ---------------------------------------------------------------------------
# Normalise a raw record from either source
# ---------------------------------------------------------------------------

def _normalise_api_record(raw: dict) -> dict | None:
    """Normalise a record from probe_gain_api.py (newgainapi JSON format)."""
    # Typical newgainapi fields (case varies):
    report_id = (
        raw.get("GainReportNumber") or
        raw.get("ReportNumber") or
        raw.get("report_id") or ""
    ).upper()

    country_name = (
        raw.get("CountryName") or
        raw.get("countryName") or
        raw.get("country_name") or ""
    )

    country_code = (
        raw.get("CountryCode") or
        raw.get("countryCode") or
        raw.get("country_code") or
        report_id[:2] if report_id else ""
    ).upper()

    # Try to resolve ISO2
    iso2 = (
        country_code if country_code in TARGET_ISO2
        else _iso2_from_name(country_name)
    )

    attachments = raw.get("Attachments") or raw.get("attachments") or []
    pdf_url = ""
    for att in attachments:
        url = att.get("FileURL") or att.get("file_url") or att.get("url") or ""
        if url.lower().endswith(".pdf"):
            pdf_url = url
            break

    if not pdf_url:
        return None

    pub_date_raw = (
        raw.get("ReportDate") or
        raw.get("reportDate") or
        raw.get("publication_date") or ""
    )
    publication_date = _parse_date(pub_date_raw)

    if not publication_date:
        # Try from URL
        parsed = _parse_pdf_url(pdf_url)
        if parsed["pub_year"] and parsed["pub_month"]:
            publication_date = f"{parsed['pub_year']}{parsed['pub_month']:02d}01"

    post = raw.get("PostName") or raw.get("postName") or raw.get("post") or ""
    category = (
        raw.get("ReportCategory") or
        raw.get("reportCategory") or
        raw.get("category") or ""
    )

    url_parsed = _parse_pdf_url(pdf_url)
    filename_clean = url_parsed["filename_clean"]

    return {
        "report_id": report_id,
        "country_iso2": iso2 or "",
        "country_name": country_name,
        "post": post,
        "category": category,
        "publication_date": publication_date or "",
        "pdf_url": pdf_url,
        "filename_clean": filename_clean,
    }


def _normalise_playwright_record(raw: dict) -> dict | None:
    """Normalise a record from probe_gain_playwright.py."""
    pdf_url = raw.get("pdf_url") or ""
    if not pdf_url:
        return None

    report_id = (raw.get("report_id") or "").upper()
    iso2 = raw.get("country_iso2") or (report_id[:2] if report_id else "")
    country_name = (
        raw.get("country_name_from_file") or
        raw.get("country_name_page") or ""
    )
    post = raw.get("post") or ""
    category = raw.get("category") or ""
    filename_clean = raw.get("filename_clean") or _parse_pdf_url(pdf_url)["filename_clean"]

    pub_date_raw = raw.get("pub_date_raw") or ""
    publication_date = _parse_date(pub_date_raw)
    if not publication_date:
        parsed = _parse_pdf_url(pdf_url)
        if parsed["pub_year"] and parsed["pub_month"]:
            publication_date = f"{parsed['pub_year']}{parsed['pub_month']:02d}01"

    if not iso2 or iso2 not in TARGET_ISO2:
        return None

    return {
        "report_id": report_id,
        "country_iso2": iso2,
        "country_name": country_name,
        "post": post,
        "category": category,
        "publication_date": publication_date or "",
        "pdf_url": pdf_url,
        "filename_clean": filename_clean,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build GAIN coffee manifest YAML.")
    parser.add_argument(
        "--source",
        choices=["api", "playwright", "auto"],
        default="auto",
        help="Which probe output to read (default: auto-detect).",
    )
    parser.add_argument(
        "--include-all-countries",
        action="store_true",
        help="Include countries outside TARGET_ISO2 (for debugging).",
    )
    args = parser.parse_args()

    # Determine source file
    if args.source == "auto":
        if _API_RESULTS.exists():
            source = "api"
            print(f"Auto-detected: api_results.jsonl")
        elif _CRAWL_RESULTS.exists():
            source = "playwright"
            print(f"Auto-detected: crawl_results.jsonl")
        else:
            print(
                "ERROR: Neither api_results.jsonl nor crawl_results.jsonl found.\n"
                "Run probe_gain_api.py --save  or  probe_gain_playwright.py first."
            )
            raise SystemExit(1)
    else:
        source = args.source

    input_path = _API_RESULTS if source == "api" else _CRAWL_RESULTS
    if not input_path.exists():
        print(f"ERROR: {input_path} not found.")
        raise SystemExit(1)

    normalise_fn = _normalise_api_record if source == "api" else _normalise_playwright_record

    # Read + normalise
    records: list[dict] = []
    skipped = 0
    with open(input_path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  [WARN] Line {i}: invalid JSON — {e}")
                skipped += 1
                continue

            norm = normalise_fn(raw)
            if norm is None:
                skipped += 1
                continue

            # Country filter
            if not args.include_all_countries and norm["country_iso2"] not in TARGET_ISO2:
                skipped += 1
                continue

            records.append(norm)

    print(f"Read {len(records) + skipped} raw records, normalised {len(records)}, skipped {skipped}")

    if not records:
        print("ERROR: No records after normalisation. Check probe output.")
        raise SystemExit(1)

    # Deduplicate on report_id (or pdf_url as fallback)
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in records:
        key = r["report_id"] or r["pdf_url"]
        if key and key not in seen:
            seen.add(key)
            deduped.append(r)

    print(f"After dedup: {len(deduped)} records ({len(records) - len(deduped)} duplicates removed)")

    # Sort: country_iso2 asc, then publication_date desc
    deduped.sort(key=lambda r: (r["country_iso2"], r["publication_date"]), reverse=False)
    # Secondary: within same country, newest first
    from itertools import groupby
    sorted_records: list[dict] = []
    for iso2, group in groupby(deduped, key=lambda r: r["country_iso2"]):
        sorted_records.extend(sorted(group, key=lambda r: r["publication_date"], reverse=True))

    # Country summary
    from collections import Counter
    country_counts = Counter(r["country_iso2"] for r in sorted_records)
    print("\nRecords per country:")
    for iso2, count in sorted(country_counts.items()):
        print(f"  {iso2}: {count}")

    # Build YAML structure
    manifest = {
        "source": "usda_gain_coffee",
        "generated": date.today().strftime("%Y-%m-%d"),
        "total_records": len(sorted_records),
        "target_countries": sorted(TARGET_ISO2),
        "reports": sorted_records,
    }

    _OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT_MANIFEST, "w", encoding="utf-8") as fh:
        yaml.dump(
            manifest,
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=120,
        )

    print(f"\nManifest written: {_OUT_MANIFEST}")
    print(f"Total reports: {len(sorted_records)}")
    print("\nNext step: python jobs/ingest/fetch_gain_coffee.py --dry-run --limit 5 --country-codes BR")


if __name__ == "__main__":
    main()
