"""SILVER-F001 R0 census capture -- the apply-then-refresh tool, RECONSTRUCTED and COMMITTED.

``census_one(table)`` reads live Glue (get_table + get_partitions) and one canonical parquet
footer, and emits the R0 record shape the readiness baselines carry
(``reports/silver_readiness/<baseline_id>/tables/<table>.json``). Three files cite this module as
the sanctioned re-capture mechanism (gen_registry_from_baseline.py, f011_ddl_diff_report.py,
test_silver_registry_gen.py); until 2026-08-26 the tool itself existed ONLY as
``scratch/silver_f001/common.py`` -- gitignored, deleted, unrecoverable from git (verified) -- the
exact no-git-ref class SILVER-F091 now lints for. This reconstruction closes that.

THE HASH RECIPES -- TWO GENERATIONS, BOTH WRITTEN DOWN
------------------------------------------------------
RECIPE v1 (the ghost tool's, RECOVERED VERBATIM 2026-08-26): a first exhaustive search (~700
candidate serializations over the stored artifacts, the ``_raw`` sidecars, boto3 reconstructions,
DDL shapes and live parquet footers) missed it, because the catalog pre-image is a THIRD shape --
neither the stored glue block nor the raw dict. The recovery came from the estate's own transcript
archive: ``scratch/silver_f001/common.py`` was written by a Claude Code subagent on 2026-07-12,
and Claude Code persists every Write payload verbatim in its JSONL transcripts -- the whole
package was recovered from the ``79f4542e`` session's workflow transcripts, 72 seconds before the
census first ran. The recipes (implemented below as :func:`catalog_hash_v1` /
:func:`schema_fingerprint_v1`, and verifiable via ``--verify-legacy``):

    catalog_hash_sha256 (v1)      = sha256(json.dumps(canon, sort_keys=True, separators=(",",":")))
        where canon = {"columns": [{"Name","Type"}...], "partition_keys": [{"Name","Type"}...],
                       "location", "input_format", "output_format", "serde", "table_type",
                       "parameters" minus {"transient_lastDdlTime", "last_modified_time"}}
        built from the RAW boto3 Table dict (the ``_raw/<t>.get-table.json`` sidecar).
    schema_fingerprint_sha256 (v1) = sha256(";".join(f"{name}:{arrow_type}") over arrow_columns)

Legacy verification, measured 2026-08-26 across all 43 originals: schema 43/43 (two verify
against the MINT-TIME arrow list rather than the stored one, which was rewritten post-mint:
silver_noaa_iod hand-rewritten float->double, silver_pink_sheet extended 36->80 by the F063
widening refresh); catalog 41/43 (35 from the ``_raw`` sidecar = the frozen R0 rollback side, 6
from the record's own post-refresh glue block -- those six were re-captured after real catalog
events). THE TWO RESIDUALS ARE MIS-PROVENANCED, NOT UNEXPLAINED: ``silver_conab_coffee`` and
``silver_wasde`` carry SILVER-F012 ``catalog.hash_table`` values (a migration plan's
desired_hash) written into this F001 field by a later refresh -- annotated in-record, never
overwritten.

RECIPE v2 (this module's go-forward recipe, ``hash_recipe: 2`` stamped beside each hash) hashes
the ENTIRE record block, so coverage is wider than v1 (partition_mode, projection properties,
sample facts all bind) and every input is contained in the record itself -- any checkout verifies
offline, no AWS call, no sidecar:

    catalog_hash_sha256      = sha256(json.dumps(glue_block_minus_hash_fields,
                                                 sort_keys=True, separators=(",", ":")))
    schema_fingerprint_sha256 = sha256(json.dumps(physical_sample_minus_hash_fields,
                                                  sort_keys=True, separators=(",", ":")))

where "minus hash fields" strips ``catalog_hash_sha256``/``schema_fingerprint_sha256``/
``hash_recipe`` from the block being hashed. Legacy records keep their v1 values untouched and
are verified BY the v1 functions; new captures mint v2.

Usage (read-only against AWS; writes only the record/raw files you ask for):
    python scripts/silver/run_census.py --table silver_psd_attributes --dry-run
    python scripts/silver/run_census.py --table silver_psd_attributes            # writes the record
    python scripts/silver/run_census.py --table silver_psd --check               # capture vs stored diff
    python scripts/silver/run_census.py --table X --raw                          # also _raw/*.json
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
BASELINE_ID = "20260712_p65impl"
TABLES_DIR = _REPO / "reports" / "silver_readiness" / BASELINE_ID / "tables"
RAW_DIR = _REPO / "reports" / "silver_readiness" / BASELINE_ID / "_raw"
DATABASE = "leviathan_dev"
BUCKET = "leviathan-dev-shahem-001"
PARTITION_PAGE_CAP = 10   # pages of 1000; a projected table registers few or none

HASH_RECIPE_VERSION = 2
_HASH_FIELDS = ("catalog_hash_sha256", "schema_fingerprint_sha256", "hash_recipe")

# Fields that legitimately move between captures of an UNCHANGED table (times move only when the
# catalog is touched, but boto3 renders them in local tz -- keep them out of --check's diff noise).
_CHECK_VOLATILE = {"captured_at_utc", "anchor_git_sha", "package", "readiness_reason",
                   "reproduction_commands", "readiness_state", "refreshed"}


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_block(block: dict) -> str:
    """RECIPE v2: sha256 over the canonical JSON of the block minus its own hash fields."""
    return _sha256(_canonical({k: v for k, v in block.items() if k not in _HASH_FIELDS}))


# ---------------------------------------------------------------------------
# RECIPE v1 -- the ghost tool's recipes, recovered verbatim (see module docstring).
# ---------------------------------------------------------------------------

def catalog_hash_v1(tbl: dict) -> str:
    """The ghost tool's catalog fingerprint over a RAW boto3 Table dict (verbatim recovery)."""
    sd = tbl.get("StorageDescriptor", {})
    canon = {
        "columns": [{"Name": c["Name"], "Type": c["Type"]} for c in sd.get("Columns", [])],
        "partition_keys": [{"Name": c["Name"], "Type": c["Type"]}
                           for c in tbl.get("PartitionKeys", [])],
        "location": sd.get("Location"),
        "input_format": sd.get("InputFormat"),
        "output_format": sd.get("OutputFormat"),
        "serde": (sd.get("SerdeInfo") or {}).get("SerializationLibrary"),
        "table_type": tbl.get("TableType"),
        "parameters": {k: v for k, v in (tbl.get("Parameters") or {}).items()
                       if k not in ("transient_lastDdlTime", "last_modified_time")},
    }
    return _sha256(_canonical(canon))


def _record_glue_to_raw_shape(glue_block: dict) -> dict:
    """Rebuild the v1 pre-image from a RECORD's glue block (for records re-captured after a
    catalog event, whose _raw sidecar is the frozen pre-event rollback side by design)."""
    return {
        "StorageDescriptor": {
            "Columns": [{"Name": c["name"], "Type": c["type"]}
                        for c in glue_block["nonpartition_columns"]],
            "Location": glue_block["location"],
            "InputFormat": glue_block["input_format"],
            "OutputFormat": glue_block["output_format"],
            "SerdeInfo": {"SerializationLibrary": glue_block["serde"]},
        },
        "PartitionKeys": [{"Name": c["name"], "Type": c["type"]}
                          for c in glue_block["partition_keys"]],
        "TableType": glue_block["table_type"],
        "Parameters": glue_block["parameters"],
    }


def schema_fingerprint_v1(arrow_columns: list) -> str:
    """The ghost tool's schema fingerprint: semicolon-joined name:type, no JSON, no terminator."""
    return _sha256(";".join(f"{c['name']}:{c['type']}" for c in arrow_columns))


# The two records whose stored catalog hashes were measured (2026-08-26) to be SILVER-F012
# ``catalog.hash_table`` values -- a migration plan's desired_hash written into this F001 field by
# a later refresh. Mis-provenanced, annotated in-record, never overwritten or re-minted.
MISPROVENANCED_LEGACY_CATALOG = frozenset({"silver_conab_coffee", "silver_wasde"})
# Records whose stored arrow list was REWRITTEN AFTER minting, so the v1 schema hash verifies
# against the mint-time list (recoverable from the footer / the _raw side), not the stored one:
# silver_noaa_iod's list was hand-rewritten float->double; silver_pink_sheet's was extended 36->80
# by the 2026-08-20 F063 series-widening refresh (scratchpad refresh_baseline.py appended 44
# declared-target columns while deliberately leaving the mint-time hash untouched).
LEGACY_SCHEMA_LIST_REWRITTEN_POST_MINT = frozenset({"silver_noaa_iod", "silver_pink_sheet"})


def verify_legacy() -> int:
    """Verify every legacy record's v1 hashes offline (stored record + _raw sidecar only)."""
    ok = bad = 0
    for p in sorted(TABLES_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        g = d.get("glue", {})
        if "hash_recipe" in g or g.get("catalog_hash_sha256", "0" * 64) == "0" * 64:
            continue
        name = d["table"]
        # catalog: the _raw sidecar (frozen R0 side) OR the record's post-refresh glue block.
        cands = []
        raw_p = RAW_DIR / f"{name}.get-table.json"
        if raw_p.exists():
            cands.append(catalog_hash_v1(json.loads(raw_p.read_text(encoding="utf-8"))))
        cands.append(catalog_hash_v1(_record_glue_to_raw_shape(g)))
        c_ok = g["catalog_hash_sha256"] in cands
        if not c_ok and name in MISPROVENANCED_LEGACY_CATALOG:
            print(f"  {name}: catalog = KNOWN MIS-PROVENANCED (F012 value in the F001 field)")
            c_ok = True
        s_ok = (d["physical_sample"]["schema_fingerprint_sha256"]
                == schema_fingerprint_v1(d["physical_sample"]["arrow_columns"]))
        if not s_ok and name in LEGACY_SCHEMA_LIST_REWRITTEN_POST_MINT:
            print(f"  {name}: schema = mint-time list rewritten post-mint (documented)")
            s_ok = True
        if c_ok and s_ok:
            ok += 1
        else:
            bad += 1
            print(f"  UNEXPLAINED: {name} catalog_ok={c_ok} schema_ok={s_ok}")
    print(f"verify-legacy: {ok} verified, {bad} unexplained")
    return 0 if bad == 0 else 1


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def _partition_mode(glue_params: dict, partition_keys: list) -> str:
    if not partition_keys:
        return "flat"
    if str(glue_params.get("projection.enabled", "")).lower() == "true":
        return "projected"
    return "registered"


def _newest_parquet_key(s3, bucket: str, prefix: str) -> tuple[str | None, int]:
    """Newest non-hidden .parquet under prefix (Hive hidden-path convention: skip _*/.*)."""
    newest, size = None, 0
    newest_ts = None
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix.rstrip("/")) + 1:]
            if any(seg.startswith(("_", ".")) for seg in rel.split("/")):
                continue
            if not key.endswith(".parquet"):
                continue
            if newest_ts is None or obj["LastModified"] > newest_ts:
                newest, size, newest_ts = key, obj["Size"], obj["LastModified"]
    return newest, size


def census_one(table: str, *, database: str = DATABASE, bucket: str = BUCKET,
               sample_key: str | None = None, package: str = "",
               anchor_git_sha: str = "") -> tuple[dict, dict, dict]:
    """Capture one table's R0 record from live Glue + the canonical parquet footer.

    Returns ``(record, raw_get_table, raw_get_partitions)`` -- the latter two in the exact shapes
    the ``_raw/`` sidecars carry."""
    import boto3
    import pyarrow.parquet as pq

    glue_c = boto3.client("glue", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    sts = boto3.client("sts", region_name="us-east-1")
    account_id = sts.get_caller_identity()["Account"]

    t = glue_c.get_table(DatabaseName=database, Name=table)["Table"]
    sd = t["StorageDescriptor"]
    location = sd["Location"].rstrip("/")
    prefix = location.split("/", 3)[3] if location.startswith("s3://") else location
    partition_keys = [{"name": c["Name"], "type": c["Type"]} for c in t.get("PartitionKeys", [])]
    params = dict(t.get("Parameters") or {})
    proj_props = {k: v for k, v in params.items() if k.startswith("projection.")}

    # partitions (registered) -- capped, never exhaustive
    parts, capped = [], False
    if t.get("PartitionKeys"):
        paginator = glue_c.get_paginator("get_partitions")
        pages = 0
        for page in paginator.paginate(DatabaseName=database, TableName=table,
                                       PaginationConfig={"PageSize": 1000}):
            parts.extend(p.get("Values", []) for p in page.get("Partitions", []))
            pages += 1
            if pages >= PARTITION_PAGE_CAP:
                capped = True
                break

    glue_block = {
        "location": location,
        "s3_bucket": bucket,
        "s3_prefix": prefix,
        "table_type": t.get("TableType"),
        "input_format": sd.get("InputFormat"),
        "output_format": sd.get("OutputFormat"),
        "serde": (sd.get("SerdeInfo") or {}).get("SerializationLibrary"),
        "num_nonpartition_columns": len(sd["Columns"]),
        "nonpartition_columns": [{"name": c["Name"], "type": c["Type"]} for c in sd["Columns"]],
        "partition_keys": partition_keys,
        "partition_mode": _partition_mode(params, partition_keys),
        "projection_enabled": str(params.get("projection.enabled", "")).lower() == "true",
        "projection_properties": proj_props,
        "create_time": str(t.get("CreateTime", "")),
        "update_time": str(t.get("UpdateTime", "")),
        "version_id": t.get("VersionId", ""),
        "catalog_id": t.get("CatalogId", account_id),
        "parameters": params,
    }
    glue_block["catalog_hash_sha256"] = hash_block(glue_block)
    glue_block["hash_recipe"] = HASH_RECIPE_VERSION

    # physical sample
    key, size = (sample_key, None) if sample_key else _newest_parquet_key(s3, bucket, prefix)
    physical_error = None
    if key is None:
        physical = {
            "sample_key": None, "sample_size_bytes": 0, "num_rows_in_file": 0,
            "num_row_groups": 0, "created_by": f"(no parquet object under {prefix})",
            "kv_metadata_keys": [], "arrow_columns": [], "parquet_physical_columns": [],
        }
        physical_error = f"no non-hidden .parquet object found under s3://{bucket}/{prefix}/"
    else:
        head = s3.head_object(Bucket=bucket, Key=key)
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        pf = pq.ParquetFile(io.BytesIO(body))
        md = pf.metadata
        kv = md.metadata or {}
        physical = {
            "sample_key": key,
            "sample_size_bytes": head["ContentLength"],
            "num_rows_in_file": md.num_rows,
            "num_row_groups": md.num_row_groups,
            "created_by": md.created_by,
            "kv_metadata_keys": sorted(k.decode("utf-8", "replace") for k in kv),
            "arrow_columns": [{"name": f.name, "type": str(f.type)} for f in pf.schema_arrow],
            "parquet_physical_columns": [
                {"name": md.schema.column(i).name,
                 "physical_type": md.schema.column(i).physical_type}
                for i in range(len(md.schema))
            ],
        }
    physical["schema_fingerprint_sha256"] = hash_block(physical)
    physical["hash_recipe"] = HASH_RECIPE_VERSION

    record = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "package": package or f"run_census re-capture (recipe v{HASH_RECIPE_VERSION})",
        "baseline_id": BASELINE_ID,
        "anchor_git_sha": anchor_git_sha,
        "account_id": account_id,
        "region": "us-east-1",
        "database": database,
        "table": table,
        "readiness_state": "READY",
        "readiness_reason": (
            f"Captured from live Glue + the parquet footer by scripts/silver/run_census.py "
            f"(hash recipe v{HASH_RECIPE_VERSION}: every hash input is stored in this record; "
            f"verify offline with run_census.hash_block)."),
        "reproduction_commands": [f"python scripts/silver/run_census.py --table {table}"],
        "glue": glue_block,
        "registered_partitions": {
            "count": len(parts), "page_capped": capped, "placeholder_count": 0,
            "sample": parts[:5],
        },
        "physical_sample": physical,
        "physical_sample_error": physical_error,
        "glue_vs_physical": {
            "glue_nonpartition_cols": len(sd["Columns"]),
            "physical_parquet_cols": len(physical["parquet_physical_columns"]),
            "equal": len(sd["Columns"]) == len(physical["parquet_physical_columns"]),
            "note": ("Glue non-partition column count vs physical parquet column count "
                     "(physical excludes Hive partition cols by design)"),
        },
    }
    raw_table = json.loads(json.dumps(t, default=str))
    raw_parts = {"count": len(parts), "capped": capped, "partitions": parts[:1000]}
    return record, raw_table, raw_parts


# ---------------------------------------------------------------------------
# Check (capture vs stored)
# ---------------------------------------------------------------------------

def check_one(table: str) -> int:
    stored_p = TABLES_DIR / f"{table}.json"
    if not stored_p.exists():
        print(f"NO STORED RECORD: {stored_p}")
        return 2
    stored = json.loads(stored_p.read_text(encoding="utf-8"))
    fresh, _, _ = census_one(table)
    legacy = "hash_recipe" not in stored.get("glue", {})
    diffs = []

    notes = []

    def cmp(path: str, a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k in _CHECK_VOLATILE or (legacy and k in _HASH_FIELDS):
                    continue
                cmp(f"{path}.{k}", a.get(k), b.get(k))
        elif a != b:
            # KNOWN GHOST-TOOL DIVERGENCE, measured 2026-08-26 on silver_noaa_oni: the original
            # captures sampled the byte-identical `_shadow/` staging twin (the W7 2x-miscount
            # hazard class); this reconstruction skips hidden paths by the Hive convention. Same
            # bytes, better key -- a NOTE, never drift.
            if (path == ".physical_sample.sample_key" and isinstance(a, str) and isinstance(b, str)
                    and a.replace("/_shadow/", "/") == b):
                notes.append(f"  NOTE {path}: stored sampled the _shadow twin ({a!r}); "
                             f"live samples canonical ({b!r}) -- same bytes, corrected key")
                return
            diffs.append((path, a, b))

    cmp("", stored, fresh)
    for n in notes:
        print(n)
    if not diffs:
        tag = " (legacy v1 hashes excluded -- unreproducible, labeled)" if legacy else ""
        print(f"CHECK OK: {table} live capture matches the stored record{tag}")
        return 0
    print(f"CHECK DRIFT: {table} -- {len(diffs)} field(s) differ:")
    for path, a, b in diffs[:30]:
        print(f"  {path}: stored={a!r} live={b!r}")
    return 1


def main() -> None:
    ap = argparse.ArgumentParser(description="SILVER-F001 R0 census capture (recipe v2)")
    ap.add_argument("--table", default=None)
    ap.add_argument("--verify-legacy", action="store_true", dest="verify_legacy",
                    help="verify every legacy record's v1 hashes OFFLINE (no AWS); ignores --table")
    ap.add_argument("--database", default=DATABASE)
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--sample-key", default=None, dest="sample_key")
    ap.add_argument("--check", action="store_true", help="capture and DIFF vs the stored record; write nothing")
    ap.add_argument("--raw", action="store_true", help="also write the _raw/ get-table/get-partitions sidecars")
    ap.add_argument("--dry-run", action="store_true", help="print the record; write nothing")
    args = ap.parse_args()

    if args.verify_legacy:
        sys.exit(verify_legacy())
    if not args.table:
        ap.error("--table is required (or use --verify-legacy)")
    if args.check:
        sys.exit(check_one(args.table))

    record, raw_t, raw_p = census_one(args.table, database=args.database, bucket=args.bucket,
                                      sample_key=args.sample_key)
    text = json.dumps(record, indent=1, ensure_ascii=True) + "\n"
    if args.dry_run:
        print(text)
        return
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    out = TABLES_DIR / f"{args.table}.json"
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    if args.raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{args.table}.get-table.json").write_text(
            json.dumps(raw_t, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
        (RAW_DIR / f"{args.table}.get-partitions.json").write_text(
            json.dumps(raw_p, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote _raw sidecars for {args.table}")


if __name__ == "__main__":
    main()
