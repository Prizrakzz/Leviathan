"""Build a GAIN commodity manifest YAML from probe output.

Reads from either:
  - scratch/gain/api_results.jsonl     (from probe_gain_api.py --save)
  - scratch/gain/crawl_{commodity}.jsonl   (from probe_gain_http.py)

Produces a clean, deduplicated, sorted YAML manifest consumed by
jobs/ingest/fetch_gain.py.

Usage
-----
For coffee (backwards compat):
    python scratch/gain/build_manifest.py \\
        --source-name usda_gain_coffee \\
        --input scratch/gain/crawl_coffee.jsonl

For wheat (after running probe_gain_http.py for wheat):
    python scratch/gain/build_manifest.py \\
        --source-name usda_gain_wheat \\
        --input scratch/gain/crawl_wheat.jsonl

--output defaults to configs/sources/{source_name}_archive.yaml.
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
_CONFIGS_SOURCES_DIR = _REPO_ROOT / "configs" / "sources"

_API_RESULTS = _SCRATCH_DIR / "api_results.jsonl"
_CRAWL_RESULTS = _SCRATCH_DIR / "crawl_results.jsonl"  # legacy default

# ---------------------------------------------------------------------------
# Country ISO2 mapping (must stay in sync with probe scripts)
# ---------------------------------------------------------------------------

# Comprehensive country name → ISO2 mapping covering all GAIN commodity producers.
# Keys are lowercase substrings that appear in FAS report titles.
COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    # Coffee origins
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
    # Grains / wheat / corn / rice / oilseeds / softs
    "united states": "US",
    "france": "FR",
    "australia": "AU",
    "canada": "CA",
    "ukraine": "UA",
    "russia": "RU",
    "russian federation": "RU",
    "pakistan": "PK",
    "egypt": "EG",
    "argentina": "AR",
    "china": "CN",
    "germany": "DE",
    "poland": "PL",
    "turkey": "TR",
    "türkiye": "TR",
    "turkiye": "TR",
    "south africa": "ZA",
    "nigeria": "NG",
    "thailand": "TH",
    "ghana": "GH",
    "paraguay": "PY",
    "bolivia": "BO",
    "ecuador": "EC",
    "uzbekistan": "UZ",
    "malaysia": "MY",
    "myanmar": "MM",
    "burma": "MM",
    "taiwan": "TW",
    "south korea": "KR",
    "korea": "KR",
    "japan": "JP",
    "senegal": "SN",
    "nicaragua": "NI",
    "costa rica": "CR",
    "el salvador": "SV",
    "dominican republic": "DO",
    "haiti": "HT",
    "venezuela": "VE",
    "chile": "CL",
    "uruguay": "UY",
    "zambia": "ZM",
    "zimbabwe": "ZW",
    "mozambique": "MZ",
    "rwanda": "RW",
    "burundi": "BI",
    "angola": "AO",
    "sri lanka": "LK",
    "nepal": "NP",
    "bangladesh": "BD",
    "iran": "IR",
    "iraq": "IQ",
    "saudi arabia": "SA",
    "kazakhstan": "KZ",
    "romania": "RO",
    "hungary": "HU",
    "spain": "ES",
    "italy": "IT",
    "netherlands": "NL",
    "belgium": "BE",
    "austria": "AT",
    "new zealand": "NZ",
}


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

def _normalise_api_record(raw: dict, target_iso2: set[str]) -> dict | None:
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

    iso2 = (
        _iso2_from_name(country_name)
        or (country_code if len(country_code) == 2 else "")
    )

    if not iso2:
        return None
    if target_iso2 and iso2 not in target_iso2:
        return None

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


def _normalise_playwright_record(raw: dict, target_iso2: set[str]) -> dict | None:
    """Normalise a record from probe_gain_playwright.py or probe_gain_http.py."""
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

    if not iso2:
        return None
    if target_iso2 and iso2 not in target_iso2:
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
    parser = argparse.ArgumentParser(description="Build GAIN commodity manifest YAML.")
    parser.add_argument(
        "--source-name",
        required=True,
        metavar="SOURCE_NAME",
        help=(
            "Source identifier for the YAML manifest, e.g. 'usda_gain_wheat'. "
            "Output defaults to configs/sources/{source_name}_archive.yaml."
        ),
    )
    parser.add_argument(
        "--input",
        default=None,
        metavar="PATH",
        help=(
            "Input JSONL file from probe_gain_http.py "
            "(default: auto-detect api_results.jsonl or crawl_results.jsonl)."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Output YAML manifest path (default: configs/sources/{source_name}_archive.yaml).",
    )
    parser.add_argument(
        "--source",
        choices=["api", "playwright", "auto"],
        default="auto",
        help="Which probe format to normalise: 'api' (newgainapi JSON) or 'playwright'/'auto' (HTTP crawler).",
    )
    args = parser.parse_args()

    source_name = args.source_name.strip()
    out_manifest = (
        Path(args.output)
        if args.output
        else _CONFIGS_SOURCES_DIR / f"{source_name}_archive.yaml"
    )

    # Determine input file
    if args.input:
        input_path = Path(args.input)
        detected_source = args.source if args.source != "auto" else "playwright"
    elif args.source == "auto":
        if _API_RESULTS.exists():
            input_path = _API_RESULTS
            detected_source = "api"
            print("Auto-detected: api_results.jsonl")
        elif _CRAWL_RESULTS.exists():
            input_path = _CRAWL_RESULTS
            detected_source = "playwright"
            print("Auto-detected: crawl_results.jsonl")
        else:
            print(
                "ERROR: Neither api_results.jsonl nor crawl_results.jsonl found.\n"
                "Run probe_gain_http.py first, or pass --input PATH."
            )
            raise SystemExit(1)
    else:
        input_path = _API_RESULTS if args.source == "api" else _CRAWL_RESULTS
        detected_source = args.source

    if not input_path.exists():
        print(f"ERROR: {input_path} not found.")
        raise SystemExit(1)

    # target_iso2 = empty set means accept all countries (probe already filtered)
    target_iso2: set[str] = set()
    normalise_fn = _normalise_api_record if detected_source == "api" else _normalise_playwright_record

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

            norm = normalise_fn(raw, target_iso2)
            if norm is None:
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

    # Sort: country_iso2 asc, then publication_date desc within each country
    from itertools import groupby
    from collections import Counter
    deduped.sort(key=lambda r: (r["country_iso2"], r["publication_date"]))
    sorted_records: list[dict] = []
    for iso2, group in groupby(deduped, key=lambda r: r["country_iso2"]):
        sorted_records.extend(sorted(group, key=lambda r: r["publication_date"], reverse=True))

    # Country summary
    country_counts = Counter(r["country_iso2"] for r in sorted_records)
    print("\nRecords per country:")
    for iso2, count in sorted(country_counts.items()):
        print(f"  {iso2}: {count}")

    # Build YAML structure
    manifest = {
        "source": source_name,
        "generated": date.today().strftime("%Y-%m-%d"),
        "total_records": len(sorted_records),
        "target_countries": sorted(country_counts.keys()),
        "reports": sorted_records,
    }

    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(out_manifest, "w", encoding="utf-8") as fh:
        yaml.dump(
            manifest,
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=120,
        )

    print(f"\nManifest written: {out_manifest}")
    print(f"Total reports: {len(sorted_records)}")
    print(
        f"\nNext step: python jobs/ingest/fetch_gain.py "
        f"--source {source_name} --dry-run --limit 5"
    )


if __name__ == "__main__":
    main()
