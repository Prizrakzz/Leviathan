"""AWS Batch Fargate task: silver_futures_eod -> gold_board_crush (flat, daily, $/bushel).

Reads the three CBOT soy legs' per-delivery-month EOD parquet DIRECTLY from S3 (the
gold_weather_z / load_pg_numbers no-Athena pattern: the Glue catalog is never touched here),
applies the ONE named front-month roll rule, computes the board crush, and writes a single
flat parquet to ``gold/board_crush/part-000.parquet``.

The compute core lives in ``leviathan.transforms.gold.board_crush`` (pure, unit-tested on
synthetic frames); this file is only the S3 I/O + orchestration shell.

  * silver/futures_eod/leviathan_slug=soybeans_cbot/trade_year=YYYY/*.parquet
  * silver/futures_eod/leviathan_slug=soybean_meal_cbot/trade_year=YYYY/*.parquet
  * silver/futures_eod/leviathan_slug=soybean_oil_cbot/trade_year=YYYY/*.parquet

Only those three prefixes are listed -- the table has 31 slugs and reading the other 28 to
throw them away would be the LIST-storm class this estate already paid $134 to learn about.

The gold table is NON-PROJECTED and NON-PARTITIONED (Glue DDL sql/athena/ddl/gold_board_crush.sql),
so there is no per-partition ADD on refresh and no enumeration surface. DDL registration and a
load_pg_numbers mirror run are the (ORCHESTRATOR-SEQUENCED) cloud steps; this job only writes the
parquet.

WHY IT IS CHEAP: the output is one row per READABLE trading session -- roughly 2,650 rows, a few
hundred KB. The intermediate read is the three legs' full per-delivery-month history (153,806 rows
as of 2026-08-20), which is the real sizing input.

WHY IT IS NOT ~4,000 ROWS: the tape starts 2010-06-06 but GLBX open interest -- the input the ONE
front-month rule reads for these three legs -- starts 2015-11-19, and 47 later sessions are
statistics blackouts or expiring-contract final prints. Those 1,532 dates are REFUSED per date and
printed by name-count below; nothing is filled in for them. See the transform's module docstring for
the measurement.

Usage:
    python jobs/batch/gold_board_crush_task.py
    python jobs/batch/gold_board_crush_task.py --dry-run true
"""
from __future__ import annotations

import argparse
import io
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.transforms.gold.board_crush import (
    CRUSH_LEGS,
    CRUSH_RULE_VERSION,
    INPUT_COLUMNS,
    PHYSICAL_COLUMNS,
    REFUSED_DATES,
    compute_board_crush,
)

logger = get_logger("gold_board_crush")

_SILVER_EOD = "silver/futures_eod"
_GOLD_KEY = "gold/board_crush/part-000.parquet"
_WORKERS = 16


def _leg_prefix(slug: str) -> str:
    return f"{_SILVER_EOD}/leviathan_slug={slug}/"


def _read_leg(bucket: str, slug: str, region: str) -> pd.DataFrame:
    """Every registered trade_year partition for one leg, as one frame."""
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
    )

    keys = list_s3_keys(bucket, _leg_prefix(slug), suffix=".parquet", aws_region=region)
    if not keys:
        logger.warning("gold_board_crush: no objects under %s", _leg_prefix(slug))
        return pd.DataFrame(columns=INPUT_COLUMNS)

    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futs = {
            pool.submit(s3_download_with_retry, bucket, k, get_thread_local_s3_client(region)): k
            for k in keys
        }
        for fut in as_completed(futs):
            k = futs[fut]
            try:
                body = fut.result()
            except Exception as exc:  # noqa: BLE001 -- one unreadable object must not lose the leg
                logger.error("gold_board_crush: failed to read %s (%s)", k, exc)
                continue
            df = pq.read_table(io.BytesIO(body)).to_pandas()
            # leviathan_slug is a Hive PARTITION key, so it is in the path and NOT in the
            # file. Restore it from the prefix we asked for -- never infer it from a column
            # that does not exist.
            df["leviathan_slug"] = slug
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=INPUT_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    logger.info("gold_board_crush: leg %s -> %d rows from %d objects", slug, len(out), len(keys))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compute gold_board_crush from the three CBOT soy legs of silver_futures_eod.")
    ap.add_argument("--dry-run", default="false",
                    help="compute and log the shape, write nothing")
    args = ap.parse_args(argv)
    dry = str(args.dry_run).lower() in ("1", "true", "yes")

    load_env()
    bucket = get_required_env("S3_BUCKET")
    region = get_required_env("AWS_REGION")

    legs = [_read_leg(bucket, slug, region) for slug in sorted(CRUSH_LEGS.values())]
    eod = pd.concat([f for f in legs if len(f)], ignore_index=True) if any(
        len(f) for f in legs) else pd.DataFrame(columns=INPUT_COLUMNS)

    missing_legs = sorted(set(CRUSH_LEGS.values()) - set(eod.get("leviathan_slug", pd.Series(
        dtype="object")).unique()))
    if missing_legs:
        # FAIL CLOSED. A crush is a three-leg object; publishing a table built from
        # whatever legs happened to land would be a number nobody could audit, and an
        # empty overwrite would erase a good prior publish.
        logger.error(
            "gold_board_crush: legs %s have NO rows in silver_futures_eod -- refusing to "
            "publish a partial crush. Land the missing leg and re-run.", missing_legs)
        return 2

    gold = compute_board_crush(eod)

    # THE PER-DATE REFUSAL, PRINTED BEFORE THE ZERO-ROW FENCE. A run that emits
    # nothing must say WHICH dates it could not read and WHY -- the first fire of
    # this job refused all 153,806 rows and the log could only say "zero rows",
    # because the input contract was asked once over the whole history instead of
    # per session. This block is that answer, and it prints on every outcome.
    ledger = gold.attrs.get(REFUSED_DATES)
    if ledger is not None:
        logger.info("gold_board_crush: %s", ledger.render())
        for role, days in sorted(ledger.refused_by_role.items()):
            if days:
                logger.info("gold_board_crush: leg %s refused %d date(s), %s .. %s",
                            role, len(days), days[0], days[-1])

    if gold.empty:
        logger.error("gold_board_crush: computed ZERO rows from %d input rows -- refusing to "
                     "overwrite the published table with an empty one", len(eod))
        return 3

    logger.info("gold_board_crush: %d rows, %s .. %s, rule=%s",
                len(gold), gold["trade_date"].iloc[0], gold["trade_date"].iloc[-1],
                CRUSH_RULE_VERSION)

    if dry:
        logger.info("gold_board_crush: --dry-run, nothing written")
        return 0

    from leviathan.storage.s3 import get_thread_local_s3_client

    # The ledger is a RUN RECORD, not a column and not schema metadata: it belongs
    # in this job's log, where an operator reads it, and NOT in the published
    # parquet (pyarrow would try to JSON it into the pandas metadata block, warn,
    # and either bloat the file or silently drop it). Cleared explicitly so the
    # written object is exactly PHYSICAL_COLUMNS and nothing else.
    body = gold[PHYSICAL_COLUMNS].copy()
    body.attrs = {}

    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(body, preserve_index=False),
                   buf, compression="snappy")
    get_thread_local_s3_client(region).put_object(
        Bucket=bucket, Key=_GOLD_KEY, Body=buf.getvalue(),
        ContentType="application/octet-stream")
    logger.info("gold_board_crush: wrote s3://%s/%s (%d bytes)",
                bucket, _GOLD_KEY, buf.tell())
    return 0


if __name__ == "__main__":
    sys.exit(main())
