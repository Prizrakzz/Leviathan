"""Fetch FNC Colombia monthly report PDFs to raw S3.

Two report series are downloaded:

  cifras       — Informe Mensual de Cifras (production statistics narrative)
                 https://federaciondecafeteros.org/informe-mensual-de-cifras/
  exportaciones — Informe Mensual de Exportaciones (export breakdown narrative)
                  https://federaciondecafeteros.org/informemensualdeexporaciones/

Discovery strategy
------------------
1. Live page scrape — requests.get on each report index page, extract all
   PDF href links matching known report filename patterns.

2. Wayback CDX backfill (opt-in via --historical) — queries
   web.archive.org/cdx for archived PDF URLs under both WordPress upload
   prefixes (app/uploads and wp-content/uploads), filtered to filenames
   that match report naming patterns.  PDFs already discovered from the
   live page are skipped.  Historical PDFs are downloaded via the Wayback
   `if_` modifier, which serves the original response rather than the
   annotated Wayback page.

Noise filtering
---------------
The FNC report pages include sidebar/navigation links to non-report PDFs
(ethics codes, statutes, single-page price charts).  Only PDFs whose
filenames contain "Informe" or "Reporte" are downloaded.

S3 key structure
----------------
  raw/production/source=fnc/monthly_reports/
      report_type={cifras|exportaciones}/
      upload_year={YYYY}/
      upload_month={MM}/
      {filename}.pdf

  upload_year/upload_month come from the /uploads/YYYY/MM/ path in the URL,
  not from the report's reference month.  Report month assignment is done
  in the bronze transform.

Manifest
--------
Successfully uploaded PDFs are appended to configs/sources/fnc_reports.yaml
so future runs can skip them with --skip-existing-s3.

Idempotency
-----------
  --skip-existing-s3  — skip keys already present in S3.
  --dry-run           — print candidate URLs without downloading.
  --limit N           — process at most N PDFs per run (use 1 to smoke-test).

Rate limiting
-------------
FNC is a WordPress site on Colombian hosting, not a CDN.  Default sleep is
2.0 s between requests.  max_workers is not used — all downloads are
sequential to respect the server.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import ssl
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import unquote

import requests
import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_fnc_report_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF"
_MIN_PDF_BYTES = 5_000  # sanity floor

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CDX_UA = "Leviathan-Data-Pipeline/1.0 (research)"

_SSL_CTX = ssl.create_default_context()

_MANIFEST_PATH = (
    Path(__file__).parent.parent / "configs" / "sources" / "fnc_reports.yaml"
)

# Report index pages to scrape
_REPORT_PAGES: dict[str, str] = {
    "cifras": "https://federaciondecafeteros.org/informe-mensual-de-cifras/",
    "exportaciones": "https://federaciondecafeteros.org/informemensualdeexporaciones/",
}

# Wayback CDX prefix scans for historical backfill
_CDX_PREFIXES = [
    "federaciondecafeteros.org/app/uploads/",
    "federaciondecafeteros.org/wp-content/uploads/",
]

# Filename must contain one of these strings (case-insensitive) to be kept.
# Excludes: precio_cafe.pdf, Codigo-de-Etica*, ESTATUTOS*, etc.
_REPORT_KEYWORDS = ("informe", "reporte")

# Regex to extract upload year/month from URL path: /uploads/YYYY/MM/
_UPLOAD_YM_RE = re.compile(r"/uploads/(\d{4})/(\d{2})/")

# Determine report_type from filename heuristic
_EXPORTACIONES_KEYWORDS = ("expos", "export")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_report_pdf(url: str) -> bool:
    """Return True if the URL looks like a monthly report PDF (not noise)."""
    filename = unquote(url.rsplit("/", 1)[-1]).lower()
    return any(kw in filename for kw in _REPORT_KEYWORDS)


def _report_type_from_url(url: str, page_key: str) -> str:
    """Infer report_type from URL filename; fall back to the scrape page key."""
    filename = unquote(url.rsplit("/", 1)[-1]).lower()
    if any(kw in filename for kw in _EXPORTACIONES_KEYWORDS):
        return "exportaciones"
    return page_key  # trust the scrape context over filename heuristic


def _upload_ym(url: str) -> tuple[int, int]:
    """Extract (upload_year, upload_month) from a wp-content/uploads URL.

    Returns (0, 0) when the path does not contain the expected /YYYY/MM/ segment.
    """
    m = _UPLOAD_YM_RE.search(url)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


# ---------------------------------------------------------------------------
# Live page scraping
# ---------------------------------------------------------------------------


def _scrape_live_page(
    page_key: str, page_url: str, session: requests.Session
) -> list[tuple[str, str]]:
    """Scrape PDF links from a live FNC report index page.

    Returns list of (report_type, pdf_url) tuples, filtered to report PDFs only.
    """
    resp = session.get(page_url, timeout=20)
    resp.raise_for_status()
    raw_links = re.findall(
        r'href=["\']'
        r'(https?://federaciondecafeteros\.org[^"\']*\.pdf)'
        r'["\']',
        resp.text,
        re.IGNORECASE,
    )
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for link in raw_links:
        if link in seen:
            continue
        seen.add(link)
        if _is_report_pdf(link):
            results.append((_report_type_from_url(link, page_key), link))
    logger.info(
        "Live scrape: %s → %d report PDFs (from %d raw links)",
        page_key,
        len(results),
        len(raw_links),
    )
    return results


# ---------------------------------------------------------------------------
# Wayback CDX backfill
# ---------------------------------------------------------------------------


def _cdx_scan(prefix: str, limit: int = 500) -> list[tuple[str, str]]:
    """Scan Wayback CDX for archived FNC report PDFs under *prefix*.

    Returns list of (timestamp, original_url) pairs, filtered to report PDFs.
    """
    api_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={urllib.parse.quote(prefix, safe='')}"
        "&matchType=prefix"
        "&output=json"
        "&fl=timestamp,original"
        "&filter=mimetype:application/pdf"
        "&filter=statuscode:200"
        f"&filter=original:.*[Ii]nforme.*"
        "&collapse=original"
        f"&limit={limit}"
    )
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": _CDX_UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
            rows = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001 — any network error returns empty list; CDX scan is best-effort
        logger.warning("CDX scan failed for prefix %s: %s", prefix, exc)
        return []

    # First row is the header ["timestamp","original"] — skip it.
    results = []
    for row in rows[1:]:
        ts, orig = row[0], row[1]
        if _is_report_pdf(orig):
            results.append((ts, orig))
    logger.info("CDX scan %s → %d report PDFs", prefix, len(results))
    return results


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def _direct_get(url: str, session: requests.Session, timeout: int = 60) -> bytes | None:
    """Attempt direct download from FNC server.

    WordPress on macOS-style filesystems stores filenames in NFD Unicode
    (decomposed), so non-ASCII characters in the path must be NFD-normalized
    before percent-encoding (e.g. 'é' → 'e%CC%81', not '%C3%A9').
    """
    parsed = urllib.parse.urlparse(url)
    nfd_path = unicodedata.normalize("NFD", parsed.path)
    encoded_path = urllib.parse.quote(nfd_path, safe="/:@!$&'()*+,;=_-.~%")
    encoded_url = urllib.parse.urlunparse(parsed._replace(path=encoded_path))
    try:
        resp = session.get(encoded_url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > _MIN_PDF_BYTES:
            return resp.content
        logger.debug("Direct GET %s → HTTP %d", encoded_url[-60:], resp.status_code)
    except Exception as exc:  # noqa: BLE001 — any network error returns None; caller tries the next strategy
        logger.debug("Direct GET failed %s: %s", encoded_url[-60:], exc)
    return None


def _wayback_get(original_url: str, ts: str, timeout: int = 60) -> bytes | None:
    """Fetch via Wayback Machine using the `if_` modifier (raw response)."""
    wb_url = f"https://web.archive.org/web/{ts}if_/{original_url}"
    try:
        req = urllib.request.Request(wb_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            data = resp.read()
            if data and len(data) > _MIN_PDF_BYTES:
                return data
    except Exception as exc:  # noqa: BLE001 — any network error returns None; caller tries the next strategy
        logger.debug("Wayback GET failed %s: %s", wb_url[-70:], exc)
    return None


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _load_manifest() -> list[dict]:
    if _MANIFEST_PATH.exists():
        data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8")) or {}
        return data.get("reports", [])
    return []


def _append_manifest(entry: dict) -> None:
    reports = _load_manifest()
    reports.append(entry)
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(
        {"reports": reports},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    _MANIFEST_PATH.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Fetch FNC Colombia monthly report PDFs to raw S3. "
            "Scrapes live index pages; optionally adds Wayback CDX backfill."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip PDFs whose S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and print all candidate URLs without downloading.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="Polite delay between HTTP requests in seconds (default: 2.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N PDFs — use 1 for a smoke test.",
    )
    parser.add_argument(
        "--historical",
        action="store_true",
        help=(
            "Also scan Wayback CDX for pre-2024 archived PDFs. "
            "Adds significant runtime."
        ),
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = _UA

    # -----------------------------------------------------------------------
    # Discover candidate PDFs
    # -----------------------------------------------------------------------

    # candidates: list of (report_type, pdf_url, wayback_ts_or_None)
    candidates: list[tuple[str, str, str | None]] = []
    seen_originals: set[str] = set()

    # 1. Live pages
    for page_key, page_url in _REPORT_PAGES.items():
        try:
            for rtype, url in _scrape_live_page(page_key, page_url, session):
                if url not in seen_originals:
                    seen_originals.add(url)
                    candidates.append((rtype, url, None))
        except Exception as exc:  # noqa: BLE001 — any scrape failure is logged; loop continues to the next page
            logger.error("Failed to scrape %s (%s): %s", page_key, page_url, exc)
        time.sleep(args.sleep_seconds)

    # 2. CDX backfill (optional)
    if args.historical:
        for prefix in _CDX_PREFIXES:
            for ts, orig in _cdx_scan(prefix):
                if orig not in seen_originals:
                    seen_originals.add(orig)
                    rtype = _report_type_from_url(orig, "cifras")
                    candidates.append((rtype, orig, ts))
            time.sleep(1.0)

    logger.info("Total candidates: %d PDFs", len(candidates))

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(f"Candidates: {len(candidates)}")
        for rtype, url, ts in candidates:
            wayback = f"  [wayback ts={ts}]" if ts else ""
            print(f"  {rtype:15s}  {url}{wayback}")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    if args.limit:
        candidates = candidates[: args.limit]

    uploaded = skipped = errors = 0

    for rtype, pdf_url, wayback_ts in candidates:
        upload_year, upload_month = _upload_ym(pdf_url)
        raw_filename = unquote(pdf_url.rsplit("/", 1)[-1])
        s3_key = raw_fnc_report_key(rtype, upload_year, upload_month, raw_filename)

        try:
            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            # Prefer direct download; fall back to Wayback for historical.
            pdf_bytes: bytes | None = None
            if wayback_ts:
                # Historical CDX entry — use Wayback first.
                pdf_bytes = _wayback_get(pdf_url, wayback_ts)
                if pdf_bytes is None:
                    pdf_bytes = _direct_get(pdf_url, session)
            else:
                # Live page link — direct download first.
                pdf_bytes = _direct_get(pdf_url, session)
                if pdf_bytes is None and args.historical:
                    # Retry via Wayback if available (edge case: live link is broken).
                    logger.warning("Direct failed; no Wayback ts for %s", pdf_url[-60:])

            if pdf_bytes is None:
                raise RuntimeError(f"All download strategies exhausted for {pdf_url}")

            if not pdf_bytes.startswith(_PDF_MAGIC):
                raise RuntimeError(
                    f"Response is not a valid PDF (missing %%PDF header): {pdf_url}"
                )
            if len(pdf_bytes) < _MIN_PDF_BYTES:
                raise RuntimeError(
                    f"File suspiciously small ({len(pdf_bytes):,} bytes): {pdf_url}"
                )

            upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket, s3_key, pdf_bytes, pdf_url, "application/pdf", region
            )

            _append_manifest(
                {
                    "report_type": rtype,
                    "source_url": pdf_url,
                    "s3_key": s3_key,
                    "upload_year": upload_year,
                    "upload_month": upload_month,
                    "filename": raw_filename,
                }
            )

            logger.info(
                "Uploaded (%s, uy=%d, um=%02d) %.1f KB → s3://%s/%s",
                rtype,
                upload_year,
                upload_month,
                len(pdf_bytes) / 1024,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed %s (%s): %s", rtype, pdf_url, exc)
            errors += 1

        time.sleep(args.sleep_seconds)

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )

    if errors:
        raise SystemExit(f"{errors} PDF(s) failed — see logs above.")


if __name__ == "__main__":
    main()
