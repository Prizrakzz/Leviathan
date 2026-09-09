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
    apply_absent_group_waiver,
    apply_full_scan,
    apply_vintage_waiver,
    census_column,
    evaluate_gate,
    evaluate_sample_divergence,
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


def _parquets_under(s3, prefix: str, per_group: int, page_cap: int = 6,
                    empty_page_cap: int = 200) -> list[str]:
    """Up to ``per_group`` parquet keys spread across the (bounded) listing under ``prefix``.

    THE EMPTY-WINDOW EXTENSION (found 2026-09-09 while censusing the four sibling writers). The
    6-page x 400-key window is a LIST budget, not a data budget: it counts hidden control-plane
    objects too. ``silver_modis_ndvi`` publishes under ``silver/weather/source=modis_ndvi/``, whose
    ``_manifests/`` and ``_shadow/`` children sort BEFORE ``commodity=`` ('_' is 0x5F, 'c' is 0x63),
    and there are 10,525 hidden parquets there -- so all 2,400 keys in the window were hidden, this
    function returned [], and that table's value census read ZERO files and printed
    "PASS files=0 gate_rows=0" every time it ran. A census that reads nothing passes anything: the
    same vacuity class as the parity gate's SPEC-INVALID panel in this same RCA, on the largest
    silver table in the estate (10,532 canonical objects).

    The window therefore keeps paging -- to a hard ``empty_page_cap`` ceiling -- ONLY while it has
    found zero candidates. That is provably inert for every prefix that yields at least one parquet
    key inside the first ``page_cap`` pages: the key list, and so the spread indices and the sampled
    objects, are byte-identical to before. MEASURED across the whole registry on 2026-09-09: exactly
    four tables sampled zero files, and three of them (silver_ams_gtr, silver_eex_freight,
    silver_moex_agro_indices) have no canonical objects at all and are unaffected. Only modis moves.

    WHAT MOVING MEANS FOR THAT TABLE'S OPERATOR, said plainly. ``silver_modis_ndvi``'s value census
    was VACUOUS and is now LIVE inside a BLOCKING gate: the first non-hidden parquet under its
    prefix appears on LIST page 28, so the old 6-page window returned 0 keys and the table printed
    "PASS files=0" on every run; it now reads 4 of its 10,532 objects (the full-family scan skips it
    at the FULL_SCAN_MAX_FILES cap). Measured PASS on 2026-09-09 -- but this is a gate that can now
    go red where it structurally could not before, and the next scheduled reader is the
    modis_biweekly chain's gate leg, cron(0 9 ? * MON *), next fire 2026-09-14 09:00Z.
    """
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
        if not token or pages >= (page_cap if keys else empty_page_cap):
            break
    if len(keys) <= per_group:
        return keys
    # spread: first, last, and evenly-spaced interior samples (era coverage).
    idxs = sorted({round(i * (len(keys) - 1) / (per_group - 1)) for i in range(per_group)})
    return [keys[i] for i in idxs]


# The bound on the FULL-family scan (NASS GATE RCA docket, 2026-09-09 -- option (a)). A table whose
# canonical family exceeds this reads its footers the sampled way and says so; nothing about the
# gate's verdict depends on the scan, so a fallback is a loss of a second opinion, never of a fence.
# MEASURED against the live estate on 2026-09-09 (LIST-only count of all 52 censused prefixes,
# 23,228 objects): at 2,000 the scan covers 50 of 52 tables and 8,218 objects, and the two that fall
# back are the only ones that could make this expensive -- silver_modis_ndvi (10,532) and
# silver_production (4,478). ~16k additional footer range-GETs on a full --all sweep, well under a
# cent, ~1 minute at 16 workers; a per-table gate run (the usda_nass chain reads 2 tables, 1,486
# objects) pays a few seconds.
# WHERE THAT COST IS PAID, named because it is not a cheap place. census_one_table is called by
# jobs/audit/silver_rebuild_gate.py, so these reads happen INSIDE the blocking gate of a scheduled
# chain -- up to this cap in extra footer range-GETs per table, on top of the 3-per-group sample.
# What they buy is REPORTING, not a verdict (see value_census.apply_full_scan for the proof that
# the scan cannot change a table's colour): an honest KIND, the whole-family fractions in the
# artifact, and the sample_unrepresentative WARN.
FULL_SCAN_MAX_FILES = 2000


def _all_parquets_under(s3, prefix: str, cap: int) -> Optional[list[str]]:
    """EVERY parquet key under ``prefix``, or ``None`` once more than ``cap`` have been seen.

    Deliberately separate from :func:`_parquets_under`, which the SAMPLE uses: the sampled keys must
    stay byte-identical to what this census read before the full scan existed, so the two listings
    never share state. Returns None (rather than a truncated list) past the cap -- a partial family
    scan would be a THIRD estimator, and the point of this pass is to have one that is complete."""
    keys: list[str] = []
    token = None
    while True:
        kw = dict(Bucket=BUCKET, Prefix=prefix, MaxKeys=1000)
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        keys.extend(o["Key"] for o in r.get("Contents", [])
                    if o["Key"].endswith(".parquet") and not _is_hidden(o["Key"]))
        if len(keys) > cap:
            return None
        token = r.get("NextContinuationToken")
        if not token:
            return keys


def full_scan_groups(
    s3,
    groups: dict[str, list[str]],
    prefix: str,
    *,
    cap: int = FULL_SCAN_MAX_FILES,
) -> dict[str, list[str]]:
    """``{group_label: [EVERY parquet key in that group]}``, or ``{}`` if the table exceeds ``cap``.

    Keyed off the groups the sampler already chose, so the full scan speaks about exactly the
    partition groups the gate evaluates and can never introduce one the gate does not know. The cap
    is applied to the TABLE, not the group: a family is scanned whole or not at all, because a
    half-scanned group's ``files_with_stats`` would be neither the sample's claim nor the family's."""
    out: dict[str, list[str]] = {}
    budget = cap
    for label in groups:
        gp = prefix if not label else f"{prefix}{label}/"
        keys = _all_parquets_under(s3, gp, budget)
        if keys is None:
            return {}
        out[label] = keys
        budget -= len(keys)
        if budget < 0:
            return {}
    return out


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


# Footer-read concurrency. Raised 16 -> 32 on 2026-09-09 when the full-family scan multiplied the
# read count: MEASURED on silver_nass_annual's 1,206 objects, 36.0 s at 16 workers, 20.9 s at 32,
# 21.2 s at 48 -- the curve is flat past 32, so 32 is where the extra reads stop costing wall clock.
# Purely a concurrency knob: the keys read, the stats derived and every verdict are identical.
# It is a DEFAULT, so it also raises S3 footer concurrency for the two callers that do not pass one
# -- jobs/audit/silver_rebuild_gate.py and jobs/audit/feature_readiness.py -- on tables the 36.0 /
# 20.9 / 21.2 s curve was not measured on. Behaviour-neutral there too (same keys, same verdicts),
# but unmeasured: if a caller ever needs the old ceiling it passes max_workers=16 explicitly.
def census_one_table(contract: dict, *, per_group: int = 3, max_workers: int = 32) -> tuple[TableCensusResult, dict]:
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
    season_overrides = contract.get("min_nonnull_frac_season_overrides") or None
    # D-SG G1-5: the season floor is a statement about WHEN this census ran, so the month comes
    # from the census clock (the same clock that stamps generated_at), never from the data.
    # KNOWN LIMIT (review m-4): a REPLAY with --asof in another month still gets the wall-clock
    # month's floor -- census_one_table takes no asof today. In production asof ~= now, so this
    # is cosmetic; plumb asof through before ever using replays to relitigate a season verdict.
    as_of_month = datetime.now(timezone.utc).month
    knowledge_col = contract.get("knowledge_date_col")
    vintage = contract.get("vintage_retention")
    projection_domains = contract.get("projection_domains") or {}
    # Declared, user-gated SOURCE ABSENCE of (partition group, value column) pairs. Consumed HERE
    # rather than inside evaluate_gate for the same reason vintage_waiver is: the declaration is a
    # REGISTRY fact, so the gate function itself stays strict and cannot be quietly disarmed by a
    # caller omitting an argument. See apply_absent_group_waiver for the measured trigger (the three
    # cottonseed Tuesdays) and the three fail-closed rules.
    absent_groups = contract.get("value_column_absent_groups") or None

    target_cols = list(dict.fromkeys(value_columns + ([knowledge_col] if knowledge_col else [])))

    groups = sample_groups(s3, prefix, partition_mode, projection_domains, per_group=per_group)
    all_keys = [(g, k) for g, keys in groups.items() for k in keys]

    # THE FULL-FAMILY SCAN (RCA docket option (a), armed 2026-09-09). Every object of every sampled
    # group, footer-only, so the KIND_STATS_UNAVAILABLE clause stops being a 3-file coin-flip and
    # the whole-group non-null fraction can be reported beside the sampled one. FAIL-OPEN by
    # construction and by the except arm below: with no scan the census behaves exactly as it did
    # before this pass existed, so a LIST failure or an oversized family degrades the second opinion
    # and never the gate.
    full_groups: dict[str, list[str]] = {}
    if target_cols and all_keys:
        try:
            full_groups = full_scan_groups(
                s3, groups, prefix if prefix.endswith("/") else prefix + "/")
        except Exception as exc:  # noqa: BLE001 -- the scan is an ADDITION; it may never break the gate
            full_groups = {}
            print(f"       (full-family scan unavailable for {table}: {str(exc)[:120]})")

    # Parallel footer reads (memory: parallelize S3-bound work).
    sampled_keys = {k for _, k in all_keys}
    scan_keys = sorted({k for keys in full_groups.values() for k in keys} - sampled_keys)
    stats_by_key: dict[str, dict] = {}
    if target_cols and all_keys:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(_read_footer_stats, fs, k, target_cols): k
                    for k in [k for _, k in all_keys] + scan_keys}
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
    full_summaries: dict[str, dict] = {}
    for g, keys in groups.items():
        g_census = {}
        g_full = {}
        full_keys = full_groups.get(g) or []
        for col in value_columns:
            fstats = [stats_by_key.get(k, {}).get(col) for k in keys]
            g_census[col] = census_column(fstats, col)
            if len(full_keys) > len(keys):
                g_full[col] = census_column(
                    [stats_by_key.get(k, {}).get(col) for k in full_keys], col)
                # ONLY files_with_stats is taken from the whole group. See apply_full_scan for the
                # proof that this is VERDICT-INERT -- it can only relabel a hard stats_unavailable
                # row as a hard all_nan row, never flip a colour -- and for why the floor
                # deliberately keeps reading the sampled fraction.
                g_census[col] = apply_full_scan(g_census[col], g_full[col])
        label = g or "(flat)"
        g_rows = evaluate_gate(table, g_census, value_columns, min_frac,
                               floor_overrides=floor_overrides,
                               season_floor_overrides=season_overrides,
                               as_of_month=as_of_month)  # value checks only
        # A DECLARED absence is NARRATED (a warn row carrying the approval + the publisher fact);
        # an UNDECLARED one stays a hard fail. The demotion is keyed on this group's label, so it
        # can never reach another commodity's identical-looking row.
        g_rows, g_absent = apply_absent_group_waiver(g_rows, label, absent_groups, value_columns)
        for r in g_rows:
            per_group_rows.append(GateRow(r.table, r.column, r.kind, r.observed, r.threshold,
                                          f"[{label}] {r.detail}"))
        for r in g_absent:
            per_group_warns.append(GateRow(r.table, r.column, r.kind, r.observed, r.threshold,
                                           f"[{label}] {r.detail}"))
        for r in evaluate_warnings(table, g_census, value_columns):
            per_group_warns.append(GateRow(r.table, r.column, r.kind, r.observed, r.threshold,
                                           f"[{label}] {r.detail}"))
        # The floor landmine, COMPUTED and reported (never decided): the sampled and whole-group
        # non-null fractions straddling this column's floor.
        for r in evaluate_sample_divergence(table, g_census, g_full, value_columns, min_frac,
                                            floor_overrides=floor_overrides,
                                            season_floor_overrides=season_overrides,
                                            as_of_month=as_of_month):
            per_group_warns.append(GateRow(r.table, r.column, r.kind, r.observed, r.threshold,
                                           f"[{label}] {r.detail}"))
        group_summaries[label] = {col: g_census[col].to_dict() for col in value_columns}
        if g_full:
            full_summaries[label] = {col: g_full[col].to_dict() for col in value_columns}

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
        ] + ([f"min_nonnull_frac_overrides ACTIVE: {floor_overrides} (OP-8 user-gated per-column "
              "calibration; the gate compared these columns against their calibrated floors)"]
             if floor_overrides else [])
          + ([f"min_nonnull_frac_season_overrides ACTIVE for census month {as_of_month:02d}: "
              f"{season_overrides} (D-SG G1-5 calendar-structural columns; the month's window "
              "floor replaced the per-column floor where one is declared)"]
             if season_overrides else [])
          + ([f"value_column_absent_groups ACTIVE ({absent_groups.get('approved', '?')}): "
              f"{ {g: sorted(c) for g, c in (absent_groups.get('groups') or {}).items()} } -- "
              "these (group, column) pairs are a DECLARED source absence; their stats_unavailable/"
              "all_nan rows are demoted to WARN and appear in warn_rows with the reason. Every "
              "other pair, kind and group stays hard."]
             if absent_groups else [])
          + ([f"FULL-FAMILY SCAN ACTIVE: {sum(len(v) for v in full_groups.values())} objects "
              f"footer-read across {len(full_groups)} groups (the sample is "
              f"{len(all_keys)}). It is REPORTING, NOT A VERDICT: only files_with_stats is taken "
              "from it, and because a file with no statistics also books zero effective non-nulls, "
              "retiring a stats_unavailable row uncovers the all_nan row underneath it -- the scan "
              "can relabel a hard row, never change a table's colour. The floor / all-NaN / "
              "sentinel verdicts all still read the 3-file sample, whose fraction the OP-8 floors "
              "were calibrated against, so WHICH THREE OBJECTS ARE DRAWN still decides them. Where "
              "the sampled and whole-family fractions straddle a floor, a sample_unrepresentative "
              "WARN carries both numbers; that WARN and these fractions are what this pass adds."]
             if full_groups else
             [f"full-family scan SKIPPED (table exceeds the {FULL_SCAN_MAX_FILES}-object cap, or "
              "the listing failed): stats_unavailable is reported from the 3-file sample alone "
              "here, and no whole-family fraction is available to compare a floor verdict "
              "against."]),
    )
    # Fold per-group value rows + vintage rows into the result's gate/warn lists (waived vintage
    # rows land in WARN, and the artifact carries the waiver object itself).
    object.__setattr__(result, "gate_rows", tuple(list(per_group_rows) + list(vintage_rows)))
    object.__setattr__(result, "warn_rows", tuple(list(per_group_warns) + waived_rows))
    d = result.to_dict()
    d["per_group_value_census"] = group_summaries
    if full_summaries:
        d["per_group_full_family_census"] = full_summaries
        d["full_family_files_scanned"] = sum(len(v) for v in full_groups.values())
    if waiver:
        d["vintage_waiver"] = dict(waiver)
    if absent_groups:
        d["value_column_absent_groups"] = dict(absent_groups)
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
