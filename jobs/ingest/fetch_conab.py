"""Fetch CONAB Boletim da Safra de Café PDFs to raw S3.

Discovery strategy
------------------
All known survey URLs are stored in a static manifest:
  configs/sources/conab_archive.yaml

gov.br/conab (Plone CMS) serves PDFs in two patterns:
  A) URL ends in .pdf  — standard download
  B) URL has no extension — Plone file object serving application/pdf bytes

Both patterns return valid PDF content (verified by magic bytes %PDF).

curl_cffi with impersonate='chrome124' is used to bypass TLS fingerprint
filtering.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip surveys already uploaded.  Re-running
with this flag is safe and fast.  Add ``--limit 1`` for a quick smoke-test.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml
from curl_cffi import requests as curl_requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_conab_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF"
_IMPERSONATE = "chrome124"

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "sources" / "conab_archive.yaml"
)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _download_pdf(url: str, session: curl_requests.Session, timeout: int = 90) -> bytes:
    """Download a PDF from gov.br/conab.

    Handles both URL patterns:
      - URLs ending in .pdf (standard)
      - URLs without extension (Plone file objects serving application/pdf)
    """
    resp = session.get(url, impersonate=_IMPERSONATE, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download CONAB Boletim da Safra de Café PDFs to raw S3. "
            "Reads URLs from configs/sources/conab_archive.yaml. "
            "gov.br/conab requires curl_cffi (TLS impersonation)."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip surveys whose S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print all survey URLs without downloading anything.",
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
        help="Process at most N surveys — use 1 for a smoke test.",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load manifest
    # -----------------------------------------------------------------------
    manifest_data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    surveys: list[dict] = manifest_data["surveys"]
    logger.info("Loaded %d entries from manifest %s", len(surveys), _MANIFEST_PATH.name)

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(f"Manifest: {_MANIFEST_PATH.name}  ({len(surveys)} entries)")
        for entry in surveys:
            print(
                f"  crop_year={entry['crop_year']}  survey={entry['survey_number']:02d}"
                f"  {entry['pdf_url']}"
            )
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    if args.limit:
        surveys = surveys[: args.limit]

    uploaded = skipped = errors = 0

    with curl_requests.Session() as session:
        for entry in surveys:
            crop_year = entry["crop_year"]
            survey_number = int(entry["survey_number"])
            pdf_url = entry["pdf_url"]
            s3_key = raw_conab_key(crop_year, survey_number)

            try:
                if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                    logger.info("Skipping — already in S3: %s", s3_key)
                    skipped += 1
                    continue

                logger.info(
                    "Downloading crop_year=%s survey=%02d  %s …",
                    crop_year,
                    survey_number,
                    pdf_url,
                )
                pdf_bytes = _download_pdf(pdf_url, session)

                if not pdf_bytes.startswith(_PDF_MAGIC):
                    raise RuntimeError(
                        f"Response is not a valid PDF (missing %PDF header): {pdf_url}"
                    )
                check_min_file_size(pdf_bytes, "conab", context=pdf_url)

                upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
                write_raw_s3_metadata(
                    bucket, s3_key, pdf_bytes, pdf_url, "application/pdf", region
                )

                logger.info(
                    "Uploaded crop_year=%s survey=%02d  (%.1f MB) → s3://%s/%s",
                    crop_year,
                    survey_number,
                    len(pdf_bytes) / 1_048_576,
                    bucket,
                    s3_key,
                )
                uploaded += 1

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed crop_year=%s survey=%02d (%s): %s",
                    crop_year,
                    survey_number,
                    pdf_url,
                    exc,
                )
                errors += 1

            time.sleep(args.sleep_seconds)

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )


if __name__ == "__main__":
    main()
