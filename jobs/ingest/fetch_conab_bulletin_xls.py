"""Download CONAB per-bulletin Excel (previsão de safra) files to raw S3.

Each CONAB Boletim de Acompanhamento da Safra de Café bulletin page on
gov.br includes a companion .xls data file containing the structured
area/production/productivity tables.  This job downloads those XLS files.

Discovery input
---------------
Reads data/conab/conab_bulletin_excels.json produced by
jobs/ingest/discover_conab_bulletin_xls.py.
Run the probe first to refresh the URL list.

S3 key
------
  raw/production/source=conab/bulletin_xls/
    safra_year={safra_year}/survey={survey_no:02d}/{filename}

Magic validation
----------------
Old Excel OLE compound file:  bytes 0-3 == D0 CF 11 E0
New Excel Open XML (XLSX):    bytes 0-3 == 50 4B 03 04  (ZIP)
Both are accepted; files not matching either magic are rejected.

Run
---
    .venv\\Scripts\\python.exe jobs/ingest/fetch_conab_bulletin_xls.py [--skip-existing-s3] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from curl_cffi import requests as curl_requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_conab_hist_series_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_XLS_MAGIC_OLE  = b"\xd0\xcf\x11\xe0"  # OLE compound file (.xls)
_XLS_MAGIC_ZIP  = b"PK\x03\x04"        # Open XML (.xlsx / .xlsm)
_MIN_XLS_BYTES  = 5_000                 # sanity floor; real CONAB files are ~490 KB

_IMPERSONATE = "chrome124"
_CONTENT_TYPE_XLS  = "application/vnd.ms-excel"
_CONTENT_TYPE_XLSX = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_MANIFEST_PATH = _PROJECT_ROOT / "data" / "conab" / "conab_bulletin_excels.json"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _download_xls(url: str, session: curl_requests.Session, timeout: int = 60) -> bytes:
    resp = session.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download CONAB per-bulletin Excel files to raw S3. "
            "Reads data/conab/conab_bulletin_excels.json "
            "(run discover_conab_bulletin_xls.py first)."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip files whose S3 key already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print candidate URLs without downloading.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="Polite delay between HTTP requests in seconds (default: 2.0).",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load manifest
    # -----------------------------------------------------------------------
    if not _MANIFEST_PATH.exists():
        parser.error(
            f"Not found: {_MANIFEST_PATH}\n"
            "  Run: .venv\\Scripts\\python.exe jobs/ingest/discover_conab_bulletin_xls.py"
        )

    entries: list[dict] = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    logger.info("Loaded %d entries from %s", len(entries), _MANIFEST_PATH.name)

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(f"Dry run: {len(entries)} bulletin Excel file(s)")
        for e in sorted(entries, key=lambda x: (x["safra_year"], x["survey_no"])):
            filename = e.get("filename") or e["xls_url"].rsplit("/", 1)[-1]
            s3_key = raw_conab_hist_series_key(e["safra_year"], e["survey_no"], filename)
            print(f"  {e['survey_no']}o Safra {e['safra_year']}  {filename}")
            print(f"    -> s3://.../{s3_key}")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0

    session = curl_requests.Session()

    for e in sorted(entries, key=lambda x: (x["safra_year"], x["survey_no"])):
        xls_url  = e["xls_url"]
        filename = e.get("filename") or xls_url.rsplit("/", 1)[-1]
        safra_year = int(e["safra_year"])
        survey_no  = int(e["survey_no"])
        s3_key = raw_conab_hist_series_key(safra_year, survey_no, filename)

        try:
            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            logger.info(
                "Downloading %do Safra %d  %s ...", survey_no, safra_year, xls_url
            )
            data = _download_xls(xls_url, session)

            # Validate magic bytes
            magic4 = data[:4]
            if magic4 == _XLS_MAGIC_OLE:
                content_type = _CONTENT_TYPE_XLS
            elif data[:3] == _XLS_MAGIC_ZIP[:3]:
                content_type = _CONTENT_TYPE_XLSX
            else:
                raise RuntimeError(
                    f"Response is not a valid XLS/XLSX file (magic={magic4.hex()}): {xls_url}"
                )

            if len(data) < _MIN_XLS_BYTES:
                raise RuntimeError(
                    f"File suspiciously small ({len(data):,} bytes): {xls_url}"
                )

            upload_bytes_to_s3(data, bucket, s3_key, region)
            write_raw_s3_metadata(bucket, s3_key, data, xls_url, content_type, region)

            logger.info(
                "Uploaded %s (%.1f KB) -> s3://%s/%s",
                filename,
                len(data) / 1024,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001 — any download or S3 upload failure is logged and counted; loop continues to the next entry
            logger.error(
                "FAILED %do Safra %d (%s): %s", survey_no, safra_year, filename, exc
            )
            errors += 1

        time.sleep(args.sleep_seconds)

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
