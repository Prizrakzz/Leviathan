"""Fetch SAGIS South Africa Weekly Data Excel files to raw S3.

Discovery
---------
SAGIS publishes cumulative per-season Excel files for weekly producer
deliveries and weekly imports/exports on a single WordPress page:

    GET https://www.sagis.org.za/wp-json/wp/v2/pages
        ?slug=sagis-weekly-data&_fields=content

Parsing ``content.rendered`` extracts all ``*.xlsx`` / ``*.xls`` links.

Data structure
--------------
Each Excel file is a *cumulative snapshot* for one marketing season, updated
weekly with a new filename (new week-number suffix).  Historical seasons have
one final file; the current season accumulates one new file per week.

Datasets and crops on this page:

  producer_deliveries
      maize       ProdProgressive-Mielies_*  /  ProdProgressive_-_Mielies_*
      maize_grade SWP_Grade_Per_Week_*
      wheat       ProdProgressive-Koring_*   /  ProdProgressive_-_Koring_*
      soybeans    ProdProgressive-Sojabone_* /  ProdProgressive_-_Sojabone_*
      sunflower   ProdProgressive-Sonneblom_* / ProdProgressive_-_-Sonneblom_*

  imp_exp_intentions   (8-week rolling window)
      maize       Intended-MAIZE-WeekEnding_*
      wheat       Intended-WHEAT-WeekEnding_*

  imp_exp_progressive  (per marketing season, back to 2003/04)
      maize       IMP-EXP_Progressive*Mielies_*
      wheat       IMP-EXP_Progressive*Koring_*

  imp_exp_historic     (single consolidated archive files)
      maize       Week_inligting_Mielies*
      wheat       Week_inligting_Koring*

File formats
------------
Modern files (2023+) are ``.xlsx`` (ZIP-based Open XML).
Older files (pre-2023) are ``.xls`` (OLE compound document).
Both are validated by magic bytes before upload.

S3 key structure
----------------
    raw/production/source=sagis_weekly/
        dataset={dataset}/
        crop={crop}/
        {filename}

Flat within dataset/crop — no season partition needed; the filename itself
encodes the marketing season and week number.

Manifest
--------
Successfully uploaded files are appended to
``configs/sources/sagis_weekly_manifest.yaml`` so future runs can skip
already-seen URLs without an S3 round-trip.

Idempotency
-----------
  --skip-existing-s3  Skip keys already present in S3.
  --dry-run           Print classified URLs without downloading.
  --limit N           Process at most N files — use 5 for a smoke test.
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from urllib.parse import unquote

import requests
import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_sagis_weekly_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WP_API_URL = (
    "https://www.sagis.org.za/wp-json/wp/v2/pages"
    "?slug=sagis-weekly-data&_fields=content"
)

# Matches .xlsx and .xls links in the WordPress-rendered HTML.
_EXCEL_LINK_RE = re.compile(
    r'(https://www\.sagis\.org\.za/wp-content/uploads/[^"]+\.xlsx?)',
    re.IGNORECASE,
)

# Magic bytes for Excel format validation.
_MAGIC_ZIP = b"PK\x03\x04"        # .xlsx / Open XML (ZIP-based)
_MAGIC_OLE = b"\xd0\xcf\x11\xe0"  # .xls  / OLE compound document

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "sources" / "sagis_weekly_manifest.yaml"
)

_DEFAULT_SLEEP = 1.0

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# (keyword_1, keyword_2_or_None, dataset, crop)  — applied in order, first match wins.
# keyword matching is case-insensitive on the decoded filename.
_CLASSIFIERS: list[tuple[str, str | None, str, str]] = [
    # Producer deliveries — check specific patterns first
    ("SWP_Grade_Per_Week",          None,       "producer_deliveries", "maize_grade"),
    ("ProdProgressive",             "Mielies",  "producer_deliveries", "maize"),
    ("ProdProgressive",             "Koring",   "producer_deliveries", "wheat"),
    ("ProdProgressive",             "Sojabone", "producer_deliveries", "soybeans"),
    ("ProdProgressive",             "Sonneblom","producer_deliveries", "sunflower"),
    # Intentions
    ("Intended-MAIZE",              None,       "imp_exp_intentions",  "maize"),
    ("Intended-WHEAT",              None,       "imp_exp_intentions",  "wheat"),
    # Historic consolidated files (check before IMP-EXP to avoid mis-match)
    ("Week_inligting_Mielies",      None,       "imp_exp_historic",    "maize"),
    ("Week_inligting_Koring",       None,       "imp_exp_historic",    "wheat"),
    # Progressive imp/exp (IMP-EXP covers all naming variants)
    ("IMP-EXP",                     "Mielies",  "imp_exp_progressive", "maize"),
    ("IMP-EXP",                     "Koring",   "imp_exp_progressive", "wheat"),
]


def _classify(filename: str) -> tuple[str, str] | None:
    """Return ``(dataset, crop)`` for *filename*, or ``None`` if unrecognised.

    Matching is case-insensitive.
    """
    fn_lower = filename.lower()
    for kw1, kw2, dataset, crop in _CLASSIFIERS:
        if kw1.lower() in fn_lower:
            if kw2 is None or kw2.lower() in fn_lower:
                return dataset, crop
    return None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _discover_excel_urls(session: requests.Session) -> list[str]:
    """Query the SAGIS WP JSON API and return all unique Excel URLs.

    Raises:
        RuntimeError: If the API returns no pages or no Excel links.
    """
    logger.info("Querying SAGIS WP API: %s …", _WP_API_URL)
    resp = session.get(_WP_API_URL, timeout=30)
    resp.raise_for_status()

    pages = resp.json()
    if not pages:
        raise RuntimeError(
            "SAGIS WP API returned an empty response.  "
            "The page slug 'sagis-weekly-data' may have changed."
        )

    html = pages[0]["content"]["rendered"]
    raw_links = _EXCEL_LINK_RE.findall(html)

    seen: set[str] = set()
    urls: list[str] = []
    for link in raw_links:
        if link not in seen:
            seen.add(link)
            urls.append(link)

    logger.info("Discovered %d unique Excel/XLS links.", len(urls))
    if not urls:
        raise RuntimeError(
            "No Excel links found in page content.  "
            "SAGIS may have changed the page layout or URL structure."
        )
    return urls


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _load_manifest() -> list[dict]:
    if _MANIFEST_PATH.exists():
        data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8")) or {}
        return data.get("excels", [])
    return []


def _append_manifest(entry: dict) -> None:
    excels = _load_manifest()
    excels.append(entry)
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(
        {"excels": excels},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    _MANIFEST_PATH.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_excel(data: bytes, filename: str, source_url: str) -> str:
    """Validate magic bytes and return the MIME content-type.

    Args:
        data:       Downloaded file bytes.
        filename:   Decoded filename used to determine expected format.
        source_url: Used in error messages only.

    Returns:
        MIME type string — either Open XML or legacy Excel.

    Raises:
        RuntimeError: If the magic bytes do not match either Excel format.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if data[:4] == _MAGIC_ZIP:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if data[:4] == _MAGIC_OLE:
        return "application/vnd.ms-excel"
    raise RuntimeError(
        f"Unexpected file format (ext=.{ext}, magic={data[:4]!r}): {source_url}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch SAGIS Weekly Data Excel files to raw S3. "
            "Discovers all files via the SAGIS WordPress JSON API."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip files whose S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and classify all URLs without downloading anything.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N files — use 5 for a smoke test.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=_DEFAULT_SLEEP,
        help=f"Polite delay between downloads in seconds (default: {_DEFAULT_SLEEP}).",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = _UA

    # -----------------------------------------------------------------------
    # Discover
    # -----------------------------------------------------------------------
    urls = _discover_excel_urls(session)

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        unrecognised = 0
        print(f"Discovered: {len(urls)} Excel/XLS files")
        for u in urls:
            filename = unquote(u.rsplit("/", 1)[-1])
            result = _classify(filename)
            if result:
                dataset, crop = result
                print(f"  [{dataset:22s} / {crop:14s}]  {filename}")
            else:
                print(f"  [UNRECOGNISED                       ]  {filename}")
                unrecognised += 1
        if unrecognised:
            logger.warning("%d unrecognised file(s) — will be skipped.", unrecognised)
        return

    # -----------------------------------------------------------------------
    # Live run
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    known_urls: set[str] = {e["excel_url"] for e in _load_manifest()}

    if args.limit:
        urls = urls[: args.limit]

    uploaded = skipped = errors = 0

    for excel_url in urls:
        filename = unquote(excel_url.rsplit("/", 1)[-1])
        result = _classify(filename)

        if result is None:
            logger.warning("Unrecognised file — skipping: %s", filename)
            skipped += 1
            continue

        dataset, crop = result
        s3_key = raw_sagis_weekly_key(dataset, crop, filename)

        try:
            if excel_url in known_urls:
                logger.info("Skipping - in manifest: %s", filename)
                skipped += 1
                continue

            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping - already in S3: %s", s3_key)
                skipped += 1
                continue

            resp = session.get(excel_url, timeout=60)
            resp.raise_for_status()
            data = resp.content

            content_type = _validate_excel(data, filename, excel_url)
            check_min_file_size(data, "sagis_weekly", context=excel_url)

            upload_bytes_to_s3(data, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket, s3_key, data, excel_url, content_type, region
            )

            _append_manifest(
                {
                    "excel_url": excel_url,
                    "dataset": dataset,
                    "crop": crop,
                    "filename": filename,
                    "s3_key": s3_key,
                }
            )
            known_urls.add(excel_url)

            logger.info(
                "Uploaded [%s / %s]  %.1f KB → s3://%s/%s",
                dataset,
                crop,
                len(data) / 1024,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001 — any download, validation, or S3 error is logged; loop continues
            logger.error("Failed %s: %s", filename, exc)
            errors += 1

        time.sleep(args.sleep_seconds)

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )

    if errors:
        raise SystemExit(f"{errors} file(s) failed — see logs above.")


if __name__ == "__main__":
    main()
