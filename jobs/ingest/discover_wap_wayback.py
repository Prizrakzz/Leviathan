"""Discover pre-2002 USDA FAS World Agricultural Production HTML pages archived
in the Wayback Machine and write a download manifest.

The original FAS WAP circular was published as HTML on fas.usda.gov from
approximately 1996 to 2001.  These HTML pages typically contain embedded
production tables that are directly parseable via BeautifulSoup (more
ML-accessible than scanned PDFs).

This script queries the Wayback Machine CDX API to find all archived snapshots
of WAP pages, selects one canonical snapshot per release_month, and writes
``configs/sources/usda_wap_wayback_manifest.yaml``.

Also probes the 2002-01 → 2002-07 gap in the modern FAS manifest (those months
may be on Wayback Machine as PDFs or HTML before the CDN migrated).

Run
---
    python jobs/ingest/discover_wap_wayback.py [--dry-run] [--sleep-seconds 0.5]

Output
------
    configs/sources/usda_wap_wayback_manifest.yaml

    Schema (per entry):
        release_month: "YYYY-MM"
        wayback_url:   "https://web.archive.org/web/{timestamp}/{original}"
        original_url:  "<original fas.usda.gov URL>"
        timestamp:     "<14-digit Wayback timestamp>"
        format:        "html"   # or "pdf" for 2002 gap entries
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

_CDX_URL = (
    "https://web.archive.org/cdx/search/cdx"
    "?url={pattern}"
    "&output=json"
    "&fl=timestamp,original,statuscode,mimetype"
    "&filter=statuscode:200"
    "&collapse=original"
    "&limit=2000"
)

# URL patterns to probe — FAS used inconsistent casing and subdirectory names
_PROBE_PATTERNS = [
    "fas.usda.gov/WAP/circular/*",
    "fas.usda.gov/wap/circular*",
    "www.fas.usda.gov/WAP/circular/*",
    "www.fas.usda.gov/wap/circular*",
    # Year-scoped probes to work around the 2000-row CDX limit.
    # Without these the 2000-row cap is exhausted by 1999 due to ~55 files per issue.
    "fas.usda.gov/WAP/circular/2000/*",
    "fas.usda.gov/WAP/circular/2001/*",
    "fas.usda.gov/WAP/circular/2002/*",
    "www.fas.usda.gov/WAP/circular/2000/*",
    "www.fas.usda.gov/WAP/circular/2001/*",
    "www.fas.usda.gov/WAP/circular/2002/*",
    # 2002 gap: the psdonline/circulars path was used before the modern portal
    "fas.usda.gov/psdonline/circulars/production.pdf",
    "www.fas.usda.gov/psdonline/circulars/production.pdf",
]

_WAYBACK_BASE = "https://web.archive.org/web"

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_wap_wayback_manifest.yaml"
)

_REQUEST_TIMEOUT_S = 30
_HEADERS = {"User-Agent": "Leviathan-WAP-Discover/1.0 (research; non-commercial)"}

# ---------------------------------------------------------------------------
# Month-name → number map (for URL parsing like "99-03" or "oct96")
# ---------------------------------------------------------------------------

_MONTH_ABBR: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}

# ---------------------------------------------------------------------------
# release_month extraction from WAP URLs
# ---------------------------------------------------------------------------

# Pattern: /1999/99-03/ or /1998/98-10/
_URL_YY_MM_RE = re.compile(r"/(\d{4})/(\d{2})-(\d{2})/")

# Pattern: oct96wap, jan97wap etc
_URL_MON_YY_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(\d{2})wap",
    re.IGNORECASE,
)

# Pattern: /circular/1996/96-10/ — redundant with above but explicit
_URL_YEAR_RE = re.compile(r"/circular[^/]*/(\d{4})/(\d{2})-(\d{2})/")


def _release_month_from_url(url: str) -> str | None:
    """Extract YYYY-MM release_month from a WAP HTML URL, or return None."""
    # Try YY-MM folder pattern first: /1999/99-03/
    m = _URL_YY_MM_RE.search(url)
    if m:
        year_full, yy, mm = m.group(1), m.group(2), m.group(3)
        return f"{year_full}-{mm}"

    # Try month-abbrev+YY filename: oct96wap1.html
    m = _URL_MON_YY_RE.search(url)
    if m:
        mon_abbr, yy = m.group(1).lower(), m.group(2)
        mon_num = _MONTH_ABBR.get(mon_abbr)
        if mon_num:
            # Expand 2-digit year: 96→1996, 03→2003
            year_full = int(yy)
            year_full = 1900 + year_full if year_full >= 90 else 2000 + year_full
            return f"{year_full}-{mon_num:02d}"

    return None


def _release_month_from_timestamp(timestamp: str, original: str) -> str | None:
    """For the psdonline/circulars/production.pdf path (single overwritten file),
    infer release_month from the Wayback capture timestamp YYYYMM."""
    # timestamp is 14 digits: YYYYMMDDHHMMSS
    if len(timestamp) >= 6:
        return f"{timestamp[:4]}-{timestamp[4:6]}"
    return None


# ---------------------------------------------------------------------------
# CDX query
# ---------------------------------------------------------------------------


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT_S)
    r.raise_for_status()
    return r


def _cdx_query(pattern: str, sleep_seconds: float) -> list[dict]:
    """Run one CDX query and return parsed rows as dicts."""
    url = _CDX_URL.format(pattern=requests.utils.quote(pattern, safe="/:*?=&"))
    print(f"CDX query: {pattern} ...")
    try:
        data = _get(url).json()
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return []
    finally:
        time.sleep(sleep_seconds)

    if not data or len(data) < 2:
        print("  No results")
        return []

    header = data[0]
    rows = [dict(zip(header, row)) for row in data[1:]]
    print(f"  {len(rows)} snapshots")
    return rows


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover(sleep_seconds: float) -> list[dict]:
    """
    Query Wayback CDX for all WAP-related URLs, extract release_month from
    each, select one canonical snapshot per month, and return manifest entries.
    """
    all_rows: list[dict] = []
    for pattern in _PROBE_PATTERNS:
        rows = _cdx_query(pattern, sleep_seconds)
        all_rows.extend(rows)

    print(f"\nTotal CDX rows: {len(all_rows)}")

    # ------------------------------------------------------------------
    # Map rows → (release_month, row) — deduplicate by month
    # ------------------------------------------------------------------
    month_candidates: dict[str, list[dict]] = {}

    for row in all_rows:
        original: str = row.get("original", "")
        timestamp: str = row.get("timestamp", "")
        mimetype: str = row.get("mimetype", "")

        # Determine release_month
        if "psdonline/circulars/production.pdf" in original.lower():
            release_month = _release_month_from_timestamp(timestamp, original)
            fmt = "pdf"
        else:
            release_month = _release_month_from_url(original)
            fmt = "html"

        if not release_month:
            continue

        # Skip anything already covered by the modern FAS manifest (>= 2002-08)
        year, month = int(release_month[:4]), int(release_month[5:7])
        if (year, month) >= (2002, 8):
            continue

        row["_release_month"] = release_month
        row["_format"] = fmt
        month_candidates.setdefault(release_month, []).append(row)

    # ------------------------------------------------------------------
    # For each month, pick the canonical snapshot:
    # - prefer .html/.htm over PDF (more structured)
    # - prefer the snapshot closest to the 10th of the release month
    #   (publication day is typically mid-month)
    # ------------------------------------------------------------------
    confirmed: list[dict] = []

    for release_month in sorted(month_candidates.keys()):
        candidates = month_candidates[release_month]
        year_s, month_s = release_month[:4], release_month[5:7]
        # Ideal capture timestamp: YYYYMM10 (10th of month)
        ideal_ts = f"{year_s}{month_s}10000000"

        def _score_url(url: str) -> int:
            """Lower score = better. Prefer HTML, penalise binary/attachment files."""
            lower = url.lower()
            if lower.endswith(".html") or lower.endswith(".htm"):
                return 0
            if lower.endswith(".wk3") or lower.endswith(".wk4") or lower.endswith(".xls"):
                return 10  # spreadsheet attachments — worst
            if lower.endswith(".gif") or lower.endswith(".jpg") or lower.endswith(".png"):
                return 9   # image files — very bad
            if lower.endswith(".pdf"):
                return 5   # PDF attachment — acceptable but not preferred
            return 3       # other (text, unknown)

        # Sort: HTML first by URL score, then by proximity to ideal_ts
        def _sort_key(r: dict) -> tuple[int, int, int]:
            fmt_pref = 0 if r["_format"] == "html" else 1
            url_pref = _score_url(r.get("original", ""))
            ts_diff = abs(int(r.get("timestamp", "0")[:8]) - int(ideal_ts[:8]))
            return (fmt_pref, url_pref, ts_diff)

        candidates.sort(key=_sort_key)
        best = candidates[0]

        wayback_url = f"{_WAYBACK_BASE}/{best['timestamp']}/{best['original']}"
        entry = {
            "release_month": release_month,
            "wayback_url": wayback_url,
            "original_url": best["original"],
            "timestamp": best["timestamp"],
            "format": best["_format"],
        }
        confirmed.append(entry)
        print(f"  {release_month}  {best['_format']}  {wayback_url}")

    print(f"\nDiscovery complete: {len(confirmed)} unique months")
    return confirmed


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def _save_manifest(entries: list[dict]) -> None:
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        fh.write("# USDA FAS World Agricultural Production — Wayback Machine snapshots\n")
        fh.write("# Generated by: python jobs/ingest/discover_wap_wayback.py\n")
        fh.write("# Coverage: ~1996-10 to 2002-07 (HTML format, embedded tables)\n")
        fh.write("# Note: format=html → source=usda_wap_html; format=pdf → source=usda_wap\n\n")
        fh.write("releases:\n\n")
        for e in entries:
            fh.write(f'  - release_month: "{e["release_month"]}"\n')
            fh.write(f'    wayback_url:   "{e["wayback_url"]}"\n')
            fh.write(f'    original_url:  "{e["original_url"]}"\n')
            fh.write(f'    timestamp:     "{e["timestamp"]}"\n')
            fh.write(f'    format:        "{e["format"]}"\n')
            fh.write("\n")
    print(f"\nManifest saved: {len(entries)} entries -> {_MANIFEST_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Discover pre-2002 USDA WAP pages on the Wayback Machine "
            "and build a manifest."
        )
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Run discovery but do not write the manifest file.")
    parser.add_argument("--sleep-seconds", type=float, default=0.5,
                        help="Polite delay between CDX API calls (default: 0.5).")
    args = parser.parse_args()

    entries = discover(sleep_seconds=args.sleep_seconds)

    if args.dry_run:
        print("\n[dry-run] Manifest not written.")
        return

    _save_manifest(entries)


if __name__ == "__main__":
    main()
