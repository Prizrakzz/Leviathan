"""Glue Python Shell job: raw → bronze for USDA FAS ESR data.

Processes ALL (commodity_code, market_year) pairs in a single job run.
This is deliberately a single-invocation design — running one Glue job per
pair would incur 360 cold-start billing charges (~$15) for the full backfill
versus ~$0.44 for one job.  See plan for cost analysis.

THE VINTAGE LAW (lane C re-review NEW-2, 2026-09-04)
----------------------------------------------------
A bronze partition's ``as_of`` comes from the RAW KEY, or from the raw object's
``raw_meta`` sidecar -- NEVER from today's date.  This job used to break that law
in ``backfill`` mode: it paired every UNDATED raw backfill key with
``--ingest_date`` (the run's own date) and wrote
``bronze_esr_key(code, year, <that date>)`` into the SAME bronze prefix
``jobs/batch/esr_task.py`` writes.  MEASURED 2026-09-04: 8,474 of the 8,920 ESR
bronze objects (95.0%) are fabricated vintages minted exactly that way.  A Glue
Python Shell job has no route to a ``raw_meta`` sidecar here, so backfill mode
now REFUSES by name and points at the writer that can date the key.
``--ingest_date`` stays what its name says: the INGEST date, never a vintage.

Modes
-----
backfill
    REFUSED -- see THE VINTAGE LAW above.  Use
    ``jobs/batch/esr_task.py --include-backfill [--backfill-as-of YYYYMMDD]``
    instead: it resolves each undated key's as_of from an explicit operator date
    or the sidecar's ``download_timestamp``, and refuses a key it cannot date.
    This is still the DEFAULT mode on purpose: a no-flag fire must REFUSE, not
    silently do the wrong thing.

weekly
    Iterates commodity_codes × [current_year, current_year+1].  Reads each
    raw weekly key (identified by as_of) from S3, transforms, uploads.
    Called from the Airflow esr_weekly_ingest DAG after fetch_all_snapshots.

Required args:
  --bucket        S3 bucket name
  --aws_region    e.g. us-east-1
  --ingest_date   YYYY-MM-DD (the INGEST date ONLY -- it is NEVER a bronze as_of
                  vintage; see THE VINTAGE LAW above)

Optional args:
  --mode            backfill|weekly  (default: backfill, which now REFUSES)
  --commodity_codes comma-separated ESR codes  (default: all 44 measured source codes)
  --start_year      first marketing year for backfill  (default: 1990)
  --end_year        last marketing year for backfill   (default: current year)
  --as_of           YYYYMMDD snapshot date for weekly  (default: today)
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

from awsglue.utils import getResolvedOptions
from bootstrap import run_bootstrap

run_bootstrap()

import boto3
from botocore.config import Config

from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_esr_key, raw_esr_weekly_key
from leviathan.storage.s3 import upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.usda_esr import transform_esr_json_to_bronze

logger = get_logger(__name__)

_RETRY_CFG = Config(retries={"max_attempts": 10, "mode": "adaptive"})

# The measured 44-code ESR universe (GET /api/esr/commodities, 2026-08-20).
# THIS IS A LITERAL ON PURPOSE: a Glue Python Shell job runs standalone off the
# bootstrapped wheel and cannot import `jobs.ingest.fetch_usda_esr`, so the list
# is mirrored rather than shared.  A unit test pins it EQUAL to the fetcher's
# _TARGET_COMMODITY_CODES (tests/unit/test_fetch_usda_esr_universe.py), so the
# mirror cannot drift the way the legacy 10-code copy did.
_DEFAULT_COMMODITY_CODES = [
    101, 102, 103, 104, 105, 106, 107, 201,
    301, 401, 501, 601, 701, 801, 901, 902,
    1001, 1101, 1110,
    1201, 1202, 1203, 1301, 1401, 1402, 1403, 1404,
    1498, 1499, 1501, 1502, 1503, 1504, 1505,
    1601, 1602, 1603, 1604, 1605, 1606, 1607, 1608,
    1701, 1702,
]
_TMP = Path("/tmp/esr_bronze")

# THE VINTAGE LAW's refusal, named so a Glue log line says WHICH law stopped the run and
# WHICH writer to use instead.  Deliberately a STRING and not a collection: this file sits
# inside the F091 lint's SCAN_ROOTS and a module-level collection would move the raw-literal
# census (PIN_RAW_LITERALS) in a shared tree.
_BACKFILL_REFUSAL = (
    "REFUSING (ESR VINTAGE LAW): this Glue writer cannot re-bronze the UNDATED backfill "
    "keys. It has no route to a raw_meta sidecar, so it used to stamp every undated "
    "payload with --ingest_date -- the run's own date -- minting a point-in-time vintage "
    "that never existed. MEASURED 2026-09-04: 8,474 of 8,920 ESR bronze objects (95.0%) "
    "were minted that way. Use the law-abiding writer instead: jobs/batch/esr_task.py "
    "--include-backfill [--backfill-as-of YYYYMMDD], which resolves as_of from the key's "
    "own as_of= segment, an explicit operator date, or the sidecar's download_timestamp, "
    "and REFUSES a key it cannot date. This job's WEEKLY mode is unaffected: there the "
    "as_of is the raw key's own segment."
)

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

REQUIRED_ARGS = ["bucket", "aws_region", "ingest_date"]
OPTIONAL_ARGS = ["mode", "commodity_codes", "start_year", "end_year", "as_of"]

_raw_args = getResolvedOptions(sys.argv, REQUIRED_ARGS)

# getResolvedOptions does not support optional args — parse them manually.
_argv = sys.argv[1:]


def _get_optional(name: str, default: str) -> str:
    flag = f"--{name}"
    try:
        idx = _argv.index(flag)
        return _argv[idx + 1]
    except (ValueError, IndexError):
        return default


today = datetime.date.today()

BUCKET:     str = _raw_args["bucket"]
AWS_REGION: str = _raw_args["aws_region"]
INGEST_DATE: str = _raw_args["ingest_date"]  # YYYY-MM-DD

MODE:       str = _get_optional("mode", "backfill")
AS_OF:      str = _get_optional("as_of", today.strftime("%Y%m%d"))
START_YEAR: int = int(_get_optional("start_year", "1990"))
END_YEAR:   int = int(_get_optional("end_year", str(today.year)))

_codes_raw = _get_optional("commodity_codes", "")
COMMODITY_CODES: list[int] = (
    [int(c.strip()) for c in _codes_raw.split(",") if c.strip()]
    if _codes_raw
    else _DEFAULT_COMMODITY_CODES
)


# ---------------------------------------------------------------------------
# Marketing year helper (mirrors fetch_usda_esr.py)
# ---------------------------------------------------------------------------

_WHEAT_CODES = frozenset({101, 102, 103, 104, 105, 106, 107, 201})
# D-EC 2026-08-20: the phantom mirror is gone.  This used to be one
# _COTTON_RICE_CODES = {1201, 1202, 1203, 1301, 1302, 3202} -- 1302 and 3202 do
# NOT exist in the source's 44-code universe, and every real upland cotton code
# (1401-1404) and every rice code was missing, so the Aug 1 marketing year was
# applied to two phantoms and withheld from thirteen real codes.  These two sets
# are the fetcher's, code for code, and a unit test pins all three copies equal.
_COTTON_CODES = frozenset({1201, 1202, 1203, 1301, 1401, 1402, 1403, 1404})
_RICE_CODES = frozenset({1498, 1499, 1501, 1502, 1503, 1504, 1505})


def _marketing_year_start_month(commodity_code: int) -> int:
    if commodity_code in _WHEAT_CODES:
        return 6
    if commodity_code in _COTTON_CODES or commodity_code in _RICE_CODES:
        return 8
    return 9


def _current_marketing_year(commodity_code: int, reference: datetime.date) -> int:
    start_month = _marketing_year_start_month(commodity_code)
    if reference.month >= start_month:
        return reference.year
    return reference.year - 1


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def _process_pair(
    s3_client,
    commodity_code: int,
    market_year: int,
    raw_key: str,
    as_of_date: str,
) -> bool:
    """Download raw JSON, transform, write Parquet, upload to bronze.

    Returns True on success, False if the raw key does not exist (skip).
    Raises on any other error so the caller can accumulate failures.
    """
    # Check raw key exists
    try:
        s3_client.head_object(Bucket=BUCKET, Key=raw_key)
    except s3_client.exceptions.ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 404:
            logger.debug("  [skip] raw key not found: %s", raw_key)
            return False
        raise

    # Download raw JSON to memory (files are small — no need for /tmp)
    response = s3_client.get_object(Bucket=BUCKET, Key=raw_key)
    raw_bytes = response["Body"].read()
    logger.info(
        "  Downloaded %d KB — commodity_code=%d market_year=%d",
        len(raw_bytes) // 1024, commodity_code, market_year,
    )

    # Transform
    df = transform_esr_json_to_bronze(
        raw_bytes=raw_bytes,
        commodity_code=commodity_code,
        market_year=market_year,
        as_of_date=as_of_date,
        ingest_date=INGEST_DATE,
    )

    # Write Parquet locally then upload (avoids holding the full DataFrame
    # and BytesIO buffer in memory simultaneously for large files)
    _TMP.mkdir(parents=True, exist_ok=True)
    local_path = _TMP / f"esr_{commodity_code}_{market_year}.parquet"
    df.to_parquet(local_path, index=False, engine="pyarrow", compression="snappy")

    # Upload to bronze
    b_key = bronze_esr_key(commodity_code, market_year, as_of_date)
    with local_path.open("rb") as fh:
        upload_bytes_to_s3(fh.read(), BUCKET, b_key, AWS_REGION)
    logger.info("  → s3://%s/%s", BUCKET, b_key)

    local_path.unlink(missing_ok=True)
    return True


def main() -> None:
    if MODE == "backfill":
        # THE VINTAGE LAW, refused BEFORE anything is opened: no client, no LIST, no GET.
        # START_YEAR / END_YEAR still parse, so the refusal reads the same for every
        # invocation shape; there is deliberately no path past this line.
        raise RuntimeError(_BACKFILL_REFUSAL)

    s3 = boto3.client("s3", region_name=AWS_REGION, config=_RETRY_CFG)

    # WEEKLY: the as_of is READ OFF THE RAW KEY this run opens -- raw_esr_weekly_key embeds it,
    # and the same value is what bronze_esr_key writes -- so the bronze partition's vintage is
    # the raw key's own vintage (provenance ``raw_key`` in jobs/batch/esr_task.py's terms).
    # A missing key is skipped by _process_pair, never invented.
    reference = datetime.date(int(AS_OF[:4]), int(AS_OF[4:6]), int(AS_OF[6:8]))
    pairs: list[tuple[int, int, str, str]] = []
    for code in COMMODITY_CODES:
        cur = _current_marketing_year(code, reference)
        for year in [cur, cur + 1]:
            raw_key = raw_esr_weekly_key(code, year, AS_OF)
            pairs.append((code, year, raw_key, AS_OF))

    logger.info(
        "raw→bronze ESR: mode=%s  pairs=%d  commodity_codes=%s",
        MODE, len(pairs), COMMODITY_CODES,
    )

    success = skipped = failed = 0

    for commodity_code, market_year, raw_key, as_of_date in pairs:
        try:
            processed = _process_pair(s3, commodity_code, market_year, raw_key, as_of_date)
            if processed:
                success += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "  FAILED commodity_code=%d market_year=%d — %s",
                commodity_code, market_year, exc,
            )
            failed += 1

    # Clean up /tmp
    import shutil
    shutil.rmtree(_TMP, ignore_errors=True)

    logger.info(
        "raw→bronze ESR complete. success=%d  skipped=%d  failed=%d",
        success, skipped, failed,
    )

    if failed:
        raise RuntimeError(
            f"{failed} pair(s) failed during raw→bronze ESR transform — see log above."
        )


if __name__ == "__main__":
    main()
