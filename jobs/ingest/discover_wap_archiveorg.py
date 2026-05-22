"""Discover USDA FAS World Agricultural Production PDFs in the Archive.org
``usda-foreignagricultureservice`` collection and write a download manifest.

The Internet Archive holds a digitised collection of USDA FAS publications
dating back to the late 1950s.  This script queries the Archive.org search API
to enumerate WAP items, resolves the canonical PDF download URL for each item,
and writes ``configs/sources/usda_wap_archiveorg_manifest.yaml``.

Run
---
    python jobs/ingest/discover_wap_archiveorg.py [--dry-run] [--sleep-seconds 1.0]

Output
------
    configs/sources/usda_wap_archiveorg_manifest.yaml

    Schema (per entry):
        release_month: "YYYY-MM"   # derived from item date metadata
        url:           "<archive.org download URL>"
        identifier:    "<archive.org item identifier>"
        title:         "<item title>"
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import requests
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEARCH_URL = (
    "https://archive.org/advancedsearch.php"
    "?q=collection%3Ausda-foreignagricultureservice"
    "+title%3A%22world+agricultural+production%22"
    "&fl=identifier,title,date,description"
    "&output=json"
    "&rows=500"
    "&page={page}"
)

_FILES_URL = "https://archive.org/metadata/{identifier}/files"
_DOWNLOAD_BASE = "https://archive.org/download"

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_wap_archiveorg_manifest.yaml"
)

_REQUEST_TIMEOUT_S = 30
_HEADERS = {"User-Agent": "Leviathan-WAP-Discover/1.0 (research; non-commercial)"}

# Patterns used to extract release_month from item date / title.
# Archive.org dates are ISO 8601 (YYYY-MM-DD) or YYYY-MM or YYYY.
_DATE_RE = re.compile(r"(\d{4})-(\d{2})")

# Month abbreviation → number (for titles like "World Agricultural Production - May 1987")
_MONTH_ABBR: dict[str, str] = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    # abbreviations
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "oct": "10", "nov": "11", "dec": "12",
}

_TITLE_MONTH_RE = re.compile(
    r"(\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b)"
    r"[,\s]+(\d{4})",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(url: str, timeout: int = _REQUEST_TIMEOUT_S) -> requests.Response:
    r = requests.get(url, headers=_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def _extract_release_month(date_str: str, title: str) -> str | None:
    """Return YYYY-MM derived from item date or title, or None if not parseable."""
    # Try the item date field first (most reliable)
    if date_str:
        m = _DATE_RE.search(date_str)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        # Year-only date — skip (ambiguous which month)
    # Fall back to title pattern, e.g. "World Agricultural Production - July 1984"
    m = _TITLE_MONTH_RE.search(title)
    if m:
        month_word = m.group(1).lower()
        year = m.group(2)
        month_num = _MONTH_ABBR.get(month_word)
        if month_num:
            return f"{year}-{month_num}"
    return None


def _resolve_pdf_url(identifier: str, sleep_seconds: float) -> str | None:
    """Return the best PDF download URL for an Archive.org item, or None."""
    url = _FILES_URL.format(identifier=identifier)
    try:
        data = _get(url).json()
    except Exception as exc:
        print(f"    [files] ERROR {identifier}: {exc}")
        return None
    finally:
        time.sleep(sleep_seconds)

    files: list[dict] = data.get("result") or []
    # Prefer files whose name ends in .pdf (case-insensitive), pick the largest
    pdfs = [f for f in files if str(f.get("name", "")).lower().endswith(".pdf")]
    if not pdfs:
        # Some items have .pdf.gz or DjVu — skip
        return None
    # Pick the largest PDF (typically the full circular, not a thumbnail)
    pdfs.sort(key=lambda f: int(f.get("size", 0)), reverse=True)
    filename = pdfs[0]["name"]
    return f"{_DOWNLOAD_BASE}/{identifier}/{filename}"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover(sleep_seconds: float) -> list[dict]:
    """
    Query the Archive.org search API for WAP items in the FAS collection,
    resolve the PDF URL for each, and return a list of manifest entries.
    """
    # ------------------------------------------------------------------
    # Stage 1: enumerate items via search API (paginate until empty)
    # ------------------------------------------------------------------
    items: list[dict] = []
    page = 1
    while True:
        url = _SEARCH_URL.format(page=page)
        print(f"Search page {page} ...")
        try:
            data = _get(url).json()
        except Exception as exc:
            print(f"  Search page {page} ERROR: {exc} — stopping")
            break
        docs: list[dict] = data.get("response", {}).get("docs", [])
        if not docs:
            print(f"  Page {page}: no results — done")
            break
        items.extend(docs)
        print(f"  Page {page}: {len(docs)} items (total: {len(items)})")
        if len(docs) < 500:
            break
        page += 1
        time.sleep(sleep_seconds)

    print(f"\nStage 1 complete: {len(items)} items found")

    # ------------------------------------------------------------------
    # Stage 2: resolve PDF URLs and extract release_month
    # ------------------------------------------------------------------
    confirmed: list[dict] = []
    skipped_no_date = 0
    skipped_no_pdf = 0

    for item in items:
        identifier: str = item.get("identifier", "")
        title: str = item.get("title", "")
        date_str: str = item.get("date", "") or ""

        release_month = _extract_release_month(date_str, title)
        if not release_month:
            print(f"  SKIP (no date)  {identifier}  title={title!r}")
            skipped_no_date += 1
            continue

        # Skip anything after July 2002 — already in the modern FAS manifest
        year, month = int(release_month[:4]), int(release_month[5:7])
        if (year, month) >= (2002, 8):
            print(f"  SKIP (covered)  {release_month}  {identifier}")
            continue

        pdf_url = _resolve_pdf_url(identifier, sleep_seconds)
        if not pdf_url:
            print(f"  SKIP (no PDF)   {release_month}  {identifier}  title={title!r}")
            skipped_no_pdf += 1
            continue

        confirmed.append({
            "release_month": release_month,
            "url": pdf_url,
            "identifier": identifier,
            "title": title,
        })
        print(f"  FOUND  {release_month}  {identifier}  →  {pdf_url}")

    # Sort chronologically and deduplicate (keep first encountered per month)
    confirmed.sort(key=lambda e: e["release_month"])
    deduped: list[dict] = []
    seen_months: set[str] = set()
    for entry in confirmed:
        if entry["release_month"] in seen_months:
            print(f"  DUP   {entry['release_month']}  {entry['identifier']} — keeping first")
            continue
        seen_months.add(entry["release_month"])
        deduped.append(entry)

    print(
        f"\nDiscovery complete: {len(deduped)} unique months confirmed"
        f" (skipped: {skipped_no_date} no-date, {skipped_no_pdf} no-PDF)"
    )
    return deduped


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def _save_manifest(entries: list[dict]) -> None:
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        fh.write("# USDA FAS World Agricultural Production — Archive.org historical PDFs\n")
        fh.write("# Generated by: python jobs/ingest/discover_wap_archiveorg.py\n")
        fh.write("# Source: Internet Archive usda-foreignagricultureservice collection\n")
        fh.write("# Coverage: pre-2002-08 (modern FAS manifest covers 2002-08 onward)\n\n")
        fh.write("releases:\n\n")
        for e in entries:
            fh.write(f'  - release_month: "{e["release_month"]}"\n')
            fh.write(f'    url:           "{e["url"]}"\n')
            fh.write(f'    identifier:    "{e["identifier"]}"\n')
            fh.write(f'    title:         "{e["title"]}"\n')
            fh.write("\n")
    print(f"\nManifest saved: {len(entries)} entries → {_MANIFEST_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover pre-2002 USDA WAP PDFs on Archive.org and build a manifest."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Run discovery but do not write the manifest file.")
    parser.add_argument("--sleep-seconds", type=float, default=1.0,
                        help="Polite delay between HTTP requests (default: 1.0).")
    args = parser.parse_args()

    entries = discover(sleep_seconds=args.sleep_seconds)

    if args.dry_run:
        print("\n[dry-run] Manifest not written.")
        for e in entries:
            print(f"  {e['release_month']}  {e['url']}")
        return

    _save_manifest(entries)


if __name__ == "__main__":
    main()
