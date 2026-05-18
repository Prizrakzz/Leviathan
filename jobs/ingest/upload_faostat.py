from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import upload_file_to_s3

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Local FAOSTAT QCL ZIP path")
    args = parser.parse_args()

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    local_path = Path(args.file)

    # Single shared ZIP for all commodities — no ingest_date or commodity prefix.
    # The Glue job filters to the relevant FAO item at runtime.
    s3_key = "raw/production/source=faostat/dataset=QCL/Production_Crops_Livestock_E_All_Data_Normalized.zip"

    raw_bytes = local_path.read_bytes()

    # --- Decompression test: verify ZIP integrity and CSV presence before upload ---
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            bad_file = zf.testzip()
            if bad_file is not None:
                raise RuntimeError(f"ZIP corruption detected in member: {bad_file}")
            if not any(name.lower().endswith(".csv") for name in zf.namelist()):
                raise RuntimeError("No CSV file found inside FAOSTAT ZIP.")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Failed to open FAOSTAT ZIP '{local_path}': {exc}") from exc

    # --- Size threshold check ---
    check_min_file_size(raw_bytes, "faostat_qcl", context=str(local_path))

    upload_file_to_s3(
        local_path=local_path,
        bucket=bucket,
        key=s3_key,
        aws_region=region,
    )

    write_raw_s3_metadata(
        bucket, s3_key, raw_bytes, "local_upload", "application/zip", region
    )

    logger.info("Uploaded %s to s3://%s/%s", local_path, bucket, s3_key)


if __name__ == "__main__":
    main()
