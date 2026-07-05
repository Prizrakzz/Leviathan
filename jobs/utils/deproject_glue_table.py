"""De-project sparse Glue tables: partition PROJECTION -> REGISTERED partitions (Jul-2026 LIST-storm class fix).

Projection on SPARSE tables makes Athena enumerate the projected grid on S3 for any non-sargable query:
silver_esr projected ~6M candidates over 370 real dirs (~16,000x), silver_wasde 19.5K over 461 (42x),
silver_model_predictions ~29K over a handful. One CAST'd predicate = ~130-600K LISTs (~$5-8). Registered
partitions prune catalog-side for ANY query shape (the silver_esr_compact precedent).

ZERO-DOWNTIME MECHANICS: while `projection.enabled=true` Athena IGNORES registered partitions, so
`--register` is invisible and can run any time; the cutover is `--flip` — ONE atomic update_table removing
the projection properties. `--rollback <snapshot.json>` restores the exact original Parameters (registered
partitions become inert again). Dense projected tables (weather trio) are NOT targets — their real layout
~= the grid, so projection is efficient there.

    python jobs/utils/deproject_glue_table.py --dry-run              # show everything, touch nothing
    python jobs/utils/deproject_glue_table.py --register             # snapshot + register (invisible)
    python jobs/utils/deproject_glue_table.py --register --tables silver_wasde
    python jobs/utils/deproject_glue_table.py --flip --tables silver_wasde     # THE gated cutover
    python jobs/utils/deproject_glue_table.py --rollback data/glue_backups/silver_wasde_<ts>.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger

logger = get_logger("deproject_glue_table")

DB = "leviathan_dev"
BUCKET = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")

# Per-table: S3 root prefix + ordered partition columns + the S3 dir-key each column uses (silver_esr's
# column `as_of_date` lives under dirs named `as_of=` — the projection template did the mapping; we must).
TARGETS = {
    "silver_wasde": {
        "prefix": "silver/wasde/",
        "cols": [("release_date", "release_date")],
    },
    "silver_esr": {
        "prefix": "silver/production/source=usda_esr/",
        "cols": [("commodity_code", "commodity_code"), ("market_year", "market_year"),
                 ("as_of_date", "as_of")],
    },
    "silver_model_predictions": {
        "prefix": "silver/model_predictions/",
        "cols": [("model_family", "model_family"), ("prediction_date", "prediction_date")],
    },
}


def _s3():
    import boto3
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _walk_partitions(prefix: str, dir_keys: list[str]) -> list[tuple[list[str], str]]:
    """Delimiter-walk the REAL prefixes level by level -> [(values, s3_location)]. Values are taken from
    `<dir_key>=<value>/` path segments in declared column order."""
    s3 = _s3()
    level: list[tuple[list[str], str]] = [([], prefix)]
    for dk in dir_keys:
        nxt: list[tuple[list[str], str]] = []
        for vals, p in level:
            tok = None
            while True:
                kw = dict(Bucket=BUCKET, Prefix=p, Delimiter="/")
                if tok:
                    kw["ContinuationToken"] = tok
                r = s3.list_objects_v2(**kw)
                for c in r.get("CommonPrefixes", []):
                    seg = c["Prefix"][len(p):].strip("/")
                    if seg.startswith(dk + "="):
                        nxt.append((vals + [seg.split("=", 1)[1]], c["Prefix"]))
                tok = r.get("NextContinuationToken")
                if not tok:
                    break
        level = nxt
    return [(vals, f"s3://{BUCKET}/{p}") for vals, p in level]


def _snapshot(glue, table: str) -> Path:
    t = glue.get_table(DatabaseName=DB, Name=table)["Table"]
    out = Path("data/glue_backups") / f"{table}_{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(t, indent=2, default=str), encoding="utf-8")
    try:  # second copy off-laptop — the rollback artifact must survive the machine
        _s3().put_object(Bucket=BUCKET, Key=f"admin/glue_backups/{out.name}",
                         Body=out.read_bytes())
    except Exception as e:  # noqa: BLE001
        logger.warning("s3 backup copy failed (local copy kept): %s", e)
    logger.info("[%s] snapshot -> %s (+ s3://%s/admin/glue_backups/)", table, out, BUCKET)
    return out


_TABLE_INPUT_KEYS = ("Name", "Description", "Owner", "Retention", "StorageDescriptor", "PartitionKeys",
                     "TableType", "Parameters")


def _table_input(t: dict) -> dict:
    return {k: t[k] for k in _TABLE_INPUT_KEYS if k in t}


def cmd_register(tables: list[str], dry: bool) -> None:
    from leviathan.storage import glue_partitions as gp
    glue = gp._glue()
    for table in tables:
        cfg = TARGETS[table]
        parts = _walk_partitions(cfg["prefix"], [dk for _, dk in cfg["cols"]])
        logger.info("[%s] %d real partitions found under s3://%s/%s", table, len(parts), BUCKET, cfg["prefix"])
        for vals, loc in parts[:3]:
            logger.info("[%s]   sample %s -> %s", table, vals, loc)
        if dry:
            continue
        _snapshot(glue, table)
        created, existed = gp.batch_ensure(DB, table, parts)
        logger.info("[%s] registered %d new, %d already present (INVISIBLE until --flip)",
                    table, created, existed)


def cmd_flip(tables: list[str], dry: bool) -> None:
    import boto3
    glue = boto3.client("glue", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    for table in tables:
        t = glue.get_table(DatabaseName=DB, Name=table)["Table"]
        params = dict(t.get("Parameters") or {})
        doomed = [k for k in params if k.startswith("projection.") or k == "storage.location.template"]
        logger.info("[%s] removing params: %s", table, sorted(doomed))
        if dry:
            continue
        _snapshot(glue, table)                       # snapshot again at flip time (belt + braces)
        for k in doomed:
            params.pop(k)
        params["deprojected"] = time.strftime("%Y-%m-%d")   # audit breadcrumb
        ti = _table_input(t)
        ti["Parameters"] = params
        glue.update_table(DatabaseName=DB, TableInput=ti)
        logger.info("[%s] FLIPPED to registered partitions (rollback: --rollback <snapshot>)", table)


def cmd_rollback(snapshot_path: str) -> None:
    import boto3
    glue = boto3.client("glue", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    t = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    glue.update_table(DatabaseName=DB, TableInput=_table_input(t))
    logger.info("[%s] parameters RESTORED from %s (projection re-enabled; registered partitions inert)",
                t["Name"], snapshot_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    ap = argparse.ArgumentParser(description="Projection -> registered partitions for sparse Glue tables")
    ap.add_argument("--tables", default=",".join(TARGETS), help="comma-separated subset of targets")
    ap.add_argument("--register", action="store_true", help="snapshot + register real partitions (invisible)")
    ap.add_argument("--flip", action="store_true", help="THE cutover: remove projection properties (gated)")
    ap.add_argument("--rollback", default=None, metavar="SNAPSHOT_JSON")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    unknown = [t for t in tables if t not in TARGETS]
    if unknown:
        raise SystemExit(f"not a de-projection target: {unknown} (dense tables stay projected on purpose)")
    if args.rollback:
        cmd_rollback(args.rollback)
        return
    if args.flip:
        cmd_flip(tables, args.dry_run)
        return
    # default / --register / --dry-run
    cmd_register(tables, dry=args.dry_run and not args.register or args.dry_run)


if __name__ == "__main__":
    main()
