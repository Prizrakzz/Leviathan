"""SILVER-V001 runner -- the canonical value census (bounded, read-only, footer-only).

Reads the F010 silver registry, samples parquet objects per partition-era, reads
their FOOTERS via a bounded range-GET (pyarrow S3FileSystem), and evaluates the
V001 gate (null-fraction floor, all-NaN, all-constant/sentinel, single-vintage).
Emits one ``<table>.json`` per table plus a ``value_census_summary.json`` index
under the evidence directory.

HARD INVARIANTS
---------------
* INV-3: this runner NEVER constructs an Athena client and NEVER issues
  ``start-query-execution``. The projection trio (nasa_power / chirps / cpc_soil)
  is sampled the same footer way as every other table. ``athena_queries_issued``
  is stamped 0 in every emitted record as the tripwire.
* READ-ONLY: only ``list_objects_v2`` + footer range-GET. No mutation, so no
  ``publish_guard`` authorization is required (there is no publish path here).
* ASCII-only stdout (cp1252 console). Report files are UTF-8.

Usage:
    python jobs/audit/value_census.py --tables silver_chirps,silver_esr_compact \\
        --evidence-dir reports/silver_readiness/R1_V001_value_census
    python jobs/audit/value_census.py --all --evidence-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Repo root on sys.path so "leviathan.*" imports work when run as a plain script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from leviathan.silver.registry import load_registry  # noqa: E402
from leviathan.silver.value_census import (  # noqa: E402
    apply_vintage_waiver,
    census_column,
    evaluate_gate,
    evaluate_warnings,
    file_column_stat,
    build_table_result,
    GateRow,
    TableCensusResult,
)

REGION = "us-east-1"
BUCKET = "leviathan-dev-shahem-001"
BASELINE_ID = "20260712_p65impl"

# ML/non-value tables the census skips (no numeric measurement contract).
SKIP_TABLES = {"silver_model_predictions"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Bounded S3 sampling (LIST only) -- no footer body reads here.
# ---------------------------------------------------------------------------
def _is_hidden(key: str) -> bool:
    """Hive hidden-path convention: any ``_``/``.``-prefixed segment is control-plane.

    The F015 publisher stages under ``<root>/_shadow/`` and persists manifests under
    ``<root>/_manifests/`` (both table-root children after the BF-W1 placement fix); the
    census must never sample them as data."""
    return any(seg.startswith(("_", ".")) for seg in key.split("/") if seg)


def _immediate_child_prefixes(s3, prefix: str, cap: int) -> list[str]:
    """Immediate ``key=value/`` child prefixes under ``prefix`` (one Delimiter LIST page walk)."""
    out: list[str] = []
    token = None
    while True:
        kw = dict(Bucket=BUCKET, Prefix=prefix, Delimiter="/", MaxKeys=1000)
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        out.extend(cp["Prefix"] for cp in r.get("CommonPrefixes", [])
                   if not _is_hidden(cp["Prefix"][len(prefix):]))
        token = r.get("NextContinuationToken")
        if not token or len(out) >= cap:
            break
    return out[:cap]


def _parquets_under(s3, prefix: str, per_group: int, page_cap: int = 6) -> list[str]:
    """Up to ``per_group`` parquet keys spread across the (bounded) listing under ``prefix``."""
    keys: list[str] = []
    token = None
    pages = 0
    while True:
        kw = dict(Bucket=BUCKET, Prefix=prefix, MaxKeys=400)
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        keys.extend(o["Key"] for o in r.get("Contents", [])
                    if o["Key"].endswith(".parquet") and not _is_hidden(o["Key"]))
        token = r.get("NextContinuationToken")
        pages += 1
        if not token or pages >= page_cap:
            break
    if len(keys) <= per_group:
        return keys
    # spread: first, last, and evenly-spaced interior samples (era coverage).
    idxs = sorted({round(i * (len(keys) - 1) / (per_group - 1)) for i in range(per_group)})
    return [keys[i] for i in idxs]


def sample_groups(
    s3,
    prefix: str,
    partition_mode: str,
    projection_domains: dict,
    *,
    group_cap: int = 96,
    per_group: int = 3,
) -> dict[str, list[str]]:
    """Return ``{group_label: [parquet_key, ...]}`` sampled per partition-era.

    * flat            -> one group ('' == the whole prefix).
    * projected       -> one group per commodity enum value (the era axis where the
                         CHIRPS all-NaN lives), each sampled across years.
    * registered /    -> one group per immediate child partition prefix.
      partitioned
    """
    prefix = prefix if prefix.endswith("/") else prefix + "/"
    groups: dict[str, list[str]] = {}

    if partition_mode == "flat":
        groups[""] = _parquets_under(s3, prefix, per_group=max(per_group, 4))
        return groups

    child_prefixes: list[str] = []
    enum_vals = (projection_domains or {}).get("projection.commodity.values")
    if partition_mode == "projected" and enum_vals:
        child_prefixes = [f"{prefix}commodity={v}/" for v in str(enum_vals).split(",")]
    else:
        child_prefixes = _immediate_child_prefixes(s3, prefix, cap=group_cap)
    if not child_prefixes:  # fallback: treat as flat
        groups[""] = _parquets_under(s3, prefix, per_group=max(per_group, 4))
        return groups

    for cp in child_prefixes[:group_cap]:
        label = cp[len(prefix):].strip("/")
        keys = _parquets_under(s3, cp, per_group=per_group)
        if keys:
            groups[label] = keys
    return groups


# ---------------------------------------------------------------------------
# Footer reads (range-GET only) -> FileColumnStat cache.
# ---------------------------------------------------------------------------
def _read_footer_stats(fs, key: str, columns: list[str]) -> dict:
    import pyarrow.parquet as pq  # lazy: keeps module import AWS/arrow-free for callers
    pf = pq.ParquetFile(fs.open_input_file(f"{BUCKET}/{key}"))
    md = pf.metadata
    return {c: file_column_stat(md, c) for c in columns}


def census_one_table(contract: dict, *, per_group: int = 3, max_workers: int = 16) -> tuple[TableCensusResult, dict]:
    import boto3  # lazy
    import pyarrow.fs as pafs  # lazy

    s3 = boto3.client("s3", region_name=REGION)
    fs = pafs.S3FileSystem(region=REGION)

    table = contract["table_name"]
    prefix = contract.get("s3_prefix") or ""
    partition_mode = contract.get("partition_mode", "flat")
    value_columns = list(contract.get("value_columns") or [])
    min_frac = contract.get("min_nonnull_frac")
    floor_overrides = contract.get("min_nonnull_frac_overrides") or None
    knowledge_col = contract.get("knowledge_date_col")
    vintage = contract.get("vintage_retention")
    projection_domains = contract.get("projection_domains") or {}

    target_cols = list(dict.fromkeys(value_columns + ([knowledge_col] if knowledge_col else [])))

    groups = sample_groups(s3, prefix, partition_mode, projection_domains, per_group=per_group)
    all_keys = [(g, k) for g, keys in groups.items() for k in keys]

    # Parallel footer reads (memory: parallelize S3-bound work).
    stats_by_key: dict[str, dict] = {}
    if target_cols and all_keys:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(_read_footer_stats, fs, k, target_cols): k for _, k in all_keys}
            for fut in as_completed(futs):
                k = futs[fut]
                try:
                    stats_by_key[k] = fut.result()
                except Exception as exc:  # noqa: BLE001 -- a bad footer must not abort the census
                    stats_by_key[k] = {"__error__": str(exc)}

    # Table-wide census per target column (for the JSON record + vintage check).
    census_by_column = {}
    for col in target_cols:
        fstats = [stats_by_key.get(k, {}).get(col) for _, k in all_keys]
        census_by_column[col] = census_column(fstats, col)

    # Per-group value-column gate (the "per commodity" floor semantics).
    per_group_rows: list[GateRow] = []
    per_group_warns: list[GateRow] = []
    group_summaries: dict[str, dict] = {}
    for g, keys in groups.items():
        g_census = {}
        for col in value_columns:
            fstats = [stats_by_key.get(k, {}).get(col) for k in keys]
            g_census[col] = census_column(fstats, col)
        label = g or "(flat)"
        for r in evaluate_gate(table, g_census, value_columns, min_frac,
                               floor_overrides=floor_overrides):  # value checks only
            per_group_rows.append(GateRow(r.table, r.column, r.kind, r.observed, r.threshold,
                                          f"[{label}] {r.detail}"))
        for r in evaluate_warnings(table, g_census, value_columns):
            per_group_warns.append(GateRow(r.table, r.column, r.kind, r.observed, r.threshold,
                                           f"[{label}] {r.detail}"))
        group_summaries[label] = {col: g_census[col].to_dict() for col in value_columns}

    # Vintage-adequacy from the table-wide knowledge census. A declared, user-gated
    # vintage_waiver (BF-W2 rider 6: annual latest-only sources where a second vintage is
    # structurally impossible) demotes the single_vintage HARD row to a WARN that carries the
    # waiver -- reported, never silently green; evaluate_gate itself stays strict.
    vintage_rows = evaluate_gate(
        table, census_by_column, [], min_frac,
        knowledge_date_col=knowledge_col,
        knowledge_census=census_by_column.get(knowledge_col) if knowledge_col else None,
    )
    waiver = contract.get("vintage_waiver")
    vintage_rows, waived_rows = apply_vintage_waiver(vintage_rows, waiver)

    result = build_table_result(
        table,
        partition_mode=partition_mode,
        value_columns=value_columns,
        min_nonnull_frac=min_frac,
        knowledge_date_col=knowledge_col,
        vintage_retention=vintage,
        census_by_column=census_by_column,
        files_sampled=len(all_keys),
        sample_strategy=f"{partition_mode}: {len(groups)} groups x <= {per_group} files/group",
        baseline_id=BASELINE_ID,
        generated_at=_now(),
        notes=[
            "READ-ONLY footer census; no Athena issued (INV-3).",
            f"min_nonnull_frac is provisional ({min_frac}); per-source calibration pending (OP-8/AV-11).",
        ],
    )
    # Fold per-group value rows + vintage rows into the result's gate/warn lists (waived vintage
    # rows land in WARN, and the artifact carries the waiver object itself).
    object.__setattr__(result, "gate_rows", tuple(list(per_group_rows) + list(vintage_rows)))
    object.__setattr__(result, "warn_rows", tuple(list(per_group_warns) + waived_rows))
    d = result.to_dict()
    d["per_group_value_census"] = group_summaries
    if waiver:
        d["vintage_waiver"] = dict(waiver)
    return result, d


def run(tables: list[str], evidence_dir: Path, per_group: int) -> int:
    reg = load_registry()
    known = set(reg.names())
    targets = [t for t in tables if t in known and t not in SKIP_TABLES]
    missing = [t for t in tables if t not in known]
    for m in missing:
        print(f"WARN: unknown table (not in registry): {m}")

    evidence_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "package": "SILVER-V001",
        "generated_at": _now(),
        "baseline_id": BASELINE_ID,
        "mechanism": "parquet_footer_statistics",
        "athena_queries_issued": 0,
        "tables": {},
    }
    hard_fail_total = 0
    for table in targets:
        contract = reg.table(table)
        print(f"[V001] census {table} ...")
        result, d = census_one_table(contract, per_group=per_group)
        (evidence_dir / f"{table}.json").write_text(
            json.dumps(d, indent=2, sort_keys=True), encoding="utf-8"
        )
        passed = d["passed"]
        n_rows = len(d["gate_rows"])
        n_warn = len(d["warn_rows"])
        hard_fail_total += 0 if passed else 1
        summary["tables"][table] = {
            "passed": passed,
            "gate_rows": n_rows,
            "warn_rows": n_warn,
            "files_sampled": d["files_sampled"],
            "kinds": sorted({g["kind"] for g in d["gate_rows"]}),
        }
        verdict = "PASS" if passed else "FAIL"
        print(f"       {verdict}  files={d['files_sampled']}  gate_rows={n_rows}  warn_rows={n_warn}")
        for g in d["gate_rows"]:
            print(f"         - HARD {g['kind']}: {g['detail']}")
        for g in d["warn_rows"]:
            print(f"         - warn {g['kind']}: {g['detail']}")

    (evidence_dir / "value_census_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"[V001] done. tables={len(targets)} hard_fail_tables={hard_fail_total}")
    print(f"[V001] evidence -> {evidence_dir}")
    return hard_fail_total


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="SILVER-V001 canonical value census (footer-only)")
    ap.add_argument("--tables", default="", help="comma-separated table names")
    ap.add_argument("--all", action="store_true", help="census every registry table (minus ML)")
    ap.add_argument(
        "--evidence-dir",
        default=str(_REPO_ROOT / "reports" / "silver_readiness" / "R1_V001_value_census"),
    )
    ap.add_argument("--per-group", type=int, default=3, help="parquet files sampled per partition group")
    args = ap.parse_args(argv)

    if args.all:
        reg = load_registry()
        tables = [t for t in reg.names() if t not in SKIP_TABLES]
    else:
        tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    if not tables:
        ap.error("provide --tables or --all")
    return run(tables, Path(args.evidence_dir), args.per_group)


if __name__ == "__main__":
    raise SystemExit(main())
