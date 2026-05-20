"""Discover MPOB BEPI article IDs for monthly releases and annual summaries.

Strategy
--------
Scans article IDs in a sequential range against the MPOB BEPI Joomla CMS.
For each candidate article ID:

  1. Requests the article using the raw Joomla query-parameter URL form
     (?option=com_content&view=article&id={artid}), which Joomla redirects to
     its SEF (Search Engine Friendly) URL.  The final URL after redirect
     reveals the category ID embedded in the path.

  2. Checks for the palm oil table validation marker ("CRUDE PALM OIL") to
     skip non-table articles (news items, FFB mill data, login-gated pages).

  3. Parses release_type, year, and month from the page HTML:
     - "Summary Of The Malaysian Palm Oil Industry {year}" → annual_summary
     - Month name + year in title                          → monthly_release

Output
------
``data/mpob/mpob_article_manifest.json`` — JSON array of records::

    {
        "art_id":      <int>,
        "cat_id":      <int | null>,
        "release_type":"annual_summary" | "monthly_release",
        "year":        <int>,
        "month":       <int | null>,   // null for annual_summary
        "url":         <str>           // canonical URL for use by fetch_mpob.py
    }

Known anchors
-------------
- Art 1260: 2026 annual summary  (cat=344)
- Art 1249: April 2026 monthly release (cat=341)
- Art 1200: FFB mill data 2025  → filtered out (no "CRUDE PALM OIL")

Usage
-----
    # Smoke-test against the two known anchors only:
    python scratch/mpob/probe_mpob_articles.py --start 1249 --end 1260

    # Full historical backfill (2017-2026, ~4 min):
    python scratch/mpob/probe_mpob_articles.py

    # Custom range, faster sleep:
    python scratch/mpob/probe_mpob_articles.py --start 900 --end 1270 --sleep 0.3
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE = "https://bepi.mpob.gov.my"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Validation marker — must be present for a page to be a palm oil table
_TABLE_MARKER = "CRUDE PALM OIL"

# Annual summary title pattern
_RE_ANNUAL = re.compile(
    r"Summary\s+Of\s+The\s+Malaysian\s+Palm\s+Oil\s+Industry\s+(\d{4})",
    re.IGNORECASE,
)

# Month name → number
_MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# SEF URL pattern:  /index.php/{section}/{catid}-{alias}/{artid}-{slug}
_RE_SEF = re.compile(r"/index\.php/[^/]+/(\d+)-[^/]+/(\d+)-", re.IGNORECASE)

# Canonical link in HTML head
_RE_CANONICAL = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

_ROOT = Path(__file__).parent.parent.parent
_OUTPUT_DEFAULT = _ROOT / "data" / "mpob" / "mpob_article_manifest.json"

# Default scan range — covers 2017–2026 with comfortable headroom
_DEFAULT_START = 900
_DEFAULT_END = 1270

_SSL_CTX = ssl.create_default_context()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, *, timeout: int = 20) -> tuple[str, str] | None:
    """Fetch *url* with redirect-following; return (final_url, html_text) or None.

    Returns None on HTTP ≥ 400 or network error.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            if resp.status >= 400:
                return None
            html = resp.read().decode("utf-8", errors="replace")
            return resp.url, html
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _extract_cat_id(url: str) -> int | None:
    """Parse catid from a SEF URL like /index.php/section/{catid}-alias/{artid}-slug."""
    m = _RE_SEF.search(url)
    return int(m.group(1)) if m else None


def _canonical_url(html: str) -> str | None:
    """Extract <link rel="canonical"> href from HTML."""
    m = _RE_CANONICAL.search(html)
    return m.group(1) if m else None


def _parse_title(html: str) -> str:
    """Return the <title> text, stripped."""
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _classify_article(
    html: str,
    artid: int,
    final_url: str,
) -> dict | None:
    """Classify an article as annual_summary or monthly_release.

    Returns a manifest record dict, or None if the page is not a palm oil table.
    """
    # Gate: must contain the table validation marker
    if _TABLE_MARKER not in html:
        return None

    title = _parse_title(html)

    # Try to get a canonical / SEF URL
    canonical = _canonical_url(html) or final_url
    cat_id = _extract_cat_id(canonical)

    # ---- Annual summary ----
    m_annual = _RE_ANNUAL.search(html)
    if m_annual:
        year = int(m_annual.group(1))
        return {
            "art_id": artid,
            "cat_id": cat_id,
            "release_type": "annual_summary",
            "year": year,
            "month": None,
            "url": canonical,
        }

    # ---- Monthly release ----
    # Look for a month name in the page title then locate the year
    title_lower = title.lower()
    for month_name, month_num in _MONTHS.items():
        if month_name in title_lower:
            year_m = re.search(r"(20\d{2})", title)
            if year_m:
                year = int(year_m.group(1))
                return {
                    "art_id": artid,
                    "cat_id": cat_id,
                    "release_type": "monthly_release",
                    "year": year,
                    "month": month_num,
                    "url": canonical,
                }
            break  # month found but no year — try URL slug as fallback

    # Fallback: try to extract month from the SEF URL slug
    # e.g. ".../1249-april-2026"  →  month=april, year=2026
    slug_m = re.search(r"/(\d+)-([a-z]+)-(\d{4})\b", canonical, re.IGNORECASE)
    if slug_m:
        slug_month = slug_m.group(2).lower()
        slug_year = int(slug_m.group(3))
        if slug_month in _MONTHS:
            return {
                "art_id": artid,
                "cat_id": cat_id,
                "release_type": "monthly_release",
                "year": slug_year,
                "month": _MONTHS[slug_month],
                "url": canonical,
            }

    # Has table marker but couldn't classify — log and skip
    print(f"  [?] art={artid}: has CRUDE PALM OIL but could not classify — title={title!r}")
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Probe MPOB BEPI article IDs for monthly releases and annual summaries. "
            "Writes discovered articles to data/mpob/mpob_article_manifest.json."
        )
    )
    parser.add_argument(
        "--start",
        type=int,
        default=_DEFAULT_START,
        metavar="N",
        help=f"First article ID to probe (default: {_DEFAULT_START}).",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=_DEFAULT_END,
        metavar="N",
        help=f"Last article ID to probe, inclusive (default: {_DEFAULT_END}).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        metavar="SEC",
        help="Polite delay between requests in seconds (default: 0.5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be probed without making any HTTP requests.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_OUTPUT_DEFAULT,
        metavar="PATH",
        help=f"Output JSON path (default: {_OUTPUT_DEFAULT}).",
    )
    args = parser.parse_args()

    total_ids = args.end - args.start + 1
    print(
        f"Probing article IDs {args.start}–{args.end} "
        f"({total_ids} IDs, sleep={args.sleep}s)"
    )

    if args.dry_run:
        print("Dry run — no HTTP requests made.")
        return

    results: list[dict] = []
    skipped = 0
    errors = 0

    for artid in range(args.start, args.end + 1):
        url = f"{_BASE}/index.php?option=com_content&view=article&id={artid}"
        result = _get(url)

        if result is None:
            print(f"  [skip] art={artid}: HTTP error or network failure")
            errors += 1
            time.sleep(args.sleep)
            continue

        final_url, html = result

        # Check if Joomla redirected to a login page (some articles are gated)
        if "com_users" in final_url or "task=user.login" in final_url:
            print(f"  [skip] art={artid}: login-gated")
            skipped += 1
            time.sleep(args.sleep)
            continue

        record = _classify_article(html, artid, final_url)

        if record is None:
            # Non-palm-oil article; don't spam output for the common case
            time.sleep(args.sleep)
            continue

        label = (
            f"annual_summary/{record['year']}"
            if record["release_type"] == "annual_summary"
            else f"monthly_release/{record['year']}/{record['month']:02d}"
        )
        print(f"  [found] art={artid} cat={record['cat_id']}: {label}")
        results.append(record)
        time.sleep(args.sleep)

    # Sort: annual summaries first (by year), then monthly releases (by year, month)
    results.sort(
        key=lambda r: (
            r["year"],
            0 if r["release_type"] == "annual_summary" else 1,
            r["month"] or 0,
        )
    )

    # Deduplicate by (release_type, year, month) — keep last seen (highest art_id wins)
    seen: dict[tuple, dict] = {}
    for r in results:
        key = (r["release_type"], r["year"], r["month"])
        seen[key] = r
    deduped = sorted(seen.values(), key=lambda r: (r["year"], r["release_type"], r["month"] or 0))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(deduped, indent=2), encoding="utf-8")

    print(
        f"\nDone. Found {len(deduped)} palm oil table articles "
        f"({errors} HTTP errors, {skipped} login-gated skipped)."
    )
    print(f"Manifest written to: {args.output}")

    # Summary breakdown
    annual_count = sum(1 for r in deduped if r["release_type"] == "annual_summary")
    monthly_count = sum(1 for r in deduped if r["release_type"] == "monthly_release")
    print(f"  annual_summary:   {annual_count}")
    print(f"  monthly_release:  {monthly_count}")


if __name__ == "__main__":
    main()
