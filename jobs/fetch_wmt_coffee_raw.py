"""Fetch USDA FAS Coffee: World Markets and Trade (WMT) circular PDFs to raw S3.

Discovery strategy
------------------
All 47 report URLs are stored in a static manifest:
  configs/sources/usda_fas_coffee_wmt_archive.yaml

fas.usda.gov is protected by a TLS-fingerprint WAF that blocks plain Python
``requests``.  Downloads are performed with ``curl_cffi`` impersonating Chrome,
which bypasses the WAF at the TLS handshake layer.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip reports already uploaded.  Re-running with
this flag is safe and fast.  Add ``--limit 1`` for a quick smoke-test.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml
from curl_cffi import requests as curl_requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_wmt_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF"
_IMPERSONATE = "chrome124"  # curl_cffi TLS persona — bypasses fas.usda.gov WAF

_MANIFEST_PATH = (
    Path(__file__).parent.parent / "configs" / "sources" / "usda_fas_coffee_wmt_archive.yaml"
)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _download_pdf(url: str, session: curl_requests.Session, timeout: int = 60) -> bytes:
    resp = session.get(url, impersonate=_IMPERSONATE, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download USDA FAS Coffee WMT circular PDFs to raw S3. "
            "Reads URLs from configs/sources/usda_fas_coffee_wmt_archive.yaml. "
            "Uses curl_cffi to bypass the fas.usda.gov TLS fingerprint WAF."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip reports whose S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and print all report URLs without downloading anything.",
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
        help="Process at most N reports — use 1 for a smoke test.",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load manifest
    # -----------------------------------------------------------------------
    manifest_data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    reports: list[dict] = manifest_data["reports"]
    logger.info("Loaded %d entries from manifest %s", len(reports), _MANIFEST_PATH.name)

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(f"Manifest: {_MANIFEST_PATH.name}  ({len(reports)} entries)")
        for entry in reports:
            note = f"  # {entry['note']}" if entry.get("note") else ""
            print(f"  {entry['publication_date']}  {entry['pdf_url']}{note}")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    if args.limit:
        reports = reports[: args.limit]

    uploaded = skipped = errors = 0

    with curl_requests.Session() as session:
        for entry in reports:
            pub_date = entry["publication_date"]
            pdf_url = entry["pdf_url"]
            s3_key = raw_wmt_key(pub_date)

            try:
                if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                    logger.info("Skipping — already in S3: %s", s3_key)
                    skipped += 1
                    continue

                logger.info("Downloading %s  %s …", pub_date, pdf_url)
                pdf_bytes = _download_pdf(pdf_url, session)

                if not pdf_bytes.startswith(_PDF_MAGIC):
                    raise RuntimeError(
                        f"Response is not a valid PDF (missing %%PDF header): {pdf_url}"
                    )
                check_min_file_size(pdf_bytes, "usda_fas_coffee_wmt", context=pdf_url)

                upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
                write_raw_s3_metadata(
                    bucket, s3_key, pdf_bytes, pdf_url, "application/pdf", region
                )

                logger.info(
                    "Uploaded %s  (%.1f MB) → s3://%s/%s",
                    pub_date,
                    len(pdf_bytes) / 1_048_576,
                    bucket,
                    s3_key,
                )
                uploaded += 1

            except Exception as exc:  # noqa: BLE001
                logger.error("Failed %s (%s): %s", pub_date, pdf_url, exc)
                errors += 1

            time.sleep(args.sleep_seconds)

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )

    if errors:
        raise SystemExit(f"{errors} report(s) failed — see logs above.")


if __name__ == "__main__":
    main()

