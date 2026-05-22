"""Fetch World Bank Commodity Markets Outlook (CMO Outlook) PDFs to raw S3.

Publication history
-------------------
The CMO Outlook is the World Bank's flagship commodity research publication:

  1994–2007   Monthly / quarterly notes  (~8–20 pages each)
  2008–2013   Monthly issues + half-year summaries
  2014–2015   Semi-annual; archive links broken (Wayback fallback)
  2015–2017   Semi-annual; marked "*" on archive page — Wayback fallback
  2018–present  Semi-annual (April + October); direct openknowledge download

Target corpus: ~85 PDFs covering every major commodity price shock from the
1994 Brazil coffee frost through the 2022 Ukraine fertilizer shock.

S3 key structure
----------------
    raw/production/source=wb_cmo_outlook/
        release={YYYY-MM}/CMO-Outlook-{YYYY}-{label}.pdf

where ``label`` is the issue label: full month name for monthly/quarterly
issues (e.g. ``January``), or ``April`` / ``October`` for semi-annual issues.

Release partition normalisation (all eras → YYYY-MM):
    Semi-annual:  H1 → YYYY-04,  H2 → YYYY-10
    Quarterly:    Q1 → YYYY-01,  Q2 → YYYY-04,  Q3 → YYYY-07,  Q4 → YYYY-10
    Monthly:      actual month

Link resolution (three tiers)
-------------------------------
Tier A  openknowledge.worldbank.org/bitstreams/{id}/download
        Direct download — used by 2018-present semi-annual reports.

Tier B  openknowledge.worldbank.org/handle/10986/{id}
        Landing page — follow it, find the PDF bitstream href, store that.
        Used by most 2008-2013 monthly/quarterly reports.

Tier C  No href on archive page (2015–2017 ``*`` entries) or dead link.
        Attempt Wayback Machine CDX API lookup by publication date + title.

Modes
-----
--discover
    Scrape the archive page, resolve all three link tiers, attempt Wayback
    CDX for Tier C entries, write configs/sources/wb_cmo_outlook_manifest.yaml.
    No AWS credentials required.

Normal / --backfill (no --discover)
    Load manifest, apply year filters, upload missing files to raw S3.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip files already in S3.
Pass ``--dry-run`` to print S3 keys without downloading anything.
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_cmo_outlook_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ARCHIVE_URL = (
    "https://www.worldbank.org/en/research/commodity-markets/report-archive"
)
_OPENKNOWLEDGE_BASE = "https://openknowledge.worldbank.org"
_WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "wb_cmo_outlook_manifest.yaml"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60

_OPENKNOWLEDGE_BASE = "https://openknowledge.worldbank.org"
_DSPACE_BITSTREAM_RE = re.compile(
    r"^https?://openknowledge\.worldbank\.org/bitstreams/([0-9a-f-]{36})/download$",
    re.IGNORECASE,
)


def _normalize_openknowledge_url(url: str) -> str:
    """Rewrite Angular frontend download URLs to the DSpace 7 REST API content endpoint.

    The Angular frontend URLs (``/bitstreams/{uuid}/download``) return HTML
    because they rely on JavaScript to trigger the actual file download.
    The REST API endpoint (``/server/api/core/bitstreams/{uuid}/content``)
    returns the raw binary directly.
    """
    m = _DSPACE_BITSTREAM_RE.match(url)
    if m:
        return f"{_OPENKNOWLEDGE_BASE}/server/api/core/bitstreams/{m.group(1)}/content"
    return url


# ---------------------------------------------------------------------------
# Month helpers
# ---------------------------------------------------------------------------

_MONTH_NAME_TO_NUM: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    # abbreviations that appear in the archive table
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_NUM_TO_MONTH_NAME: dict[int, str] = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

# Quarterly label → representative month number
_QUARTER_TO_MONTH: dict[str, int] = {
    "q1": 1, "q2": 4, "q3": 7, "q4": 10,
    "h1": 4, "h2": 10,
}


def _label_to_release_ym(year: int, label: str) -> tuple[str, str]:
    """Map a (year, label) pair to (release_ym, display_label).

    ``label`` is the raw cell text from the archive table:
    full month name, three-letter abbreviation, or quarterly code.

    Returns:
        release_ym:     YYYY-MM string used as S3 partition.
        display_label:  Human-readable month/quarter label used in filename.
    """
    key = label.lower().strip()

    # Quarterly / half-year codes
    if key in _QUARTER_TO_MONTH:
        month = _QUARTER_TO_MONTH[key]
        return f"{year}-{month:02d}", label.upper()

    # Month names and abbreviations
    if key in _MONTH_NAME_TO_NUM:
        month = _MONTH_NAME_TO_NUM[key]
        return f"{year}-{month:02d}", _NUM_TO_MONTH_NAME[month]

    raise ValueError(f"Cannot parse date label {label!r} for year {year}")


# ---------------------------------------------------------------------------
# Archive page parsing
# ---------------------------------------------------------------------------

# Matches the year cell in the archive table: "2022 - April", "2011", etc.
_YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-9]{2})\b")


def _classify_href_tier(href: str | None) -> str:
    """Return Tier A / B / C for a given PDF href."""
    if href is None:
        return "C"
    if (
        # Plural /bitstreams/{uuid}/download  (newer releases)
        ("bitstreams" in href and "/download" in href)
        # Singular /bitstream/handle/{id}/{filename}.pdf  (2014–2022 releases)
        # This IS a direct PDF download, not a landing page.
        or re.search(r"/bitstream/handle/\d+/[^/]+\.pdf", href, re.IGNORECASE)
        # thedocs.worldbank.org direct PDF links
        or ("thedocs.worldbank.org" in href and href.endswith(".pdf"))
    ):
        return "A"
    if "openknowledge" in href:
        return "B"
    return "C"


def _parse_archive_table(html: str) -> tuple[list[dict[str, Any]], set[str]]:
    """Parse the CMO Outlook archive page and return (entries, extra_bitstream_urls).

    Each entry dict has:
        year:          int
        label:         str  — raw cell text ("April", "Jan", "Q1", "H2", …)
        href:          str | None  — raw href from the PDF link, or None
        tier:          "A" | "B" | "C"
        special_focus: str  — text of the special focus column (may be empty)

    Tier A: direct PDF download (bitstreams/download or bitstream/handle/id/file.pdf)
    Tier B: openknowledge landing page (/handle/id or /entities/id — no filename)
    Tier C: no href at all
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict[str, Any]] = []

    # The main table has columns: Issue | Reports | Supporting data | Special focus
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        # Skip header row
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            issue_cell = cells[0].get_text(separator=" ", strip=True)
            report_cell = cells[1]
            special_focus_text = cells[3].get_text(strip=True) if len(cells) > 3 else ""

            # Extract year from issue cell
            year_m = _YEAR_RE.search(issue_cell)
            if not year_m:
                continue
            year = int(year_m.group(1))

            # Determine the issue label (month, quarter, or half-year)
            # Issue cell looks like: "2022 - April" or just "2022"
            label_raw = issue_cell.replace(str(year), "").strip(" -–—").strip()
            if not label_raw:
                # Single-year row — might be a grouped row; skip (handled below)
                continue

            # Find the PDF link in the report cell
            pdf_link: str | None = None
            for a in report_cell.find_all("a", href=True):
                href = a["href"]
                link_text = a.get_text(strip=True).lower()
                # Only take the "PDF" link, not "Zip" or "Excel"
                if link_text in ("pdf", "*"):
                    pdf_link = href
                    break
                # Some rows have a direct link with no "PDF" label
                if "openknowledge" in href or "bitstream" in href:
                    pdf_link = href
                    break

            tier = _classify_href_tier(pdf_link)
            entries.append({
                "year": year,
                "label": label_raw,
                "href": pdf_link,
                "tier": tier,
                "special_focus": special_focus_text,
            })

    # Handle the "Earlier Issues" section — individual month/quarter links
    # inside <td> cells within a years-grouped table.
    # e.g. "2011 | Feb, Mar, Apr, ... H1, H2"
    for table in tables[1:]:   # skip the main table already processed
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            year_cell = cells[0].get_text(strip=True)
            year_m = _YEAR_RE.match(year_cell)
            if not year_m:
                continue
            year = int(year_m.group(1))
            links_cell = cells[1]
            for a in links_cell.find_all("a", href=True):
                label_raw = a.get_text(strip=True)
                href = a["href"]
                if not label_raw:
                    continue
                tier = _classify_href_tier(href)
                entries.append({
                    "year": year,
                    "label": label_raw,
                    "href": href,
                    "tier": tier,
                    "special_focus": "",
                })

    logger.info("Parsed %d raw entries from archive page", len(entries))

    # Secondary pass: collect ALL bitstream hrefs anywhere on the page.
    # The archive table may omit JS-rendered links; a full-page scan catches them.
    extra_bitstream_urls: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "bitstreams" in href and "/download" in href:
            full = href if href.startswith("http") else f"{_OPENKNOWLEDGE_BASE}{href}"
            extra_bitstream_urls.add(full)
        elif re.search(r"/bitstream/handle/\d+/[^/]+\.pdf", href, re.IGNORECASE):
            full = href if href.startswith("http") else f"{_OPENKNOWLEDGE_BASE}{href}"
            extra_bitstream_urls.add(full)
    if extra_bitstream_urls:
        logger.info(
            "Secondary scan: %d bitstream hrefs found anywhere on page",
            len(extra_bitstream_urls),
        )

    return entries, extra_bitstream_urls


# ---------------------------------------------------------------------------
# Tier B: follow openknowledge landing page to extract bitstream URL
# ---------------------------------------------------------------------------

_BITSTREAM_RE = re.compile(
    r"openknowledge\.worldbank\.org/bitstreams/[^\"'\s]+/download",
    re.IGNORECASE,
)


def _resolve_tier_b(href: str, session: requests.Session) -> str | None:
    """Follow an openknowledge landing page and return the bitstream download URL.

    Returns None if no PDF bitstream can be found.
    """
    url = href if href.startswith("http") else f"{_OPENKNOWLEDGE_BASE}{href}"
    try:
        resp = session.get(url, timeout=_REQUEST_TIMEOUT_S)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tier B fetch failed for %s: %s", url, exc)
        return None

    # Look for a bitstream download link in the rendered HTML
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        candidate = a["href"]
        if "bitstreams" in candidate and "/download" in candidate:
            if not candidate.startswith("http"):
                candidate = f"{_OPENKNOWLEDGE_BASE}{candidate}"
            return candidate

    # Fallback: regex scan of raw HTML
    m = _BITSTREAM_RE.search(resp.text)
    if m:
        return "https://" + m.group(0)

    logger.warning("Tier B: no bitstream found at %s", url)
    return None


# ---------------------------------------------------------------------------
# Tier C: Wayback Machine CDX fallback
# ---------------------------------------------------------------------------

def _wayback_lookup(year: int, month: int, session: requests.Session) -> str | None:
    """Query Wayback CDX for a CMO Outlook PDF near (year, month).

    Searches for openknowledge.worldbank.org pages containing
    "commodity-markets-outlook" from a ±3-month window around the expected
    publication date.

    Returns a Wayback replay URL, or None if nothing found.
    """
    # Build date window: from 2 months before to 2 months after publication
    from_date = f"{year}{max(1, month - 2):02d}01"
    to_date = f"{year}{min(12, month + 2):02d}28"

    params = {
        "url": "openknowledge.worldbank.org/*commodity*outlook*",
        "output": "json",
        "filter": "statuscode:200",
        "fl": "timestamp,original",
        "limit": "10",
        "from": from_date,
        "to": to_date,
        "matchType": "prefix",
        "collapse": "original",
    }
    try:
        resp = session.get(_WAYBACK_CDX_URL, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Wayback CDX query failed for %d-%02d: %s", year, month, exc)
        return None

    # rows[0] is the header ["timestamp","original"]
    if len(rows) <= 1:
        logger.debug("Wayback CDX: no results for %d-%02d", year, month)
        return None

    # Take first matching result — it's an openknowledge landing page
    # Convert to a Wayback replay + /download URL
    ts, original = rows[1]
    landing_url = f"https://web.archive.org/web/{ts}/{original}"
    logger.info("Wayback CDX: %d-%02d → %s", year, month, landing_url)

    # Try to resolve the bitstream from the archived landing page
    resolved = _resolve_tier_b(landing_url, session)
    if resolved:
        return resolved

    # Return the landing page itself as a fallback — it may be an HTML snapshot
    return landing_url


# ---------------------------------------------------------------------------
# Discovery: build full entry list
# ---------------------------------------------------------------------------

def _discover_entries(
    session: requests.Session,
    sleep_seconds: float,
) -> list[dict[str, Any]]:
    """Scrape archive page and resolve all three link tiers.

    Returns a list of manifest-ready dicts (sorted ascending by release_date).
    """
    logger.info("Fetching archive page: %s", _ARCHIVE_URL)
    resp = session.get(_ARCHIVE_URL, timeout=_REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    raw_entries, _extra_bitstream_urls = _parse_archive_table(resp.text)

    manifest: list[dict[str, Any]] = []
    tier_counts = {"A": 0, "B": 0, "C": 0, "skip": 0}

    for raw in raw_entries:
        year = raw["year"]
        label = raw["label"]
        tier = raw["tier"]
        href = raw.get("href")

        try:
            release_ym, display_label = _label_to_release_ym(year, label)
        except ValueError as exc:
            logger.debug("Skipping unparseable label %r (%d): %s", label, year, exc)
            tier_counts["skip"] += 1
            continue

        filename = f"CMO-Outlook-{year}-{display_label}.pdf"
        s3_key = raw_cmo_outlook_key(release_ym, filename)

        url: str | None = None
        wayback_needed = False
        notes = ""

        if tier == "A":
            url = href if href.startswith("http") else f"{_OPENKNOWLEDGE_BASE}{href}"
            tier_counts["A"] += 1

        elif tier == "B":
            logger.info("Tier B: resolving landing page for %d-%s …", year, label)
            url = _resolve_tier_b(href, session)
            tier_counts["B"] += 1
            if url is None:
                wayback_needed = True
                notes = f"Tier B resolution failed for {href}"
            time.sleep(sleep_seconds)

        else:  # Tier C
            tier_counts["C"] += 1
            month_num = int(release_ym[5:7])
            logger.info(
                "Tier C: Wayback CDX lookup for %d-%02d …", year, month_num
            )
            url = _wayback_lookup(year, month_num, session)
            if url is None:
                wayback_needed = True
                notes = "No Wayback snapshot found; manual intervention needed"
            time.sleep(sleep_seconds)

        manifest.append({
            "release_date": release_ym,
            "release_type": _classify_release_type(year),
            "label": display_label,
            "url": url or "",
            "filename": filename,
            "s3_key": s3_key,
            "special_focus": raw.get("special_focus", ""),
            "wayback_needed": wayback_needed,
            "notes": notes,
        })

    manifest.sort(key=lambda x: x["release_date"])

    # Deduplicate by s3_key (same issue may appear in multiple table sections)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for entry in manifest:
        if entry["s3_key"] not in seen:
            seen.add(entry["s3_key"])
            deduped.append(entry)

    logger.info(
        "Discovery complete: %d entries  (Tier A=%d  Tier B=%d  Tier C=%d  skipped=%d)",
        len(deduped),
        tier_counts["A"],
        tier_counts["B"],
        tier_counts["C"],
        tier_counts["skip"],
    )
    wayback_needed_count = sum(1 for e in deduped if e["wayback_needed"])
    if wayback_needed_count:
        logger.warning(
            "%d entries have wayback_needed=true — URLs not resolved; "
            "edit manifest manually or rerun --discover after adding known URLs.",
            wayback_needed_count,
        )
    return deduped


def _classify_release_type(year: int) -> str:
    if year >= 2018:
        return "semi-annual"
    if year >= 2014:
        return "semi-annual"
    if year >= 2008:
        return "monthly-quarterly"
    return "monthly-quarterly"


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------

def _load_manifest() -> list[dict[str, Any]]:
    if not _MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Manifest not found: {_MANIFEST_PATH}. "
            "Run with --discover first to build it."
        )
    data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    reports: list[dict[str, Any]] = data.get("reports") or []
    logger.info(
        "Manifest: loaded %d entries from %s", len(reports), _MANIFEST_PATH.name
    )
    return reports


def _save_manifest(reports: list[dict[str, Any]]) -> None:
    header = (
        "# World Bank CMO Outlook — manifest\n"
        "# Generated by: python jobs/ingest/fetch_wb_cmo_outlook.py --discover\n"
        "# Hand-editable: set url for wayback_needed entries, adjust notes.\n"
        "# Fields: release_date (YYYY-MM), release_type, label, url,\n"
        "#         filename, s3_key, special_focus, wayback_needed, notes\n"
    )
    with _MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        fh.write(header + "\n")
        fh.write("reports:\n\n")
        for r in reports:
            fh.write(f"  - release_date: \"{r['release_date']}\"\n")
            fh.write(f"    release_type: {r['release_type']}\n")
            fh.write(f"    label: \"{r['label']}\"\n")
            url_val = r.get("url") or ""
            fh.write(f"    url: \"{url_val}\"\n")
            fh.write(f"    filename: \"{r['filename']}\"\n")
            fh.write(f"    s3_key: \"{r['s3_key']}\"\n")
            sf = (r.get("special_focus") or "").replace('"', "'")
            fh.write(f"    special_focus: \"{sf}\"\n")
            fh.write(f"    wayback_needed: {str(r.get('wayback_needed', False)).lower()}\n")
            notes = (r.get("notes") or "").replace('"', "'")
            fh.write(f"    notes: \"{notes}\"\n")
            fh.write("\n")
    logger.info(
        "Manifest saved: %d entries → %s", len(reports), _MANIFEST_PATH
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_pdf(data: bytes, url: str) -> None:
    """Raise RuntimeError if *data* does not start with PDF magic bytes."""
    if data[:4] != _PDF_MAGIC:
        raise RuntimeError(
            f"Response from {url} is not a valid PDF "
            f"(expected %PDF, got {data[:4]!r}). "
            "Possible HTML error page or redirect."
        )


# ---------------------------------------------------------------------------
# Per-entry upload
# ---------------------------------------------------------------------------

def _upload_entry(
    entry: dict[str, Any],
    bucket: str,
    region: str,
    session: requests.Session,
    skip_existing: bool,
    sleep_seconds: float,
) -> str:
    """Download one CMO Outlook PDF and upload to raw S3.

    Returns ``"uploaded"``, ``"skipped"``, or ``"error"``.
    """
    release_date = entry["release_date"]
    url = entry.get("url", "")
    s3_key = entry["s3_key"]
    filename = entry["filename"]

    if not url:
        logger.warning(
            "Skipping %s — no URL (wayback_needed=%s). "
            "Edit manifest to add a URL, then rerun.",
            filename,
            entry.get("wayback_needed"),
        )
        return "skipped"

    try:
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("Skipping — already in S3: %s", s3_key)
            time.sleep(sleep_seconds)
            return "skipped"

        url = _normalize_openknowledge_url(url)
        logger.info("Downloading %s  %s …", release_date, url)
        resp = session.get(url, timeout=_REQUEST_TIMEOUT_S, allow_redirects=True)
        resp.raise_for_status()
        data = resp.content

        _validate_pdf(data, url)
        check_min_file_size(data, "wb_cmo_outlook", context=url)

        upload_bytes_to_s3(data, bucket, s3_key, region)
        write_raw_s3_metadata(
            bucket, s3_key, data, url, "application/pdf", region
        )

        logger.info(
            "Uploaded %s  (%.1f KB)  →  s3://%s/%s",
            release_date,
            len(data) / 1024,
            bucket,
            s3_key,
        )
        time.sleep(sleep_seconds)
        return "uploaded"

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed %s (%s): %s", filename, url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download World Bank CMO Outlook PDFs (1994–present) to raw S3. "
            "~85 reports covering every major commodity price shock from the "
            "1994 Brazil coffee frost through the 2022 Ukraine fertilizer shock."
        )
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Scrape the WB archive page, resolve all PDF links (three-tier: "
            "direct bitstream, openknowledge landing page, Wayback CDX fallback), "
            "and write configs/sources/wb_cmo_outlook_manifest.yaml. "
            "No AWS credentials required."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip files whose S3 key already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S3 keys and URLs without downloading anything.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.5,
        help="Polite delay between HTTP requests in seconds (default: 1.5).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N files — use 1–5 for smoke tests.",
    )
    parser.add_argument(
        "--year-from",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only entries with release year >= YYYY.",
    )
    parser.add_argument(
        "--year-to",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only entries with release year <= YYYY.",
    )
    args = parser.parse_args()

    load_env()

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    # ------------------------------------------------------------------
    # Discovery mode
    # ------------------------------------------------------------------
    if args.discover:
        entries = _discover_entries(session, args.sleep_seconds)
        _save_manifest(entries)
        wayback_count = sum(1 for e in entries if e.get("wayback_needed"))
        print(
            f"\nDiscovery complete: {len(entries)} entries written to "
            f"{_MANIFEST_PATH.name}\n"
            f"  wayback_needed: {wayback_count} entries have no resolved URL\n"
            f"  Edit the manifest to fill in missing URLs, then run without --discover."
        )
        return

    # ------------------------------------------------------------------
    # Download mode
    # ------------------------------------------------------------------
    bucket = get_required_env("LEVIATHAN_RAW_BUCKET")
    region = get_required_env("AWS_DEFAULT_REGION")

    reports = _load_manifest()

    # Apply year filters
    if args.year_from or args.year_to:
        before = len(reports)
        reports = [
            r for r in reports
            if (args.year_from is None or int(r["release_date"][:4]) >= args.year_from)
            and (args.year_to is None or int(r["release_date"][:4]) <= args.year_to)
        ]
        logger.info(
            "Year filter: %d → %d entries (year_from=%s year_to=%s)",
            before,
            len(reports),
            args.year_from,
            args.year_to,
        )

    if args.limit:
        reports = reports[: args.limit]
        logger.info("Limit: processing %d entries", len(reports))

    # --dry-run: print planned uploads
    if args.dry_run:
        print(f"\nDry run — {len(reports)} entries:\n")
        for r in reports:
            url_display = r.get("url") or "(no URL — wayback_needed)"
            print(f"  {r['release_date']}  {r['filename']}")
            print(f"    s3_key : {r['s3_key']}")
            print(f"    url    : {url_display}")
            if r.get("wayback_needed"):
                print(f"    *** wayback_needed — will be SKIPPED ***")
            print()
        return

    # Live upload
    counts = {"uploaded": 0, "skipped": 0, "error": 0}
    for report in reports:
        result = _upload_entry(
            report,
            bucket,
            region,
            session,
            args.skip_existing_s3,
            args.sleep_seconds,
        )
        counts[result] += 1

    total = sum(counts.values())
    logger.info(
        "Done: %d total  |  uploaded=%d  skipped=%d  errors=%d",
        total,
        counts["uploaded"],
        counts["skipped"],
        counts["error"],
    )
    if counts["error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
