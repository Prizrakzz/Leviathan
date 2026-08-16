"""AWS Batch entrypoint: Frankfurter FX -> raw + bronze + silver (SILVER-F040).

Builds the ``silver_fred_fx`` table (a documented legacy misnomer -- the true source
is Frankfurter, see ADR-003) from scratch: fetch the base=USD time series, parse a
long bronze, derive the wide silver (90-day calendar-lag percent changes), and publish
the silver through the shadow-first controlled publisher with an EXPLICIT registry-derived
arrow schema (INV-2/INV-6). Default ``--publish-mode`` is dry-run (nothing written);
canonical requires a verified signed approval.

S3 layout (truthful ``source=frankfurter`` prefix for raw/bronze; canonical silver keeps
the legacy ``silver/fred_fx/`` location per ADR-003):
    raw:    raw/fx/source=frankfurter/timeseries.json
    bronze: bronze/fx/source=frankfurter/part-000.parquet
    silver: silver/fred_fx/part-000.parquet

Usage:
    python jobs/batch/frankfurter_fx_task.py --dry-run
    python jobs/batch/frankfurter_fx_task.py --publish-mode shadow
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from datetime import date
from typing import Callable

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import silver_fred_fx_key
from leviathan.storage.s3 import get_thread_local_s3_client, upload_bytes_to_s3
from leviathan.transforms.bronze_to_silver.frankfurter_fx import build_fx_silver
from leviathan.transforms.raw_to_bronze.frankfurter_fx import SERIES_MAP, extract_fx_bronze
from jobs.batch._sb_producer_publish import publish_flat_silver

logger = get_logger("frankfurter_fx_task")

_API_BASE = "https://api.frankfurter.dev/v1"
_START_DATE = "2004-12-31"          # matches the existing history floor (OP-6)
_TIMEOUT = 60

# D-SG G1-4. frankfurter.dev sits behind Cloudflare and returned 520/522 twice in four days
# (2026-08-08 and 2026-08-11), and each one burned a whole daily fire because the GET below got
# exactly one shot. Three attempts with a 30 s / 120 s pause cost at most 2.5 extra minutes on a
# job whose median run is well under a minute. The house urllib3 adapter
# (jobs/ingest/fetch_sagis_cec.py) is deliberately NOT reused here: its backoff schedule is a
# factor, not a pair of literals, and it differs between urllib3 1.26 and 2.x -- this leg's
# contract is "30 then 120", exactly, and it needs 520/522, which are not standard codes.
_RETRY_SLEEPS = (30, 120)                       # len == tries - 1; 3 tries total
_RETRY_STATUSES = frozenset(range(500, 600))    # ANY 5xx (uncurated by design: the Cloudflare
# 52x family is the measured offender, and a wasted retry on a permanent 501/505 costs 2.5 min
# once -- cheaper than a curated list drifting when the CDN mints a new code)

RAW_KEY = "raw/fx/source=frankfurter/timeseries.json"
BRONZE_KEY = "bronze/fx/source=frankfurter/part-000.parquet"


def _timeseries_url(start: str, end: str) -> str:
    symbols = ",".join(SERIES_MAP.keys())
    return f"{_API_BASE}/{start}..{end}?base=USD&symbols={symbols}"


def _get_with_retry(url: str, *, sleep: Callable[[float], None] = time.sleep) -> requests.Response:
    """GET with a bounded backoff on TRANSPORT and SERVER faults only.

    RETRIES: connection errors, read timeouts, and any 5xx -- which is what a Cloudflare 520/522 in
    front of frankfurter.dev actually is. NEVER RETRIES 4xx: a 400/404 is the vendor telling us the
    request is wrong, and three identical wrong requests are three identical answers plus four
    minutes. The last failure is re-raised unchanged, so the job's exit vocabulary and the existing
    traceback are untouched. ``sleep`` is injected so the tests exercise the schedule without it.
    """
    last: Exception | None = None
    for attempt, sleep_for in enumerate((*_RETRY_SLEEPS, None), start=1):
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            if resp.status_code in _RETRY_STATUSES:
                raise requests.HTTPError(f"{resp.status_code} {resp.reason}", response=resp)
            resp.raise_for_status()          # 4xx -> raises, is NOT retried
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in _RETRY_STATUSES:
                raise
            last = exc
        if sleep_for is None:
            break
        logger.warning("frankfurter attempt %d/%d failed (%s) -- retrying in %ds",
                       attempt, len(_RETRY_SLEEPS) + 1, last, sleep_for)
        sleep(sleep_for)
    raise last  # type: ignore[misc]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="Frankfurter FX -> raw + bronze + silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--start", default=_START_DATE)
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true",
                        help="do not write raw/bronze; the silver publish still honours --publish-mode")
    # --publish-mode is consumed by the publish guard via sys.argv (default dry-run).
    parser.add_argument("--publish-mode", default=None,
                        help="dry-run|shadow|canonical (default dry-run)")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3 = get_thread_local_s3_client(aws_region)

    url = _timeseries_url(args.start, args.end)
    logger.info("Fetching %s", url)
    resp = _get_with_retry(url)
    raw_bytes = resp.content
    logger.info("Downloaded %d bytes", len(raw_bytes))

    if not args.dry_run:
        upload_bytes_to_s3(raw_bytes, bucket, RAW_KEY, aws_region)
        logger.info("Raw written -> %s", RAW_KEY)

    df_bronze = extract_fx_bronze(raw_bytes)
    if not args.dry_run:
        buf = io.BytesIO()
        df_bronze.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3.put_object(Bucket=bucket, Key=BRONZE_KEY, Body=buf.getvalue(),
                      ContentType="application/octet-stream")
        logger.info("Bronze written -> %s  rows=%d", BRONZE_KEY, len(df_bronze))

    df_silver = build_fx_silver(df_bronze)

    manifest = publish_flat_silver(
        table_name="silver_fred_fx",
        df=df_silver,
        job="frankfurter_fx_task",
        canonical_key=silver_fred_fx_key(),
        bucket=bucket,
        s3_client=s3,
        argv=sys.argv,
    )
    logger.info("Silver publish %s  state=%s  rows=%d",
                silver_fred_fx_key(), manifest.state.value, len(df_silver))


if __name__ == "__main__":
    main()
