from __future__ import annotations

import argparse
import logging
from pathlib import Path

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_conab_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import upload_file_to_s3

logger = get_logger(__name__)

_PDF_MAGIC = b"%PDF"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description="Upload a CONAB Boletim da Safra de Café PDF to raw S3."
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to the locally downloaded CONAB PDF.",
    )
    parser.add_argument(
        "--crop-year",
        required=True,
        help="Marketing year in underscore format, e.g. 2024_25 (April–March).",
    )
    parser.add_argument(
        "--survey-number",
        required=True,
        type=int,
        choices=range(1, 6),
        metavar="{1-5}",
        help="Survey number within the season (1–5).",
    )
    args = parser.parse_args()

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    local_path = Path(args.file)

    # --- File extension check ---
    if local_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Expected a .pdf file, got '{local_path.suffix}': {local_path}"
        )

    raw_bytes = local_path.read_bytes()

    # --- PDF magic bytes check: catches HTML error pages or truncated downloads ---
    if not raw_bytes.startswith(_PDF_MAGIC):
        raise RuntimeError(
            f"File does not appear to be a valid PDF (missing %PDF header): {local_path}"
        )

    # --- Size threshold check ---
    check_min_file_size(raw_bytes, "conab", context=str(local_path))

    s3_key = raw_conab_key(args.crop_year, args.survey_number)

    upload_file_to_s3(
        local_path=local_path,
        bucket=bucket,
        key=s3_key,
        aws_region=region,
    )

    write_raw_s3_metadata(
        bucket, s3_key, raw_bytes, "local_upload", "application/pdf", region
    )

    logger.info(
        "Uploaded %s (%.1f MB) to s3://%s/%s",
        local_path,
        len(raw_bytes) / 1_048_576,
        bucket,
        s3_key,
    )


if __name__ == "__main__":
    main()
