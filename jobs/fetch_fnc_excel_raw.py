"""Download FNC Colombia bulk Excel data files to raw S3.

Two files are downloaded on each run:

  Precios-area-y-produccion-de-cafe-YYYY-N.xlsx
    Key sheets:
      '8. Producción mensual'     — monthly production (1000s of 60 kg bags), 1956–present
      '3. Precio Ex_Dock Mensual' — monthly external price (USD cents/lb), 1913–present
      '2. Precio Interno Mensual' — monthly internal price (COP/125 kg), 1944–present
      '7. Área cult. dep. producto' — area by department (1000s ha), 2002–present

  Exportaciones-YYYY-N.xlsx
    Key sheets:
      '1. Total_Volumen'          — monthly export volume (1000s of 60 kg bags), 1958–present
      '2. Total_Valor'            — monthly export value (M USD), 1958–present
      '5. Puerto_Tipo_Vol_Val'    — monthly volume+value by type and port, 2000–present

The Excel files contain the full historical series and are re-published
annually with updated data.  FNC's server has no WAF — plain requests work.

Source config: configs/sources/fnc_excel_sources.yaml
S3 key:        raw/production/source=fnc/bulk/{filename}
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import requests
import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_fnc_excel_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# xlsx files are ZIP archives — first four bytes are the ZIP local-file header.
_XLSX_MAGIC = b"PK\x03\x04"
_MIN_EXCEL_BYTES = 10_000  # sanity floor; real FNC files are 460 KB+

_MANIFEST_PATH = (
    Path(__file__).parent.parent / "configs" / "sources" / "fnc_excel_sources.yaml"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _download_excel(url: str, session: requests.Session, timeout: int = 60) -> bytes:
    resp = session.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download FNC Colombia bulk Excel files to raw S3. "
            "Reads URLs from configs/sources/fnc_excel_sources.yaml."
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
        help="Print URLs without downloading.",
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
    manifest_data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    files: list[dict] = manifest_data["files"]
    logger.info("Loaded %d file entries from %s", len(files), _MANIFEST_PATH.name)

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        for entry in files:
            print(f"  {entry['name']:30s}  {entry['url']}")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0

    session = requests.Session()
    session.headers["User-Agent"] = _UA

    for entry in files:
        url = entry["url"]
        filename = entry["filename"]
        s3_key = raw_fnc_excel_key(filename)

        try:
            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            logger.info("Downloading %s  %s …", entry["name"], url)
            data = _download_excel(url, session)

            if not data.startswith(_XLSX_MAGIC):
                raise RuntimeError(
                    f"Response is not a valid xlsx (missing ZIP header): {url}"
                )
            if len(data) < _MIN_EXCEL_BYTES:
                raise RuntimeError(
                    f"File suspiciously small ({len(data):,} bytes): {url}"
                )

            upload_bytes_to_s3(data, bucket, s3_key, region)
            write_raw_s3_metadata(bucket, s3_key, data, url, _CONTENT_TYPE, region)

            logger.info(
                "Uploaded %s (%.1f MB) → s3://%s/%s",
                filename,
                len(data) / 1_048_576,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed %s (%s): %s", entry["name"], url, exc)
            errors += 1

        time.sleep(args.sleep_seconds)

    logger.info("Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors)

    if errors:
        raise SystemExit(f"{errors} file(s) failed — see logs above.")


if __name__ == "__main__":
    main()
