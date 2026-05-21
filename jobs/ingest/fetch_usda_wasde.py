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
    Load manifest, apply filters, upload to raw S3.

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
from leviathan.storage.paths import raw_wasde_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

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
) -> list[dict[str, Any]]:
    """Scrape all 70 esmis pages and return deduplicated manifest entries.

    Format routing: 1995–1999 → TXT; all other years → PDF.
    Deduplication: per calendar_month, keep the entry with the latest
    release_date (handles v2/v3 correction releases and the duplicate-dated
    TXT entries in the 1995 era).
    """
    all_entries: list[dict[str, Any]] = []

    for page_num in range(_ESMIS_PAGE_COUNT):
        try:
            page_entries = _scrape_esmis_page(session, page_num)
            all_entries.extend(page_entries)
            logger.info(
                "Page %d/%d: %d links (total so far: %d)",
                page_num + 1,
                _ESMIS_PAGE_COUNT,
                len(page_entries),
                len(all_entries),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to scrape page %d: %s — continuing", page_num, exc)
        if page_num < _ESMIS_PAGE_COUNT - 1:
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
    try:
        head = data[:16384].decode("latin-1")
    except Exception as exc:
        raise RuntimeError(
            f"TXT response is not decodable as text from {url}: {exc}"
        ) from exc

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
            logger.info("Skipping — already in S3: %s", s3_key)
            time.sleep(sleep_seconds)
            return "skipped"

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

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed %s (%s): %s", release_date, url, exc)
        time.sleep(sleep_seconds)
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
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
        return

    # ------------------------------------------------------------------
    # Upload mode
    # ------------------------------------------------------------------
    entries = _load_manifest()

    if args.year_from is not None:
        entries = [e for e in entries if int(e["release_date"][:4]) >= args.year_from]
    if args.year_to is not None:
        entries = [e for e in entries if int(e["release_date"][:4]) <= args.year_to]
    if args.fmt is not None:
        entries = [e for e in entries if e["fmt"] == args.fmt]

    if not entries:
        logger.warning("No entries to process after filtering.")
        session.close()
        return

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
        return

    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0
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

    session.close()
    logger.info("Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors)


if __name__ == "__main__":
    main()
