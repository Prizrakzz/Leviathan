"""AWS Batch Fargate task: silver weather -> gold_weather_z (tall, monthly, PIT-safe z-anomalies).

Reads the silver weather LONG parquet DIRECTLY from S3 (the load_pg_numbers no-Athena pattern: the Glue
catalog is never touched here), pruned by commodity, and writes one tall gold parquet per commodity to
gold/weather_z/{slug}.parquet. The compute core lives in leviathan.transforms.gold.weather_z
(pure, unit-tested on synthetic frames); this file is only the S3 I/O + orchestration shell.

  * nasa_power (silver/weather/source=nasa_power/commodity={slug}/...): tmax/tmin -> heat/gdd/tmax/frost.
  * chirps     (silver/weather/source=chirps/commodity={slug}/...):     precip    -> drought.

The gold table is NON-PROJECTED and NON-PARTITIONED (Glue DDL sql/athena/ddl/gold_weather_z.sql), so there
is no per-partition ADD on refresh and no LIST-storm enumeration surface -- the DDL registration + a
load_pg_numbers mirror run are the (USER-GATED) cloud steps; this job only writes the parquet.

WARNING (D-W4 sizing risk): the INTERMEDIATE read of raw daily weather is heavy (country x region x day x
years per commodity). The gold OUTPUT is tiny (region x year_month x few metrics), but size the
Fargate/Batch job for the transform, not the output. Processed one commodity at a time so memory is bounded.

Usage:
    python jobs/batch/gold_weather_z_task.py --commodity corn_cbot
    python jobs/batch/gold_weather_z_task.py --commodity all --force-overwrite true
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import pyarrow.parquet as pq

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.gold.weather_z import (
    _PRECIP,
    _TMAX,
    _TMIN,
    compute_weather_z,
    metric_tip_ym,
    months_behind,
)

logger = get_logger("gold_weather_z")

_SILVER_WEATHER = "silver/weather"
_WORKERS = 32

# The silver weather parquet is WIDE (one row per day; temperature_2m_max_c etc. as columns), but the
# compute core consumes the melted LONG shape [country, region, year, month, day, variable, value]
# (weather_z._slice keys on the `variable` column). Melt exactly the variables the core reads -- imported
# from the core so the two can never drift. This seam caused the 2026-07-12 run-1 silent no-op (31/31
# commodities "0 gold rows": every wide frame failed the variable-column guard, misread as thin history).
_MELT_VARS = (_TMAX, _TMIN, _PRECIP)
_MELT_IDS = ["country", "region", "year", "month", "day"]


def _to_long(frame: pd.DataFrame) -> pd.DataFrame | None:
    """Normalize a silver frame to the core's long shape [ids.., variable, value]; None when impossible.

    The two silver weather sources ship DIFFERENT shapes (probed 2026-07-12): nasa_power is WIDE (one
    column per variable, e.g. temperature_2m_max_c) and MUST be melted; chirps is ALREADY LONG
    (variable='precipitation_mm' + value). Run 2's drought blackout (34 DARK census legs, zero drought_z
    gold rows) was this function refusing the long chirps frame because it demanded wide value_vars."""
    ids = [c for c in _MELT_IDS if c in frame.columns]
    if len(ids) != len(_MELT_IDS):
        logger.error("unexpected silver schema: ids=%s cols=%s", ids, sorted(frame.columns)[:20])
        return None
    if "variable" in frame.columns and "value" in frame.columns:     # already long (chirps)
        out = frame[ids + ["variable", "value"]]
        return out if not out.empty else None
    value_vars = [c for c in _MELT_VARS if c in frame.columns]       # wide (nasa_power) -> melt
    if not value_vars:
        logger.error("unexpected silver schema: no long columns and no known wide vars; cols=%s",
                     sorted(frame.columns)[:20])
        return None
    out = frame.melt(id_vars=ids, value_vars=value_vars, var_name="variable", value_name="value")
    return out if not out.empty else None


def _source_prefix(source: str, commodity: str) -> str:
    return f"{_SILVER_WEATHER}/source={source}/commodity={commodity}/"


def _gold_key(commodity: str) -> str:
    return f"gold/weather_z/{commodity}.parquet"


def _discover_commodities(bucket: str, aws_region: str) -> list[str]:
    """Distinct commodity slugs present under silver/weather/source=nasa_power/."""
    keys = list_s3_keys(bucket, f"{_SILVER_WEATHER}/source=nasa_power/", suffix=".parquet",
                        aws_region=aws_region)
    slugs = {parse_hive_key(k, "commodity") for k in keys}
    return sorted(s for s in slugs if s)


def _read_long(bucket: str, source: str, commodity: str, aws_region: str) -> pd.DataFrame | None:
    """Read + concat every silver parquet under one (source, commodity) prefix into a long frame."""
    keys = list_s3_keys(bucket, _source_prefix(source, commodity), suffix=".parquet",
                        aws_region=aws_region)
    if not keys:
        logger.info("no %s silver for commodity=%s", source, commodity)
        return None

    def _one(key: str) -> pd.DataFrame | None:
        try:
            s3 = get_thread_local_s3_client(aws_region)
            data = s3_download_with_retry(bucket, key, s3)
            return pq.read_table(io.BytesIO(data)).to_pandas()
        except Exception as exc:  # noqa: BLE001 — per-file failures logged; loop continues
            logger.error("failed to read %s: %s", key, exc)
            return None

    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for fut in as_completed({pool.submit(_one, k) for k in keys}):
            df = fut.result()
            if df is not None and not df.empty:
                frames.append(df)
    if not frames:
        return None
    return _to_long(pd.concat(frames, ignore_index=True))


# ---------------------------------------------------------------------------
# THE FRESHNESS TRIPWIRE (2026-09-11) -- a report and a counter, never a behaviour change.
#
# WHAT IT EXISTS FOR. On 2026-09-11 this job rewrote gold/weather_z/corn_cbot.parquet at 09:19:50Z and
# every one of its five metrics tipped at data month 2026-07 -- 42 days behind, on a table the numbers
# registry SERVES (registry.py:591) and the state board reads (state/lint.py:83). Nothing anywhere
# said so: the only freshness clock in the estate (silver/freshness.py:136 ``newest_last_modified``)
# measures S3 OBJECT MTIME, and the producers rewrite the object daily, so FreshnessLagDays read 0 on
# a dead leg. A banked board block (data/board_census/2026-09-07/blocks/corn_cbot__max__d2.md:28,31)
# printed "GOLD WEATHER Z for 2026-07 ... rising over the last month" beside COT at 2026-09-01.
#
# THE DENOMINATOR IS THE CARD'S OWN PROMISE, not a new constant. ``_ym_lagged_asof_ym`` is the shipped
# arithmetic the board's own reads use; reusing it means this tripwire can never disagree with the
# guard that admits the month. Its input, ``ym_publication_lag_days``, is declared as 7 on the card
# with the card's own note that the number is UNVERIFIED -- and the measurement below is what refutes
# it. Correcting that declaration is a CONFIG change outside this lane; until it lands, this counter
# reports against the number the serving stack actually uses, which is the honest thing to report.
#
# IT CAN NEVER CHANGE THE JOB'S EXIT CODE. The whole body is wrapped, boto3 is imported inside, and a
# failure prints one line and returns -- the ``silver_rebuild_gate._emit_gate_metrics`` precedent
# ("a metric emitter that can kill the gate is worse than no metric").
# ---------------------------------------------------------------------------
_TIP_METRIC_NAMESPACE = "Leviathan/Silver"
_TIP_YM_METRIC = "WeatherZTipYm"
_TIP_BEHIND_METRIC = "WeatherZMonthsBehind"


def _claimed_ym() -> int | None:
    """The newest data month gold_weather_z's OWN card says is knowable today.

    Reads ``ym_publication_lag_days`` off the numbers registry and runs the serving arithmetic
    (``numbers.query._ym_lagged_asof_ym``) over it. The underscore is deliberate: that private function
    IS the board's arithmetic, and restating it here would create a second calendar opinion that could
    drift from the one the as-of guard applies. Imported lazily so this producer keeps no import-time
    dependency on the graphrag serving stack.

    None means the card is PRESENT and declares no lag. It RAISES -- it does not return None -- when
    the card cannot be read at all, and that is not hypothetical: ``NumbersRegistry.get``
    (numbers/registry.py:403-406) raises ``KeyError`` on an unknown table, and a table is unknown
    whenever ``GRAPHRAG_NUMBERS_DISABLE=gold_weather_z`` is set (the documented single-table rollback
    idiom, registry.py:621 ``_disabled_tables()``) or whenever ``configs/graphrag`` is simply not baked
    into the image this jobdef runs on (it rides the EMBEDDER image, rev 8 =
    leviathan-dev-leviathan-embedder@sha256:78264c51bc2a). The CALLER owns that failure, in its own
    try, so a card-side fault cannot take the card-INDEPENDENT tip measurement down with it."""
    from datetime import datetime, timezone

    from leviathan.graphrag.numbers.query import _ym_lagged_asof_ym
    from leviathan.graphrag.numbers.registry import load_registry

    ts = load_registry().get("gold_weather_z")
    lag = getattr(ts, "ym_publication_lag_days", None)
    if not lag:
        return None
    # UTC, not ``date.today()``: this container runs UTC and the gate's own freshness clock
    # (``silver_rebuild_gate._freshness_clock``) is UTC, so a local-time read would let the producer's
    # counter and the gate's stage disagree by a whole MONTH for a few hours around a month boundary
    # when run from a machine east of UTC (the owner's box is UTC+3).
    return _ym_lagged_asof_ym(datetime.now(timezone.utc).date().isoformat(), lag)


def _emit_freshness_tripwire(commodity: str, gold: pd.DataFrame) -> None:
    """Log + publish the per-metric data-month tip and its distance from the card's promise.

    ZERO EXTRA I/O: the finished frame is already in hand at the call site. NEVER RAISES.

    TWO TRIES, NOT ONE, AND THAT IS THE POINT. ``WeatherZTipYm`` -- the data month actually present --
    does not depend on the numbers card at ALL, while ``_claimed_ym()`` reads a registry that can be
    absent for ordinary operational reasons (see its docstring: a single-table disable, or an image
    without configs/graphrag baked in). Under one shared try, MEASURED, a card-side ``KeyError`` left
    put_metric_data calls = 0 and datums = 0 -- the whole tripwire silenced by the one half of it that
    was never about the card. So the card read is fenced on its own and its failure only makes
    ``months_behind`` ABSENT; the tip still ships."""
    try:
        tips = metric_tip_ym(gold)
        if not tips:
            return
        try:
            claimed = _claimed_ym()
        except Exception as exc:  # noqa: BLE001 -- an unreadable card costs the DENOMINATOR, not the tip
            claimed = None
            logger.warning(
                "freshness tripwire: the gold_weather_z card is unreadable (%s: %s) -- publishing the "
                "data-month tip WITHOUT months_behind; the tip does not depend on the card",
                type(exc).__name__, str(exc)[:200],
            )
        behind = {m: months_behind(claimed, ym) for m, ym in tips.items()}
        logger.info(
            "freshness  commodity=%s  claimed_ym=%s  tips=%s  months_behind=%s",
            commodity, claimed if claimed is not None else "undeclared",
            {m: tips[m] for m in sorted(tips)},
            {m: behind[m] for m in sorted(behind)},
        )
        from datetime import datetime, timezone

        import boto3
        now = datetime.now(timezone.utc)
        data = []
        for metric in sorted(tips):
            dims = [{"Name": "Commodity", "Value": commodity}, {"Name": "Metric", "Value": metric}]
            data.append({"MetricName": _TIP_YM_METRIC, "Timestamp": now, "Unit": "None",
                         "Value": float(tips[metric]), "Dimensions": dims})
            if behind[metric] is not None:
                data.append({"MetricName": _TIP_BEHIND_METRIC, "Timestamp": now, "Unit": "Count",
                             "Value": float(behind[metric]), "Dimensions": dims})
        # put_metric_data caps at 1000 datums per call; five metrics x 2 per commodity can never
        # approach it, and the call is made once per commodity anyway.
        boto3.client("cloudwatch").put_metric_data(Namespace=_TIP_METRIC_NAMESPACE, MetricData=data)
    except Exception as exc:  # noqa: BLE001 -- telemetry must never change a producer's verdict
        logger.warning(
            "freshness tripwire could not be emitted for commodity=%s (%s: %s) -- the gold write "
            "above stands and is unaffected",
            commodity, type(exc).__name__, str(exc)[:200],
        )


def _process_commodity(bucket: str, commodity: str, aws_region: str, force_overwrite: bool) -> int:
    s3 = get_thread_local_s3_client(aws_region)
    gold_key = _gold_key(commodity)
    if not force_overwrite:
        try:
            s3.head_object(Bucket=bucket, Key=gold_key)
            logger.info("gold already exists, skipping: %s", gold_key)
            return 0
        except Exception:  # noqa: BLE001 — 404 is expected for a new commodity
            pass

    nasa = _read_long(bucket, "nasa_power", commodity, aws_region)
    chirps = _read_long(bucket, "chirps", commodity, aws_region)
    if nasa is None and chirps is None:
        logger.warning("no silver weather for commodity=%s -- nothing to compute", commodity)
        return 0

    gold = compute_weather_z(commodity, nasa_power=nasa, chirps=chirps)
    if gold.empty:
        logger.warning("commodity=%s produced 0 gold rows (thin history?)", commodity)
        return 0

    buf = io.BytesIO()
    gold.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(Bucket=bucket, Key=gold_key, Body=buf.getvalue())
    logger.info("wrote gold  commodity=%s  rows=%d  metrics=%s  key=%s",
                commodity, len(gold), sorted(gold["metric"].unique()), gold_key)
    _emit_freshness_tripwire(commodity, gold)
    return len(gold)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    load_env()

    parser = argparse.ArgumentParser(description="silver weather -> gold_weather_z")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--commodity", default="all",
                        help="comma-separated slugs, or 'all' to discover from silver/weather")
    parser.add_argument("--force-overwrite", default="false", dest="force_overwrite")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    force = str(args.force_overwrite).lower() == "true"

    if args.commodity.strip().lower() == "all":
        commodities = _discover_commodities(bucket, aws_region)
    else:
        commodities = [c.strip() for c in args.commodity.split(",") if c.strip()]
    logger.info("gold_weather_z: %d commodities", len(commodities))

    total, failures = 0, []
    for commodity in commodities:
        try:
            total += _process_commodity(bucket, commodity, aws_region, force)
        except Exception as exc:  # noqa: BLE001 — one commodity's failure must not kill the rest
            logger.error("[%s] FAILED: %s: %s", commodity, type(exc).__name__, str(exc)[:300])
            failures.append(commodity)
    logger.info("DONE: %d gold rows across %d commodities%s", total, len(commodities),
                f"  FAILURES: {failures}" if failures else "")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
