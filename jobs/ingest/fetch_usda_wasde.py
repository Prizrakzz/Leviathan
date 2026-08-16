"""Fetch USDA WASDE monthly reports to raw S3.

Three format eras, all discovered from esmis.nal.usda.gov:

  1973–1994  PDF only (scanned images)
  1995–1999  TXT only (TXT was the authoritative distribution format for this
             era — full report including all narrative pages, zero OCR cost)
  2000–present  PDF (digital typeset; pdfplumber-compatible in bronze layer)

The numerical supply/demand tables in WASDE are already fully covered by
``fetch_usda_psd.py`` (psd_alldata_csv.zip, ``Month`` column).  The unique
value stored here is the narrative text: "OUTLOOK FOR WHEAT",
"OUTLOOK FOR COARSE GRAINS", etc. (pages 1–7 of each report).

Discovery
---------
Files are discovered from the USDA ESMIS archive (70 paginated pages):
    https://esmis.nal.usda.gov/publication/world-agricultural-supply-and-demand-estimates

~840 releases total from Sep 1973 to present.

Manifest
--------
``--discover`` scrapes all 70 pages, applies format routing, deduplicates by
calendar month (keeping the latest release date per month — handles v2/v3
corrections and duplicate-dated TXT entries in the 1995 era), and writes
``configs/sources/usda_wasde_manifest.yaml``.

S3 key structure
----------------
    raw/production/source=usda_wasde/
        release_date={YYYY-MM-DD}/wasde{MMYY}.{fmt}

where MMYY is zero-padded month + two-digit year (e.g. ``0195`` = Jan 1995,
``0526`` = May 2026).

Modes
-----
--discover
    Scrape esmis 70 pages and rebuild manifest.  No AWS credentials required.

Normal (no --discover)
    Load manifest, apply filters, upload to raw S3.  ``--refresh-manifest``
    additionally merges the head of the archive (``--discover-pages`` pages,
    newest-first) into the loaded manifest IN MEMORY first, so a release the
    static YAML has never heard of is still reachable.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip files already in S3 -- keyed on the
``source_url`` recorded in the raw_meta sidecar, not key existence, so a v2/v3
correction that reuses a release_date still re-fetches.
Pass ``--dry-run`` to print S3 keys without downloading anything.
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_wasde_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import download_s3_json, s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ESMIS_BASE = "https://esmis.nal.usda.gov"
_ESMIS_PUB_URL = (
    f"{_ESMIS_BASE}/publication/world-agricultural-supply-and-demand-estimates"
)
_ESMIS_PAGE_COUNT = 70

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "usda_wasde_manifest.yaml"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60

# A download failure on a release inside this window turns the JOB red (exit 1). Older failures
# stay warnings: three manifest URLs are permanently 404 at the source (2001-05-10
# wheat-revision, 2002-05-10 broilers_revision, 2006-07-12 China_rice_revision -- they are why
# the 627-entry manifest yields 624 bronze releases), and re-reddening a daily lane on a
# 25-year-old dead link buys nothing. Inside the window, a silent exit-0 is the exact defect
# that hid the missing 2026-08-12 release for 37 days.
_RECENT_FAILURE_DAYS = 120

# Year range where TXT is the authoritative and only available format.
_TXT_ERA_START = 1995
_TXT_ERA_END = 1999

# Matches date + extension from esmis link text.
# Handles both "Nov 09 1995-txt" and "... -May 12 2026-pdf".
_LINK_DATE_RE = re.compile(
    r"(\w{3})\s+(\d{1,2})\s+(\d{4})[-](\w+)$", re.IGNORECASE
)

_MONTH_ABBR: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


# ---------------------------------------------------------------------------
# Format routing
# ---------------------------------------------------------------------------

def _pick_format(year: int) -> str:
    """Return the preferred download format for WASDE releases in *year*.

    1995–1999 → ``"txt"`` (TXT is the authoritative full-report format;
                            no PDF available for this era in the archive).
    All other years → ``"pdf"`` (scanned 1973–1994; digital typeset 2000+).
    """
    if _TXT_ERA_START <= year <= _TXT_ERA_END:
        return "txt"
    return "pdf"


# ---------------------------------------------------------------------------
# esmis scraping
# ---------------------------------------------------------------------------

def _scrape_esmis_page(
    session: requests.Session, page_num: int
) -> list[dict[str, Any]]:
    """GET one esmis archive page and return raw link entries.

    Each returned entry dict has keys:
        release_date, calendar_month, year (int), ext ("txt"|"pdf"), url (str)

    XLS/XML links and unparseable entries are silently dropped.
    """
    url = f"{_ESMIS_PUB_URL}?page={page_num}"
    resp = session.get(url, timeout=_REQUEST_TIMEOUT_S)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    entries: list[dict[str, Any]] = []

    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "release-files" not in href:
            continue
        ext = href.rsplit(".", 1)[-1].lower()
        if ext not in ("txt", "pdf"):
            continue
        # Skip readme files — they are supplementary docs, not WASDE reports.
        basename = href.rsplit("/", 1)[-1].lower()
        if basename.startswith("readme"):
            continue

        text = a.get_text(strip=True)
        m = _LINK_DATE_RE.search(text)
        if not m:
            continue
        mon_str, day_str, year_str, link_ext = m.groups()
        if link_ext.lower() != ext:
            # Extension in link text doesn't match href — skip to avoid mismatches.
            continue

        month = _MONTH_ABBR.get(mon_str.lower())
        if month is None:
            logger.warning("Unrecognised month %r in link text: %r", mon_str, text)
            continue

        year = int(year_str)
        day = int(day_str)
        release_date = f"{year}-{month:02d}-{day:02d}"
        calendar_month = f"{year}-{month:02d}"

        entries.append({
            "release_date": release_date,
            "calendar_month": calendar_month,
            "year": year,
            "ext": ext,
            "url": _ESMIS_BASE + href,
        })

    return entries


def _build_manifest_entries(
    session: requests.Session,
    sleep_seconds: float,
    pages: int = _ESMIS_PAGE_COUNT,
) -> list[dict[str, Any]]:
    """Scrape the first *pages* esmis archive pages and return deduplicated manifest entries.

    Format routing: 1995–1999 → TXT; all other years → PDF.
    Deduplication: per calendar_month, keep the entry with the latest
    release_date (handles v2/v3 correction releases and the duplicate-dated
    TXT entries in the 1995 era).

    The archive is ordered newest-first, so ``pages=1`` is the cheap monthly refresh (it carries
    the current release) while the default 70 rebuilds the whole manifest for --discover.
    """
    pages = max(1, min(int(pages), _ESMIS_PAGE_COUNT))
    all_entries: list[dict[str, Any]] = []

    for page_num in range(pages):
        try:
            page_entries = _scrape_esmis_page(session, page_num)
            all_entries.extend(page_entries)
            logger.info(
                "Page %d/%d: %d links (total so far: %d)",
                page_num + 1,
                pages,
                len(page_entries),
                len(all_entries),
            )
        except Exception as exc:  # noqa: BLE001 — per-page scrape error; loop continues to remaining pages
            logger.warning("Failed to scrape page %d: %s — continuing", page_num, exc)
        if page_num < pages - 1:
            time.sleep(sleep_seconds)

    # Keep only entries matching the preferred format for that year.
    routed: list[dict[str, Any]] = [
        e for e in all_entries if e["ext"] == _pick_format(e["year"])
    ]

    # Dedup by calendar_month: keep latest release_date.
    by_month: dict[str, dict[str, Any]] = {}
    for e in routed:
        key = e["calendar_month"]
        if key not in by_month or e["release_date"] > by_month[key]["release_date"]:
            by_month[key] = e

    # Build final entries sorted ascending by release_date.
    manifest: list[dict[str, Any]] = []
    for e in sorted(by_month.values(), key=lambda x: x["release_date"]):
        year = e["year"]
        month = int(e["release_date"][5:7])
        mmyy = f"{month:02d}{str(year)[-2:]}"
        fmt = e["ext"]
        manifest.append({
            "release_date": e["release_date"],
            "calendar_month": e["calendar_month"],
            "mmyy": mmyy,
            "fmt": fmt,
            "url": e["url"],
            "filename": f"wasde{mmyy}.{fmt}",
        })

    txt_count = sum(1 for e in manifest if e["fmt"] == "txt")
    pdf_count = sum(1 for e in manifest if e["fmt"] == "pdf")
    logger.info(
        "Discovery: %d raw links → %d routed → %d deduplicated  (txt=%d  pdf=%d)",
        len(all_entries),
        len(routed),
        len(manifest),
        txt_count,
        pdf_count,
    )
    return manifest


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------

def _merge_manifest(
    existing: list[dict[str, Any]],
    discovered: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge freshly scraped entries into the loaded manifest, keyed by calendar_month.

    A discovered entry is ADOPTED when its calendar_month is absent (a new release -- the
    2026-08-12 case) or when its release_date is strictly newer than the stored one (a v2/v3
    correction that moved the date). An identical month/date is left alone so the merge is a
    no-op on a quiet day. Returns ``(merged_sorted_by_release_date, changed_calendar_months)``.
    The repo YAML is NOT written unless --save-manifest: the scheduled container's filesystem is
    ephemeral, so the merge exists to make THIS run complete, not to mutate a tracked config.
    """
    by_month = {e["calendar_month"]: e for e in existing}
    changed: list[str] = []
    for e in discovered:
        cur = by_month.get(e["calendar_month"])
        if cur is None or e["release_date"] > cur["release_date"]:
            by_month[e["calendar_month"]] = e
            changed.append(e["calendar_month"])
    merged = sorted(by_month.values(), key=lambda x: x["release_date"])
    return merged, sorted(changed)


def _load_manifest() -> list[dict[str, Any]]:
    data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    reports: list[dict[str, Any]] = data.get("reports") or []
    logger.info("Manifest: loaded %d entries from %s", len(reports), _MANIFEST_PATH.name)
    return reports


def _save_manifest(reports: list[dict[str, Any]]) -> None:
    """Write the manifest YAML, preserving the header comment block."""
    header_lines: list[str] = []
    for line in _MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.strip() == "":
            header_lines.append(line)
        else:
            break

    with _MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(header_lines) + "\n\n")
        fh.write("reports:\n\n")
        for r in reports:
            fh.write(f"  - release_date: \"{r['release_date']}\"\n")
            fh.write(f"    calendar_month: \"{r['calendar_month']}\"\n")
            fh.write(f"    mmyy: \"{r['mmyy']}\"\n")
            fh.write(f"    fmt: {r['fmt']}\n")
            fh.write(f"    url: \"{r['url']}\"\n")
            fh.write(f"    filename: \"{r['filename']}\"\n")
            fh.write("\n")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_txt(data: bytes, url: str) -> None:
    """Check that *data* looks like a WASDE TXT report.

    Raises RuntimeError if validation fails.
    """
    if len(data) < 100:
        raise RuntimeError(
            f"TXT response too short ({len(data)} bytes) from {url}"
        )
    head = data[:16384].decode("latin-1")

    markers = ("WORLD AGRICULTURAL", "OUTLOOK FOR", "SUPPLY AND DEMAND", "WASDE")
    if not any(marker in head.upper() for marker in markers):
        raise RuntimeError(
            f"TXT response from {url} missing expected WASDE header markers. "
            f"First 300 chars: {head[:300]!r}"
        )


def _validate_pdf(data: bytes, url: str) -> None:
    """Check that *data* starts with the PDF magic bytes.

    Raises RuntimeError if validation fails.
    """
    if data[:4] != _PDF_MAGIC:
        raise RuntimeError(
            f"Response from {url} is not a valid PDF "
            f"(expected %PDF, got {data[:4]!r})"
        )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def _upload_entry(
    entry: dict[str, Any],
    bucket: str,
    region: str,
    session: requests.Session,
    skip_existing: bool,
    sleep_seconds: float,
) -> str:
    """Download one WASDE file and upload to raw S3.

    Returns ``"uploaded"``, ``"skipped"``, or ``"error"``.
    """
    release_date = entry["release_date"]
    mmyy = entry["mmyy"]
    fmt = entry["fmt"]
    url = entry["url"]
    s3_key = raw_wasde_key(release_date, mmyy, fmt)

    try:
        if skip_existing and s3_object_exists(bucket, s3_key, region):
            # A v2/v3 correction can REUSE the release_date under a different source URL
            # (wasde0526v2.pdf -> the same wasde0526.pdf key). Key-existence alone would pin the
            # superseded bytes forever, so the recorded source_url in the raw_meta sidecar is the
            # real idempotency token. A missing/unreadable sidecar re-downloads (fail-open toward
            # freshness, never toward staleness).
            try:
                meta = download_s3_json(
                    bucket, f"raw_meta/{s3_key}_meta.json", region)
                same_source = meta.get("source_url") == url
            except Exception:  # noqa: BLE001 — no sidecar / unreadable: fall through and refetch
                same_source = False
            if same_source:
                logger.info("Skipping — already in S3 from the same source URL: %s", s3_key)
                time.sleep(sleep_seconds)
                return "skipped"
            logger.info("Re-fetching %s — S3 object exists but its recorded source_url differs "
                        "(correction release)", s3_key)

        logger.info("Downloading %s  %s …", release_date, url)
        resp = session.get(url, timeout=_REQUEST_TIMEOUT_S, allow_redirects=True)
        resp.raise_for_status()
        data = resp.content

        if fmt == "txt":
            _validate_txt(data, url)
            content_type = "text/plain"
        else:
            _validate_pdf(data, url)
            content_type = "application/pdf"

        check_min_file_size(data, f"usda_wasde_{fmt}", context=url)

        upload_bytes_to_s3(data, bucket, s3_key, region)
        write_raw_s3_metadata(bucket, s3_key, data, url, content_type, region)

        logger.info(
            "Uploaded %s  (%.1f KB)  →  s3://%s/%s",
            release_date,
            len(data) / 1024,
            bucket,
            s3_key,
        )
        time.sleep(sleep_seconds)
        return "uploaded"

    except Exception as exc:  # noqa: BLE001 — any download, validation, or S3 error is logged; caller accumulates failures
        logger.error("Failed %s (%s): %s", release_date, url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download USDA WASDE monthly reports to raw S3. "
            "Covers Sep 1973–present: PDF for 1973–1994 (scanned) and "
            "2000–present (digital), TXT for 1995–1999 (authoritative era)."
        )
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Scrape esmis.nal.usda.gov archive (70 pages) to discover all "
            "WASDE release URLs and rebuild configs/sources/usda_wasde_manifest.yaml. "
            "No AWS credentials required."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip files whose S3 key already exists.",
    )
    parser.add_argument(
        "--refresh-manifest",
        action="store_true",
        help=(
            "Re-scrape the head of the esmis archive and MERGE new/corrected releases into the "
            "loaded manifest IN MEMORY, then continue into upload mode. Without this the fetcher "
            "can only ever land releases already listed in the static YAML -- which is why the "
            "2026-08-12 WASDE was never fetched (release URLs carry an opaque node id and cannot "
            "be constructed). Use with --discover-pages."
        ),
    )
    parser.add_argument(
        "--discover-pages",
        type=int,
        default=1,
        metavar="N",
        help=(
            "How many esmis archive pages --refresh-manifest scrapes (newest-first). Default 1 "
            "(~12 newest releases, one HTTP request). Only --discover rebuilds all 70."
        ),
    )
    parser.add_argument(
        "--save-manifest",
        action="store_true",
        help=(
            "Additionally write the merged manifest back to "
            "configs/sources/usda_wasde_manifest.yaml. Operator-only: the scheduled container "
            "writes to an ephemeral filesystem, so the scheduled form omits this."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S3 keys without downloading anything.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Polite delay between HTTP requests in seconds (default: 1.0).",
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
    parser.add_argument(
        "--fmt",
        choices=["txt", "pdf"],
        default=None,
        help="Process only entries of this format (default: both).",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    # ------------------------------------------------------------------
    # Discover mode
    # ------------------------------------------------------------------
    if args.discover:
        entries = _build_manifest_entries(session, sleep_seconds=args.sleep_seconds)
        _save_manifest(entries)
        logger.info(
            "Manifest saved: %d entries → %s", len(entries), _MANIFEST_PATH
        )
        session.close()
        return 0

    # ------------------------------------------------------------------
    # Upload mode
    # ------------------------------------------------------------------
    entries = _load_manifest()

    if args.refresh_manifest:
        discovered = _build_manifest_entries(
            session, sleep_seconds=args.sleep_seconds, pages=args.discover_pages)
        if not discovered:
            # The archive head always carries ~12 releases, so an empty scrape is a scrape
            # fault (esmis 5xx, WAF, DOM change), never a quiet month. Falling back to the
            # static manifest here is the 2026-08-12 silent-miss class this flag exists to end.
            logger.error(
                "MANIFEST REFRESH FAILED: --discover-pages %d scraped ZERO routed entries -- "
                "exiting 1 rather than proceeding on the static manifest.", args.discover_pages)
            session.close()
            return 1
        entries, changed = _merge_manifest(entries, discovered)
        logger.info(
            "Manifest refresh: scraped %d page(s) -> %d routed entries; merged manifest now %d "
            "entries; months adopted/corrected: %s",
            args.discover_pages, len(discovered), len(entries), changed or "none")
        if args.save_manifest:
            _save_manifest(entries)
            logger.info("Merged manifest written to %s", _MANIFEST_PATH)

    if args.year_from is not None:
        entries = [e for e in entries if int(e["release_date"][:4]) >= args.year_from]
    if args.year_to is not None:
        entries = [e for e in entries if int(e["release_date"][:4]) <= args.year_to]
    if args.fmt is not None:
        entries = [e for e in entries if e["fmt"] == args.fmt]

    if not entries:
        logger.warning("No entries to process after filtering.")
        session.close()
        return 0

    if args.limit:
        entries = entries[: args.limit]

    if args.dry_run:
        print(f"Would process {len(entries)} files:")
        for e in entries:
            s3_key = raw_wasde_key(e["release_date"], e["mmyy"], e["fmt"])
            print(
                f"  {e['release_date']}  {e['fmt'].upper():3}  "
                f"{e['filename']}  ->  {s3_key}"
            )
        session.close()
        return 0

    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0
    recent_cutoff = (
        datetime.now(timezone.utc).date() - timedelta(days=_RECENT_FAILURE_DAYS)).isoformat()
    failed_recent: list[str] = []
    for entry in entries:
        result = _upload_entry(
            entry,
            bucket,
            region,
            session,
            skip_existing=args.skip_existing_s3,
            sleep_seconds=args.sleep_seconds,
        )
        if result == "uploaded":
            uploaded += 1
        elif result == "skipped":
            skipped += 1
        else:
            errors += 1
            if entry["release_date"] >= recent_cutoff:
                failed_recent.append(entry["release_date"])

    session.close()
    logger.info("Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors)
    if failed_recent:
        logger.error(
            "FETCH FAILED for %d release(s) inside the %d-day recency window: %s. Exiting 1 so "
            "the schedule turns RED instead of succeeding with nothing landed.",
            len(failed_recent), _RECENT_FAILURE_DAYS, sorted(failed_recent))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
