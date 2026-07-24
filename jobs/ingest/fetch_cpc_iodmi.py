"""Fetch the NOAA CPC IODMI (ERSSTv5) DMI file and write raw + bronze to S3.

Source
------
NOAA Climate Prediction Center -- Indian Ocean Dipole Mode Index, ERSSTv5 basis, fixed
1991-2020 climatology
    https://www.cpc.ncep.noaa.gov/products/international/ocean_monitoring/IODMI/mnth.ersstv5.clim19912020.dmi_current.txt

No authentication required.  Single ASCII text file (~42 KB) updated monthly in-place with
~1 month of publication lag; the full history from January 1950 is included in every
release.  Because this is a single tiny file with no WAF, no pagination and no URL
discovery step, the ingest and bronze transform are combined in one script -- the same
pattern as ``fetch_noaa_iod.py`` / ``fetch_noaa_oni.py``.

This is the re-baselined IOD source ratified in ``docs/private/ADR_IOD_SOURCE_SWITCH.md``
(Option B): the incumbent HadISST DMI has been frozen upstream since 2025-06-16 (last real
observation 2025-04).  ``fetch_noaa_iod.py`` is deliberately NOT retired -- it still
captures the HadISST series for the immutable ``_hadisst_frozen`` provenance snapshot.

Provenance
----------
The raw object is the upstream bytes VERBATIM (no re-encoding, no parsing, no filtering) at
a truthful ``source=cpc_iodmi`` prefix, and a provenance line -- source URL, fetch time in
UTC, byte count, sha256 of the captured bytes -- is logged for every capture.  All record
parsing lives in ``leviathan.transforms.raw_to_bronze.cpc_iodmi``; this script owns none of
it, so raw and bronze can never disagree about what the file said.

S3 layout
---------
    Raw:    raw/weather/source=cpc_iodmi/mnth.ersstv5.clim19912020.dmi_current.txt (overwrite)
    Bronze: bronze/weather/source=cpc_iodmi/part-000.parquet                       (overwrite)

Both objects are overwritten on each run.

Usage
-----
    python jobs/ingest/fetch_cpc_iodmi.py
    python jobs/ingest/fetch_cpc_iodmi.py --dry-run
    python jobs/ingest/fetch_cpc_iodmi.py --skip-existing-raw
    python jobs/ingest/fetch_cpc_iodmi.py --force-bronze
"""
from __future__ import annotations

import argparse
import hashlib
import io
import logging
import sys
import time
from datetime import datetime, timezone

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_cpc_iodmi_key, raw_cpc_iodmi_key
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.cpc_iodmi import extract_cpc_iodmi_bronze

logger = get_logger("fetch_cpc_iodmi")

_IODMI_URL = (
    "https://www.cpc.ncep.noaa.gov/products/international/ocean_monitoring/IODMI/"
    "mnth.ersstv5.clim19912020.dmi_current.txt"
)
_TIMEOUT = 30

# CPC is a single unauthenticated origin with no rate limit, so a short bounded retry with
# exponential backoff is enough to ride out a transient 5xx / connection reset.
_MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = 5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Sanity check: the preamble names the reconstruction and both anomaly boxes. A WAF splash
# page or an HTML 404 body carries none of these tokens.
_EXPECTED_TOKENS = ("ERSST", "WTIO", "SETIO", "DMI")
_PREAMBLE_SNIFF_BYTES = 512


def _write_parquet(data: bytes, bucket: str, key: str, aws_region: str) -> None:
    import boto3
    from leviathan.storage.s3 import _BOTO_RETRY_CONFIG
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/octet-stream")


def fetch_with_retry(url: str = _IODMI_URL) -> bytes:
    """GET ``url`` with bounded exponential-backoff retry; return the response bytes.

    Retries on a connection-level failure or a retryable status (429/5xx) and re-raises the
    last error once the attempt budget is spent, so a transient CPC blip does not fail the
    monthly chain but a genuine outage still surfaces truthfully.
    """
    backoff = _BACKOFF_SECONDS
    last_error: Exception | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "CPC returned HTTP %d (attempt %d/%d) -- retrying in %ds",
                    resp.status_code, attempt, _MAX_ATTEMPTS, backoff,
                )
            else:
                resp.raise_for_status()
                return resp.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            logger.warning(
                "Fetch failed (attempt %d/%d): %s -- retrying in %ds",
                attempt, _MAX_ATTEMPTS, exc, backoff,
            )
        time.sleep(backoff)
        backoff *= 2

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url} after {_MAX_ATTEMPTS} attempts")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(
        description="Fetch NOAA CPC IODMI (ERSSTv5) file -> raw S3 + bronze Parquet"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--skip-existing-raw", action="store_true",
                        help="Skip the HTTP fetch if the raw S3 key already exists")
    parser.add_argument("--force-bronze", action="store_true",
                        help="Re-write bronze even if raw was skipped")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the S3 keys and row count without writing anything")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    r_key = raw_cpc_iodmi_key()
    b_key = bronze_cpc_iodmi_key()

    logger.info("CPC IODMI ingest  bucket=%s  raw=%s", bucket, r_key)

    if args.dry_run:
        print(f"Source URL : {_IODMI_URL}")
        print(f"Raw key    : {r_key}")
        print(f"Bronze key : {b_key}")
        print("(dry-run -- no writes)")
        return

    # ------------------------------------------------------------------
    # Fetch raw
    # ------------------------------------------------------------------
    raw_skipped = False
    if args.skip_existing_raw and s3_object_exists(bucket, r_key, aws_region):
        logger.info("Raw already exists -- skipping HTTP fetch: %s", r_key)
        raw_skipped = True
    else:
        logger.info("Fetching %s ...", _IODMI_URL)
        iodmi_bytes = fetch_with_retry(_IODMI_URL)

        preamble = iodmi_bytes[:_PREAMBLE_SNIFF_BYTES].decode("utf-8", errors="replace")
        missing = [tok for tok in _EXPECTED_TOKENS if tok not in preamble]
        if missing:
            logger.error(
                "Response from %s does not look like the CPC IODMI file "
                "(missing preamble token(s) %s). Got: %r",
                _IODMI_URL, missing, iodmi_bytes[:120],
            )
            sys.exit(1)

        # Truthful provenance stamp for the capture: what was fetched, from where, when,
        # and the digest of the exact bytes written to the raw prefix.
        logger.info(
            "provenance  url=%s  fetched_at_utc=%s  bytes=%d  sha256=%s",
            _IODMI_URL,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            len(iodmi_bytes),
            hashlib.sha256(iodmi_bytes).hexdigest(),
        )
        upload_bytes_to_s3(iodmi_bytes, bucket, r_key, aws_region)
        logger.info("Raw written -> s3://%s/%s", bucket, r_key)

    # ------------------------------------------------------------------
    # Bronze transform
    # ------------------------------------------------------------------
    if raw_skipped and not args.force_bronze:
        logger.info("Raw was skipped and --force-bronze not set -- skipping bronze write")
        return

    if raw_skipped:
        import boto3
        from leviathan.storage.s3 import _BOTO_RETRY_CONFIG, s3_download_with_retry
        s3_client = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
        iodmi_bytes = s3_download_with_retry(bucket, r_key, s3_client)
        logger.info("Re-read raw from S3 for bronze parse (%d bytes)", len(iodmi_bytes))

    df = extract_cpc_iodmi_bronze(iodmi_bytes)

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    _write_parquet(buf.getvalue(), bucket, b_key, aws_region)
    logger.info(
        "Bronze written -> s3://%s/%s  rows=%d  years=%d-%d",
        bucket, b_key, len(df), int(df["year"].min()), int(df["year"].max()),
    )


if __name__ == "__main__":
    main()
