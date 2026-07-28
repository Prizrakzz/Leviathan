#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W2 -- ``silver_futures_eod`` producer task (the Databento leg).

THE PUBLISH CONTRACT, BY MODE
-----------------------------
``--publish-mode dry-run`` (the DEFAULT)
    Reads raw from S3, builds bronze + silver in memory, runs the row validator and the partition
    plan, writes NOTHING. No Glue client, and ``s3_client`` may be absent for the publish leg.
``--publish-mode shadow``
    Stages every partition object under the shadow prefix. A live S3 client is required
    (``build_partitioned_publish`` refuses a write mode with ``s3_client=None``). Nothing canonical
    is touched and NO Glue partition is registered.
``--publish-mode canonical``
    Write-verify-REGISTER through the F013 ``PartitionPublisher``: a live S3 client AND a live Glue
    client, an STS identity matching ``PROD_ENVIRONMENT``, a signed approval
    (``LEVIATHAN_APPROVAL_MODE=kms`` + ``LEVIATHAN_KMS_KEY_ID``, or the HMAC pair) and
    ``LEVIATHAN_READINESS`` absent. A partition already registered at a DIFFERENT location is a
    hard error unless a ``RepairAuthorization`` names that exact value tuple.

NEVER MSCK, NEVER PROJECTION. The registry pins ``partition_mode: registered`` +
``projection: forbidden``, and ``build_partitioned_publish`` refuses anything else.

THE ROW VALIDATOR IS MANDATORY
------------------------------
``futures_eod_contracts.lint_frame`` is passed as ``row_validator=`` on EVERY publish. It is the
only place the conditional invariants live -- ``contract_month IS NULL`` iff
``instrument_kind == 'cash_index'``, and per-slug ``unit``/``currency``/``settle_kind``/``source``
equality against ``CONTRACT_MAP``. The F010 contract can only express UNCONDITIONAL nullability, so
without this a producer that dropped the delivery month would write N rows collapsing to ONE
natural key and ``duplicate_check: full`` could not see it (SQL treats each NULL as distinct).

MODES OF OPERATION
------------------
``--mode backfill``  one or more ``(root, year)`` units read from the raw prefix. A backfill unit
    OWNS its whole ``(leviathan_slug, trade_year)`` partition, so it may stage it outright.
``--mode incremental`` D5's nightly: the current-year prefix, ``--since`` bounded. It owns only
    ``--lookback-days`` of the year but stages the WHOLE ``trade_year`` object (one fixed key per
    partition, no append), so it FIRST unions with the existing canonical partitions --
    :func:`merge_with_canonical`. Without that union the nightly run silently truncates the
    current-year partition of every slug to five days, and nothing in the chain would notice:
    vintage_retention is latest-only, ``silver_rebuild_gate`` is a consumer-sync dispatcher that
    checks no row counts, and the standalone W2 gate script is never invoked by the DAG.

TWO UNIQUENESS ASSERTIONS RUN BEFORE ANY STAGING
------------------------------------------------
:func:`assert_no_duplicates` hard-fails on a duplicate natural key AND on a duplicate
``(trade_date, raw_symbol)`` -- F2's precondition, on the automated path. ``ICE_BAR_RULE`` is still
PROVISIONAL pending probe P3, ``build_partitioned_publish`` performs no duplicate check, and gate 1
lives in a script no chain phase runs. Correspondingly the DAG descriptor is
``promote_mode: stop_and_notify``: the machine publishes SHADOW only, and a human promotes after P3
and the eight gates.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.silver import futures_eod_contracts as FC  # noqa: E402
from leviathan.silver.flat_producer import authorize_for_contract  # noqa: E402
from leviathan.silver.partitioned_producer import build_partitioned_publish  # noqa: E402
from leviathan.silver.registry import load_registry  # noqa: E402
from leviathan.storage.paths import (  # noqa: E402
    databento_payload_filename,
    databento_payload_prefix,
    databento_symbology_filename,
    raw_databento_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client  # noqa: E402
from leviathan.transforms.bronze_to_silver.databento_eod import (  # noqa: E402
    SILVER_COLUMNS,
    build_databento_eod_silver,
)
from leviathan.transforms.raw_to_bronze.databento_eod import (  # noqa: E402
    DATASET_SLUGS,
    GLBX,
    ICE_BAR_RULE,
    ROOT_MAP,
    apply_ice_settle,
    build_ohlcv_bronze,
    build_statistics_bronze,
    decode_dbn,
    glbx_settle_coverage,
    join_glbx_statistics,
    probe_ice_bar_rule,
    root_years,
    statistics_join_diagnostics,
    symbology_from_artifact,
)

logger = get_logger("futures_eod_task")

_TABLE = "silver_futures_eod"
_JOB = "futures_eod_databento"
# The two partition keys, in the contract's declared order (Glue keys positionally).
_PARTITION_COLS = ["leviathan_slug", "trade_year"]
# Sanity floor per (root, year) unit: the thinnest legitimate full year in the plan's table is
# ZR 2019 at 750 bars, and the thinnest legitimate STUB is the ICE 2018 six-session opener at
# 32-66. A unit landing under this is a truncated download, not a thin market.
_MIN_ROWS_PER_UNIT = 25
# The contract's declared natural key. Asserted UNIQUE on the assembled frame before a single byte
# is staged: `duplicate_check` runs downstream of the write, `lint_frame` checks conditional
# nullability and per-slug label coherence only, and `build_partitioned_publish` performs no
# duplicate check at all -- so without this the F2 double bar reaches a registered surface and the
# plan's "no registered-contract surface consumes ICE bars until a (trade_date, raw_symbol)
# uniqueness assertion passes" precondition is enforced nowhere in the automated path.
_NATURAL_KEY = ["leviathan_slug", "contract_month", "trade_date"]
# The F2 key proper. `raw_symbol` is the vendor identity; two rows sharing it on one trade date is
# the ICE double bar surviving the ICE_BAR_RULE dedupe, which is a hard fail and never a dedupe.
_F2_KEY = ["trade_date", "raw_symbol"]


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical target. Module-level seam so tests monkeypatch it
    and unit runs stay AWS-free; an empty identity still fails the guard closed on canonical."""
    from leviathan.common.aws_identity import resolve_caller_identity

    return resolve_caller_identity(aws_region)


def _get(s3_client, bucket: str, key: str) -> Optional[bytes]:
    try:
        return s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception:  # noqa: BLE001 -- a missing raw object is an ordinary "unit not fetched yet"
        return None


def _list_keys(s3_client, bucket: str, prefix: str) -> list[str]:
    """Every key under one raw prefix. ``list_objects_v2`` directly rather than a paginator so a
    test double only has to implement the one method the real client already exposes."""
    keys: list[str] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        try:
            page = s3_client.list_objects_v2(**kwargs)
        except Exception:  # noqa: BLE001 -- an unlistable prefix is an ordinary "nothing there yet"
            return keys
        keys.extend(obj["Key"] for obj in (page.get("Contents") or []))
        token = page.get("NextContinuationToken")
        if not page.get("IsTruncated") or not token:
            return keys


def resolve_payload_key(s3_client, bucket: str, *, dataset: str, root: str, year: int,
                        schema: str, mode: str = "backfill") -> str:
    """The key of the payload to READ for one ``(root, year, schema)``.

    The name is derived by :func:`leviathan.storage.paths.databento_payload_filename`, the SAME
    function the fetch job writes with. In backfill mode that is deterministic. In INCREMENTAL mode
    the fetch job stamps the file with its own as-of date (``ohlcv-1d_ZC_20260728.dbn.zst``) and
    lands it in the same ``year={current}`` prefix, and the fetch and silver phases of one chain can
    straddle UTC midnight -- so the reader LISTS the prefix and takes the NEWEST as-of stamp rather
    than recomputing a date the writer already chose. A hard-coded ``{schema}_{root}_{year}`` here
    is the defect that makes the nightly chain read a stale backfill object, or nothing at all,
    while the session it just paid for never lands."""
    ds = DATASET_SLUGS[dataset]
    backfill = raw_databento_key(ds, root, year, databento_payload_filename(schema, root, year))
    if mode != "incremental":
        return backfill
    token = databento_payload_prefix(schema, root)
    suffix = ".dbn.zst"
    stamped: list[tuple[str, str]] = []
    for key in _list_keys(s3_client, bucket, raw_databento_key(ds, root, year, "")):
        name = key.rsplit("/", 1)[-1]
        if not (name.startswith(token) and name.endswith(suffix)):
            continue
        stem = name[len(token):-len(suffix)]
        if len(stem) == 8 and stem.isdigit():      # YYYYMMDD == an incremental as-of payload
            stamped.append((stem, key))
    if stamped:
        return max(stamped)[1]
    logger.warning("%s %s/%s %s: no as-of stamped incremental payload under the year prefix -- "
                   "falling back to the backfill object", dataset, root, year, schema)
    return backfill


def load_unit_bronze(s3_client, bucket: str, *, dataset: str, root: str, year: int,
                     ice_bar_rule: str = ICE_BAR_RULE,
                     mode: str = "backfill") -> tuple[pd.DataFrame, dict]:
    """Read one ``(dataset, root, year)`` raw unit and return its bronze rows + a stats dict.

    The DECADE ANCHOR is ``year`` -- the raw path segment, never ``datetime.now()``. The symbology
    artifact is read for its recorded ``dropped_count`` (the gate-2 evidence) and, when the payload
    carries no in-band mappings, as the symbology.json the decode needs -- built from the STEP-2
    chunks by :func:`symbology_from_artifact`. Never from ``resolve_step1``: that is
    ``parent -> instrument_id``, and injecting it maps every instrument to the literal ``'ZC.FUT'``
    so the outright filter drops 100% of the purchased bars."""
    ds = DATASET_SLUGS[dataset]
    sym_key = raw_databento_key(ds, root, year, databento_symbology_filename(root, year))
    ohlcv_key = resolve_payload_key(s3_client, bucket, dataset=dataset, root=root, year=year,
                                    schema="ohlcv-1d", mode=mode)
    sym_raw = _get(s3_client, bucket, sym_key)
    artifact = json.loads(sym_raw.decode("utf-8")) if sym_raw else {}
    payload = _get(s3_client, bucket, ohlcv_key)
    if payload is None:
        raise FileNotFoundError(f"no ohlcv-1d payload at s3://{bucket}/{ohlcv_key}")

    symbology = symbology_from_artifact(artifact)
    raw = decode_dbn(payload, schema="ohlcv-1d", symbology_json=symbology)
    bronze, stats = build_ohlcv_bronze(raw, dataset=dataset, root=root, request_year=year,
                                       ice_bar_rule=ice_bar_rule)
    stats["dropped_symbols_recorded"] = artifact.get("dropped_count")

    if dataset == GLBX:
        stat_key = resolve_payload_key(s3_client, bucket, dataset=dataset, root=root, year=year,
                                       schema="statistics", mode=mode)
        stat_payload = _get(s3_client, bucket, stat_key)
        if stat_payload is None:
            logger.warning("%s %s/%s: no statistics payload -- settle stays NULL (F3: the ohlcv "
                           "close is NOT the settlement and is never substituted)",
                           dataset, root, year)
            stat_df = None
        else:
            stat_raw = decode_dbn(stat_payload, schema="statistics", symbology_json=symbology)
            stat_df = build_statistics_bronze(stat_raw, root=root, request_year=year)
        # BEFORE the join, while both frames still exist: is the ts_ref trading date on the same
        # calendar as the ts_event UTC day? A systematic skew matches nothing and is otherwise silent.
        stats["statistics_join"] = statistics_join_diagnostics(bronze, stat_df)
        bronze = join_glbx_statistics(bronze, stat_df)
        stats["glbx_settle_coverage"] = glbx_settle_coverage(bronze)
    else:
        stats["ice_probe"] = probe_ice_bar_rule(bronze)
        bronze = apply_ice_settle(bronze)
    return bronze, stats


def build_silver(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate bronze units and project onto the 17 physical + 2 partition columns."""
    live = [f for f in frames if f is not None and len(f)]
    if not live:
        return build_databento_eod_silver(pd.DataFrame())
    return build_databento_eod_silver(pd.concat(live, ignore_index=True))


def assert_no_duplicates(df: pd.DataFrame) -> None:
    """HARD FAIL on a duplicate natural key or a duplicate ``(trade_date, raw_symbol)``.

    Runs on the assembled frame BEFORE a byte is staged. There is no other check on this path:
    ``build_partitioned_publish`` performs none, ``lint_frame`` checks conditional nullability and
    per-slug label coherence only, the contract's ``duplicate_check`` runs against the table AFTER
    the write, and gate 1 lives in a standalone script the chain never invokes. The F2 ICE double
    bar is exactly the failure this catches, ``ICE_BAR_RULE`` is still PROVISIONAL pending probe P3,
    and the plan is explicit that a survivor is a hard fail and never a silent dedupe."""
    if df is None or df.empty:
        return
    for label, key in (("natural key", _NATURAL_KEY), ("(trade_date, raw_symbol)", _F2_KEY)):
        cols = [c for c in key if c in df.columns]
        if len(cols) != len(key):
            raise ValueError(f"frame is missing {sorted(set(key) - set(cols))} -- cannot assert "
                             f"{label} uniqueness")
        sizes = df.groupby(cols, dropna=False).size()
        dups = sizes[sizes > 1]
        if len(dups):
            worst = ", ".join(f"{tuple(str(x)[:10] for x in (k if isinstance(k, tuple) else (k,)))}"
                              f"x{int(v)}" for k, v in dups.sort_values(ascending=False).head(5).items())
            raise ValueError(
                f"{len(dups)} duplicate {label} value(s) in the assembled frame ({worst}) -- the F2 "
                f"double bar survived the ICE_BAR_RULE dedupe; refusing to stage. This is a hard "
                f"fail, never a dedupe: the rule is wrong, not the data"
            )


def merge_with_canonical(df: pd.DataFrame, contract: dict, s3_client) -> tuple[pd.DataFrame, dict]:
    """Union a PARTIAL frame with whatever is already canonical in each partition it touches.

    *** WHY THIS EXISTS: THE NIGHTLY RUN OWNS FIVE DAYS AND WRITES A WHOLE YEAR. ***
    ``build_partition_objects`` emits ONE object per ``(leviathan_slug, trade_year)`` group at the
    FIXED key ``.../leviathan_slug=X/trade_year=YYYY/part-000.parquet``. It never reads or appends to
    the existing object, and the key is byte-identical every run, so the put REPLACES the partition.
    A backfill unit owns its whole ``(root, year)`` and that is fine. An INCREMENTAL run holds only
    ``--lookback-days`` of the current year, so publishing it unmerged silently truncates the
    current-year partition of every slug to five days -- automated, unalarmed destruction of
    canonical history (the registry's vintage_retention is latest-only, ``silver_rebuild_gate`` is a
    consumer-sync dispatcher and checks no row counts, and the standalone W2 gate is not in the
    chain).

    So: read the existing object for each touched partition, union, and let the NEW rows win on a
    natural-key collision (a corrected settlement must be able to land). A partition that shrinks is
    a hard fail -- never publish fewer rows than were already there."""
    empty_rec = {"partitions": 0, "partitions_merged": 0, "prior_rows": 0,
                 "rows_in": int(0 if df is None else len(df)), "rows_out": 0}
    if df is None or df.empty:
        return df, empty_rec
    if s3_client is None:
        raise ValueError("merge_with_canonical needs a live S3 client -- an incremental publish "
                         "that cannot read the existing partitions would overwrite them")
    import io

    import pyarrow.parquet as pq
    from leviathan.silver.partitioned_producer import (
        DEFAULT_OBJECT_NAME,
        partition_object_key,
        partition_value_str,
    )

    bucket = contract["s3_bucket"]
    prefix = contract["s3_prefix"]
    types = {pk["name"]: pk.get("glue_type") for pk in contract.get("partition_keys", [])}
    priors: list[pd.DataFrame] = []
    prior_rows_by_partition: dict[tuple, int] = {}
    partitions = 0
    for values, _group in df.groupby(_PARTITION_COLS, dropna=False, sort=True):
        partitions += 1
        values = list(values) if isinstance(values, tuple) else [values]
        rendered = [partition_value_str(c, v, types.get(c))
                    for c, v in zip(_PARTITION_COLS, values)]
        key = partition_object_key(prefix, _PARTITION_COLS, rendered,
                                   filename=DEFAULT_OBJECT_NAME)
        body = _get(s3_client, bucket, key)
        if body is None:
            continue
        prior = pq.read_table(io.BytesIO(body)).to_pandas()
        # The partition columns live in the PATH and were dropped from the body -- put them back
        # from the group's own values, so the round trip is exact.
        for col, val in zip(_PARTITION_COLS, values):
            prior[col] = val
        extra = sorted(set(prior.columns) - set(SILVER_COLUMNS))
        missing = sorted(set(SILVER_COLUMNS) - set(prior.columns))
        if extra or missing:
            raise ValueError(
                f"canonical object s3://{bucket}/{key} does not carry the contract shape "
                f"(missing={missing}, extra={extra}) -- refusing to merge against it"
            )
        prior_rows_by_partition[tuple(rendered)] = len(prior)
        priors.append(prior[SILVER_COLUMNS])
    if not priors:
        logger.info("merge: %d partition(s) touched, none exists canonically yet -- nothing to "
                    "merge", partitions)
        return df, {**empty_rec, "partitions": partitions, "rows_out": int(len(df))}

    # NEW rows LAST so keep='last' resolves a natural-key collision in favour of this run (a
    # corrected settlement, a preliminary->final revision).
    merged = pd.concat(priors + [df[SILVER_COLUMNS]], ignore_index=True)
    ck = merged["contract_month"].astype("object").where(merged["contract_month"].notna(), "\x00")
    merged = merged.assign(_ck=ck).drop_duplicates(
        subset=["leviathan_slug", "_ck", "trade_date"], keep="last").drop(columns=["_ck"])
    merged["trade_year"] = pd.to_numeric(merged["trade_year"], errors="coerce").astype("int64")
    merged = merged[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "contract_month", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)

    # NO PARTITION MAY SHRINK. This is the whole point of the merge, asserted rather than assumed.
    after = merged.groupby(_PARTITION_COLS, dropna=False).size()
    for values, prior_n in prior_rows_by_partition.items():
        got = 0
        for idx, n in after.items():
            idx = idx if isinstance(idx, tuple) else (idx,)
            if tuple(partition_value_str(c, v, types.get(c))
                     for c, v in zip(_PARTITION_COLS, idx)) == values:
                got = int(n)
                break
        if got < prior_n:
            raise ValueError(
                f"partition {dict(zip(_PARTITION_COLS, values))} would shrink from {prior_n} to "
                f"{got} rows -- the merge lost history; refusing to publish"
            )
    rec = {"partitions": partitions, "partitions_merged": len(priors),
           "prior_rows": int(sum(prior_rows_by_partition.values())),
           "rows_in": int(len(df)), "rows_out": int(len(merged))}
    logger.info("merge: %s", json.dumps(rec, sort_keys=True))
    return merged, rec


def publish(df: pd.DataFrame, contract: dict, auth, s3_client, glue_client, *,
            run_id: Optional[str] = None, shadow_prefix: Optional[str] = None):
    """Stage + run the registered-partition publish. ``row_validator`` is NOT optional here."""
    plan = build_partitioned_publish(
        df=df,
        contract=contract,
        auth=auth,
        job=_JOB,
        partition_cols=_PARTITION_COLS,
        s3_client=s3_client,
        glue_client=glue_client,
        run_id=run_id,
        shadow_prefix=shadow_prefix,
        # MANDATORY for every silver_futures_eod producer -- the conditional invariants the F010
        # contract cannot express. Runs before a single byte is staged.
        row_validator=FC.lint_frame,
    )
    logger.info("staged %d partition(s), %d row(s) for %s",
                plan.partition_count, plan.row_count, contract["table_name"])
    return plan.run()


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(description="Databento raw -> silver_futures_eod (W2)")
    ap.add_argument("--mode", choices=["backfill", "incremental"], default="backfill")
    ap.add_argument("--root", action="append", dest="roots", default=None, choices=sorted(ROOT_MAP))
    ap.add_argument("--year", action="append", type=int, dest="years", default=None)
    ap.add_argument("--since", default=None, help="incremental: inclusive first trade date")
    ap.add_argument("--lookback-days", type=int, default=5,
                    help="incremental, used when --since is absent: keep the last N calendar days. "
                         "The scheduler substitutes only <aws.scheduler.*> attributes, so the "
                         "scheduled chain passes this rather than a templated date")
    ap.add_argument("--ice-bar-rule", default=ICE_BAR_RULE,
                    help="F2 double-bar rule (see transforms.raw_to_bronze.databento_eod)")
    ap.add_argument("--no-merge", action="store_true",
                    help="incremental only, REPAIR USE ONLY: stage the incremental window WITHOUT "
                         "unioning it with the existing canonical partitions. The staged object "
                         "REPLACES the whole (leviathan_slug, trade_year) partition, so this "
                         "truncates the current year to the lookback window. Never in the chain")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--shadow-prefix", default=None)
    ap.add_argument("--publish-mode", default="dry-run",
                    choices=["dry-run", "shadow", "canonical"], dest="publish_mode")
    ap.add_argument("--role-arn", default="", dest="role_arn")
    ap.add_argument("--account-id", default="", dest="account_id")
    args = ap.parse_args(argv)

    # Dependency preflight, ahead of every AWS call. The yfinance ImportError silently wrote
    # nothing for six weeks with no freshness alarm; this guard is the lesson.
    try:
        import databento  # noqa: F401
    except ImportError:
        logger.error("the 'databento' package is not installed -- the worker image predates the "
                     "pyproject [batch] databento pin; REBUILD + REPIN the worker image")
        return 1

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    contract = load_registry().table(_TABLE)

    roots = args.roots or sorted(ROOT_MAP)
    now_year = datetime.now(tz=timezone.utc).year
    if args.mode == "incremental":
        if not args.since:
            args.since = (datetime.now(tz=timezone.utc).date()
                          - timedelta(days=max(1, args.lookback_days))).isoformat()
        years = [datetime.strptime(args.since, "%Y-%m-%d").year]
    else:
        years = args.years
    units = []
    for root in roots:
        usable = root_years(root, now_year)
        for year in (years if years else usable):
            if int(year) in usable:
                units.append((ROOT_MAP[root][0], root, int(year)))
    if not units:
        logger.error("no (root, year) units selected")
        return 1

    account_id, role_arn = args.account_id, args.role_arn
    if args.publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)
    auth = authorize_for_contract(contract, publish_mode=args.publish_mode,
                                  role_arn=role_arn, account_id=account_id, env=os.environ)
    logger.info("publish authorized: mode=%s may_canonical=%s",
                auth.mode.value, auth.may_mutate_canonical)

    s3 = get_thread_local_s3_client(aws_region)
    publish_s3 = None if args.publish_mode == "dry-run" else s3
    glue = None
    if args.publish_mode == "canonical":
        import boto3
        glue = boto3.client("glue", region_name=aws_region)

    frames: list[pd.DataFrame] = []
    failures = 0
    for dataset, root, year in sorted(units):
        try:
            bronze, stats = load_unit_bronze(s3, bucket, dataset=dataset, root=root, year=year,
                                             ice_bar_rule=args.ice_bar_rule, mode=args.mode)
            if len(bronze) < _MIN_ROWS_PER_UNIT:
                logger.error("%s %s/%s: only %d bronze rows (floor %d) -- treating as a truncated "
                             "download, not a thin market", dataset, root, year, len(bronze),
                             _MIN_ROWS_PER_UNIT)
                failures += 1
                continue
            logger.info("unit %s %s/%s: %s", dataset, root, year, json.dumps(
                {k: v for k, v in stats.items() if k != "ice_dedupe"}, sort_keys=True))
            frames.append(bronze)
        except Exception:  # noqa: BLE001 -- one unit's failure must not abort the rest
            logger.exception("FAILED unit %s %s/%s", dataset, root, year)
            failures += 1

    if not frames:
        logger.error("no bronze frames produced from %d unit(s)", len(units))
        return 1
    df = build_silver(frames)
    if args.mode == "incremental" and args.since:
        df = df[df["trade_date"] >= pd.Timestamp(args.since)].reset_index(drop=True)
    if df.empty:
        logger.error("silver frame is EMPTY after assembly")
        return 1

    # The F2 precondition, enforced on the automated path rather than in a script nobody calls.
    assert_no_duplicates(df)

    if args.mode == "incremental" and not args.no_merge:
        # An incremental run holds only --lookback-days of the current year but stages the WHOLE
        # (leviathan_slug, trade_year) partition, so it must first read back what it does not own.
        df, merge_rec = merge_with_canonical(df, contract, s3)
        assert_no_duplicates(df)
        logger.info("incremental merge: %s", json.dumps(merge_rec, sort_keys=True))

    manifest = publish(df, contract, auth, publish_s3, glue,
                       run_id=args.run_id, shadow_prefix=args.shadow_prefix)
    logger.info("publish %s: state=%s rows=%d", auth.mode.value, manifest.state.value, len(df))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
