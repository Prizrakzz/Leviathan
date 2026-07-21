"""Mirror the numbers-registry serving tables into RDS Postgres (GRAPHRAG_NUMBERS_BACKEND=pg).

Reads each table's SILVER PARQUET straight from S3 (the source of truth — no Athena paging), using the Glue
catalog only for schema + location, and rebuilds the pg mirror atomically (DROP + CREATE + COPY inside one
transaction — pg DDL is transactional; readers keep the old rows until commit). The pg schema is named like the Athena database
(`leviathan_dev`) so `build_sql()` output runs unchanged on either backend.

TYPE DOCTRINE (parity-first): every column is TEXT except the ones SQL does math on — wide metric columns /
`value_col` (avg/sum/min/max run in-database), `year_col`/`month_col` (`year*100+month` guard), and int-typed
period columns. Dates stay ISO TEXT: build_sql compares them as text (`_dcol` casts), ISO sorts
lexically==chronologically, and Athena returns strings anyway — the executor stringifies, so a pg row is
indistinguishable from an Athena row.

Tall tables load ONLY the registry-declared metrics (silver_wasde declares 5 of ~300 attributes — ~98% of
rows are never servable). P1 tables below are all small-to-modest; silver_nasa_power is EXCLUDED until a
size check (tens of millions of rows) decides pruning vs an RDS bump.

    python jobs/utils/load_pg_numbers.py --dry-run
    python jobs/utils/load_pg_numbers.py --tables silver_fred_fx,silver_noaa_oni
    python jobs/utils/load_pg_numbers.py            # the P1 set

Runs IN-VPC (the RDS SG admits the Batch/serving SGs) — submit via jobs/submit/submit_batch_load_numbers_pg.py.
"""
from __future__ import annotations

import argparse
import logging
import os
import time

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger

logger = get_logger("load_pg_numbers")

P1_TABLES = ["silver_psd", "silver_wasde", "silver_production", "silver_esr", "silver_fred_fx",
             "silver_noaa_oni", "gold_weather_z",         # gold_weather_z: small tall z-table (D-W4);
             #                                              silver_nasa_power stays EXCLUDED (size, above)
             # numbers-depth wave (W0-4 / D3): three freshly wired WIDE tables. All small-to-modest and
             # numeric-column-safe under the type doctrine: ICCO metrics production_kt/grindings_kt/
             # end_stocks_kt/su_ratio, MPOB *_mt + su_ratio, SAGIS current_estimate_t/area_planted_ha
             # mirror as numeric; every date/slug/scope/period-string column stays ISO TEXT. SAGIS's
             # production_year (period_sql_type=int) also mirrors numeric. Justified by the serving
             # fast-path + the per-lane golden-vocabulary fixtures (NOT a C002 requirement; C002's
             # wide-metric check is AWS-free -- CORRECTION V2).
             "silver_icco_cocoa", "silver_mpob", "silver_sagis_cec",
             # PRICE_OBSERVABILITY W3.3: pink_sheet is a small flat wide table (798 rows); metric columns
             # mirror numeric, `date` (physical timestamp) stringifies to the Athena render and stays
             # TEXT COLLATE "C" -- the DP-5 substr normalization makes both backends compare identically.
             "silver_pink_sheet",
             # PRICE_OBSERVABILITY W4.2 (v2): silver_cot is a small flat wide table; the managed-money
             # metric columns (open_interest / mm_* levels + net + signed pct_oi + 3-yr z-scores) mirror
             # numeric under the type doctrine, and report_date / leviathan_slug / source stay ISO TEXT.
             "silver_cot"]
SCHEMA = "leviathan_dev"                       # == numbers.pgnumbers.SCHEMA == query.ATHENA_DB
GLUE_DB = "leviathan_dev"

_NUM_PG = {"double": "double precision", "float": "real", "bigint": "bigint", "int": "integer",
           "integer": "integer", "smallint": "smallint", "tinyint": "smallint"}


def _glue_table(name: str) -> dict:
    import boto3
    g = boto3.client("glue", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    t = g.get_table(DatabaseName=GLUE_DB, Name=name)["Table"]
    sd = t["StorageDescriptor"]
    cols = [(c["Name"], c["Type"].lower()) for c in sd.get("Columns", [])]
    parts = [(c["Name"], c["Type"].lower()) for c in t.get("PartitionKeys", [])]
    return {"location": sd["Location"], "columns": cols, "partitions": parts}


def _probe_body_columns(location: str) -> set[str]:
    """Physical column names of ONE parquet fragment under `location` (a single-footer schema probe).

    Why: a Glue PARTITION key that ALSO exists inside file bodies (silver_esr_compact post-BF-W2:
    as_of_date is both the vintage partition axis and a per-row column) makes pyarrow's dataset-schema
    unification fail — the declared partition field (string) clashes with the body column
    (large_string), live-proven on the vintage layout. The body value is authoritative (byte-identical
    to the directory value by construction), so such keys are dropped from the partitioning schema.
    Hidden prefixes ('_'/'.') are skipped, mirroring pyarrow's own discovery rule."""
    import boto3
    import pyarrow.dataset as pads
    path = location.removeprefix("s3://").rstrip("/")
    bucket, _, prefix = path.partition("/")
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix):].lstrip("/")
            if any(seg.startswith(("_", ".")) for seg in rel.split("/")):
                continue                                     # hidden staging/manifest prefixes
            if obj["Key"].endswith(".parquet"):
                # single URI STRING: the list form skips pyarrow's filesystem-from-URI resolution
                # and raises ArrowInvalid ("Expected a local filesystem path, got a URI") -- caught
                # live at the first BF-W2 in-VPC gate run.
                one = pads.dataset(f"s3://{bucket}/{obj['Key']}", format="parquet")
                return set(one.schema.names)
    return set()


def _numeric_cols(ts) -> set[str]:
    """Columns SQL does arithmetic/aggregation on — everything else mirrors as TEXT."""
    cols: set[str] = set()
    if ts.shape == "wide":
        cols |= set(ts.metrics)                              # metric NAME == column name on wide tables
    if ts.value_col:
        cols.add(ts.value_col)
    for c in (ts.year_col, ts.month_col):
        if c:
            cols.add(c)
    if ts.period_col and ts.period_sql_type == "int":
        cols.add(ts.period_col)
    if ts.commodity_code_col:
        cols.add(ts.commodity_code_col)
    return cols


def _pg_type(name: str, glue_type: str, numeric: set[str]) -> str:
    if name in numeric:
        base = glue_type.split("(")[0]
        return _NUM_PG.get(base, "double precision")
    # COLLATE "C" = byte order = Unicode code-point order = how Presto/Athena compares VARCHARs. The
    # database's linguistic default (en_US) orders punctuation/case differently, which would break
    # ORDER-BY parity on text tiebreak columns (country, period strings).
    return 'text COLLATE "C"'


def _coerce(v, is_numeric: bool):
    if v is None:
        return None
    if is_numeric:
        return v if isinstance(v, (int, float)) else float(v)
    return v if isinstance(v, str) else str(v)


def load_table(ts, conn, *, dry_run: bool = False, batch_rows: int = 20000) -> int:
    physical = ts.athena_table or ts.id
    meta = _glue_table(physical)
    all_cols = meta["columns"] + meta["partitions"]
    numeric = _numeric_cols(ts)
    col_defs = ", ".join(f'"{n}" {_pg_type(n, t, numeric)}' for n, t in all_cols)
    names = [n for n, _ in all_cols]
    is_num = [n in numeric for n in names]
    logger.info("[%s] physical=%s location=%s cols=%d (numeric: %s)",
                ts.id, physical, meta["location"], len(names), sorted(numeric) or "-")
    if dry_run:
        logger.info("[%s] DRY RUN - no DDL/load", ts.id)
        return 0

    import pyarrow as pa
    import pyarrow.dataset as pads

    # Partition keys that also live INSIDE file bodies are excluded from the partitioning schema
    # (unification clash — see _probe_body_columns); their values load from the body columns, and
    # pyarrow tolerates the unparsed directory segment.
    body_cols = _probe_body_columns(meta["location"])
    part_keys = [(n, t) for n, t in meta["partitions"] if n not in body_cols]

    def _open(unified: bool):
        if not unified:
            # EXPLICIT partition schema from Glue's declared types — pyarrow's hive inference types integer
            # path values as int64, which clashes with int32 columns inside the files ("Field year has
            # incompatible types" on silver_production). Glue is the source of truth for partition types.
            _ARROW = {"int": pa.int32(), "integer": pa.int32(), "bigint": pa.int64(),
                      "smallint": pa.int16()}
            part_schema = pa.schema(
                [(n, _ARROW.get(t.split("(")[0], pa.string())) for n, t in part_keys])
            partitioning = pads.partitioning(part_schema, flavor="hive") if part_keys else None
            return pads.dataset(meta["location"], format="parquet", partitioning=partitioning)
        # Glue-derived UNIFIED read schema for fragments whose schemas diverge across write eras
        # (silver_production: year int32 in some files, int64 in others) or that carry all-null columns
        # written as arrow `null` type (silver_wasde: "Unsupported cast from string to null"). Ints widen
        # to int64 / floats to float64 so every fragment casts UP safely; null-typed columns cast to the
        # declared type (null -> anything is a valid cast).
        _WIDE = {"int": pa.int64(), "integer": pa.int64(), "bigint": pa.int64(), "smallint": pa.int64(),
                 "tinyint": pa.int64(), "float": pa.float64(), "double": pa.float64(),
                 "boolean": pa.bool_(), "date": pa.date32(), "timestamp": pa.timestamp("us")}
        read_schema = pa.schema(
            [(n, _WIDE.get(t.split("(")[0], pa.string())) for n, t in meta["columns"]]
            + [(n, _WIDE.get(t.split("(")[0], pa.string())) for n, t in meta["partitions"]])
        wide_parts = pa.schema([(n, _WIDE.get(t.split("(")[0], pa.string())) for n, t in part_keys])
        partitioning = pads.partitioning(wide_parts, flavor="hive") if part_keys else None
        return pads.dataset(meta["location"], format="parquet", partitioning=partitioning,
                            schema=read_schema)

    flt = None
    if ts.shape == "tall" and ts.metric_col and ts.metrics:
        flt = pads.field(ts.metric_col).isin(list(ts.metrics))   # serve-relevant rows only (wasde: ~2%)

    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    def _load(dataset) -> int:
        n = 0
        # DROP+CREATE (not TRUNCATE) so column-definition changes (e.g. COLLATE "C") actually apply on
        # re-load; pg DDL is transactional, so readers still see the old table until commit.
        with conn.transaction():                                # atomic swap: readers see old rows until commit
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{SCHEMA}"."{physical}"')
                cur.execute(f'CREATE TABLE "{SCHEMA}"."{physical}" ({col_defs})')
                collist = ", ".join(f'"{c}"' for c in names)
                with cur.copy(f'COPY "{SCHEMA}"."{physical}" ({collist}) FROM STDIN') as copy:
                    # dataset schema may lack hive partition cols in some fragments; select explicitly
                    scanner = dataset.scanner(columns=names, filter=flt, batch_size=batch_rows)
                    for rb in scanner.to_batches():
                        pyd = rb.to_pydict()
                        cols = [pyd[c] for c in names]
                        for row in zip(*cols):
                            copy.write_row(tuple(_coerce(v, num) for v, num in zip(row, is_num)))
                            n += 1
        return n

    # Cast failures surface either at dataset() creation (whole-dataset schema unification:
    # silver_production) or MID-SCAN inside _load (fragment-local casts: silver_wasde's null-typed
    # columns raise ArrowNotImplementedError only when their fragment is actually read). The transaction
    # rolls back on exception, so retrying the whole load with the forced Glue schema is clean.
    _CAST_ERRS = (pa.lib.ArrowTypeError, pa.lib.ArrowNotImplementedError, pa.lib.ArrowInvalid)
    n = 0
    t0 = time.time()
    for unified in (False, True):
        try:
            n = _load(_open(unified))
            break
        except _CAST_ERRS as e:
            if unified:
                raise
            logger.info("[%s] arrow cast failure on default read (%s: %s) -> retrying with Glue-derived "
                        "unified read schema", ts.id, type(e).__name__, str(e)[:150])
    with conn.cursor() as cur:                                  # cheap serve-shaped indexes (idempotent)
        for col in filter(None, {ts.commodity_col, ts.metric_col, ts.knowledge_col(), ts.date_col}):
            cur.execute(f'CREATE INDEX IF NOT EXISTS "ix_{physical}_{col}" '
                        f'ON "{SCHEMA}"."{physical}" ("{col}")')
    logger.info("[%s] loaded %d rows in %.1fs", ts.id, n, time.time() - t0)
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    ap = argparse.ArgumentParser(description="Mirror numbers-registry tables into RDS pg")
    ap.add_argument("--tables", default=",".join(P1_TABLES),
                    help="comma-separated registry table ids (default: the P1 set)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    dsn = os.environ.get("EVIDENCE_PG_DSN")
    if not dsn and not args.dry_run:
        raise SystemExit("EVIDENCE_PG_DSN not set (run in-VPC via the Batch submit)")
    conn = None
    if not args.dry_run:
        import psycopg
        conn = psycopg.connect(dsn, autocommit=True)
    total, failures = 0, []
    for tid in [t.strip() for t in args.tables.split(",") if t.strip()]:
        try:
            total += load_table(reg.get(tid), conn, dry_run=args.dry_run)
        except Exception as e:  # noqa: BLE001 — one table's failure must not kill the rest of the mirror
            logger.error("[%s] FAILED: %s: %s", tid, type(e).__name__, str(e)[:300])
            failures.append(tid)
    logger.info("DONE: %d rows across %s%s", total, args.tables,
                f"  FAILURES: {failures}" if failures else "")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
