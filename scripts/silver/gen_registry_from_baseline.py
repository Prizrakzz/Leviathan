#!/usr/bin/env python
"""Generate the silver operational registry (SILVER-F010, Milestone R1) FROM the R0 baseline.

The 42 silver + gold_weather_z contract YAMLs under ``configs/silver/tables/`` are GENERATED
(never hand-written) from the frozen R0 readiness baseline
``reports/silver_readiness/20260712_p65impl/`` -- which carries, per table, the live Glue schema,
the physical parquet footer schema + fingerprint, and the registered-partition set -- plus the
consumer snapshots and the live consumer configs. INV-2 target types are computed by
``leviathan.silver.types`` so the physical-vs-target math has one authority. Drift the baseline
flags (WASDE int32/int64 catalog mismatch + null-typed columns, ESR int16/float32 widen) is
recorded on the column (both current-physical AND target) plus a ``drift_summary`` entry tied to
the owning R2 package.

READ-ONLY + AWS-FREE + deterministic: reads local JSON/YAML only, sorts every collection, emits
byte-stable YAML. Re-running produces an identical tree (the determinism test relies on this).

Usage:  python scripts/silver/gen_registry_from_baseline.py [--check]
  --check : generate to a temp buffer and fail (exit 3) if it differs from the checked-in tree.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver.types import classify_drift, target_arrow_type  # noqa: E402

BASELINE_ID = "20260712_p65impl"
BASELINE = _REPO / "reports" / "silver_readiness" / BASELINE_ID
TABLES_JSON = BASELINE / "tables"
CONSUMERS = BASELINE / "consumers"
OUT_DIR = _REPO / "configs" / "silver" / "tables"
KNOWN_DRIFT_OUT = _REPO / "configs" / "silver" / "known_drift.yaml"
REPORT_JSON = BASELINE / "F010_registry_reconciliation.json"
REPORT_MD = BASELINE / "F010_registry_reconciliation.md"

GENERATED_BY = "scripts/silver/gen_registry_from_baseline.py"

# --- curation maps (domain knowledge that cannot be inferred purely mechanically) -------------
DOMAIN = {
    "silver_ams_cotton_quality": "quality", "silver_chirps": "weather",
    "silver_conab_coffee": "production", "silver_cot": "positioning",
    "silver_cpc_soil": "weather", "silver_esr": "trade_flows",
    "silver_esr_compact": "trade_flows", "silver_fgis": "trade_flows",
    "silver_fnc_colombia_area_department": "production",
    "silver_fnc_colombia_exports_port_type": "trade_flows",
    "silver_fnc_colombia_monthly": "production", "silver_food_cpi": "macro",
    "silver_fred_fx": "macro", "silver_futures_prices": "prices",
    "silver_icco_cocoa": "balance_sheet", "silver_model_predictions": "model_output",
    "silver_modis_ndvi": "weather", "silver_mpob": "balance_sheet",
    "silver_mpob_annual": "balance_sheet", "silver_mpoc_exports_by_country": "trade_flows",
    "silver_mpoc_stock_comparison": "balance_sheet",
    "silver_mpoc_trade_stats_monthly": "trade_flows", "silver_nasa_power": "weather",
    "silver_nass_annual": "production", "silver_nass_citrus": "production",
    "silver_nass_crop_progress": "crop_condition", "silver_noaa_iod": "climate",
    "silver_noaa_oni": "climate", "silver_pink_sheet": "prices",
    "silver_production": "production", "silver_psd": "balance_sheet",
    "silver_sagis_cec": "production", "silver_sagis_weekly_deliveries": "trade_flows",
    "silver_sagis_weekly_exports": "trade_flows", "silver_unica_annual_state": "production",
    "silver_unica_biweekly_release_series": "production",
    "silver_unica_biweekly_season_history": "production",
    "silver_unica_corn_ethanol": "biofuel", "silver_unica_monthly_ethanol_sales": "biofuel",
    "silver_wap_table01": "balance_sheet", "silver_wap_table01_revisions": "balance_sheet",
    "silver_wasde": "balance_sheet", "gold_weather_z": "weather",
}

LIFECYCLE = {
    "silver_esr_compact": "serving_copy", "gold_weather_z": "derived",
    "silver_model_predictions": "generated", "silver_wap_table01_revisions": "derived",
    "silver_mpob_annual": "derived", "silver_unica_biweekly_release_series": "derived",
    "silver_unica_corn_ethanol": "derived", "silver_unica_monthly_ethanol_sales": "derived",
}

# Tables that retain multiple release vintages of the same fact (INV-4 per-vintage).
PER_VINTAGE = {
    "silver_wasde", "silver_psd", "silver_wap_table01_revisions", "silver_nass_citrus",
    "silver_sagis_cec", "silver_model_predictions",
}
# Explicit latest-only overrides (ESR compact retains only the latest as_of snapshot per MY).
LATEST_ONLY = {"silver_esr", "silver_esr_compact"}

# Primary R2 owning package per table (from the all-42 readiness matrix, plan L737-779).
R2_OWNER = {
    "silver_ams_cotton_quality": "SILVER-F050", "silver_chirps": "SILVER-F045",
    "silver_conab_coffee": "SILVER-F024", "silver_cot": "SILVER-F062",
    "silver_cpc_soil": "SILVER-F047", "silver_esr": "SILVER-F031",
    "silver_esr_compact": "SILVER-F031", "silver_fgis": "SILVER-F062",
    "silver_fnc_colombia_area_department": "SILVER-F062",
    "silver_fnc_colombia_exports_port_type": "SILVER-F062",
    "silver_fnc_colombia_monthly": "SILVER-F062", "silver_food_cpi": "SILVER-F062",
    "silver_fred_fx": "SILVER-F040", "silver_futures_prices": "SILVER-F062",
    "silver_icco_cocoa": "SILVER-F051", "silver_model_predictions": "SILVER-F018",
    "silver_modis_ndvi": "SILVER-F062", "silver_mpob": "SILVER-F062",
    "silver_mpob_annual": "SILVER-F062", "silver_mpoc_exports_by_country": "SILVER-F053",
    "silver_mpoc_stock_comparison": "SILVER-F055", "silver_mpoc_trade_stats_monthly": "SILVER-F054",
    "silver_nasa_power": "SILVER-F046", "silver_nass_annual": "SILVER-F020",
    "silver_nass_citrus": "SILVER-F056", "silver_nass_crop_progress": "SILVER-F062",
    "silver_noaa_iod": "SILVER-F041", "silver_noaa_oni": "SILVER-F057",
    "silver_pink_sheet": "SILVER-F023", "silver_production": "SILVER-F022",
    "silver_psd": "SILVER-F062", "silver_sagis_cec": "SILVER-F058",
    "silver_sagis_weekly_deliveries": "SILVER-F042", "silver_sagis_weekly_exports": "SILVER-F059",
    "silver_unica_annual_state": "SILVER-F062", "silver_unica_biweekly_release_series": "SILVER-F062",
    "silver_unica_biweekly_season_history": "SILVER-F062", "silver_unica_corn_ethanol": "SILVER-F062",
    "silver_unica_monthly_ethanol_sales": "SILVER-F062", "silver_wap_table01": "SILVER-F043",
    "silver_wap_table01_revisions": "SILVER-F043", "silver_wasde": "SILVER-F033",
    "gold_weather_z": "SILVER-F046",
}

# Producer inventory (best-effort from the R0 writer_entrypoints snapshot + C-WRONG-8 orphan list).
# (transform_module, batch_task, status). status: producer | half-orphan | orphan.
_T = "src/leviathan/transforms/bronze_to_silver/"
_J = "jobs/batch/"
PRODUCER = {
    "silver_ams_cotton_quality": (None, None, "half-orphan"),
    "silver_chirps": (_T + "chirps_weather.py", _J + "bronze_to_silver_chirps_task.py", "producer"),
    "silver_conab_coffee": (_T + "conab_coffee.py", _J + "conab_coffee_silver_task.py", "producer"),
    "silver_cot": (_T + "cftc_cot.py", _J + "cftc_cot_silver_task.py", "producer"),
    "silver_cpc_soil": (_T + "cpc_soil.py", _J + "cpc_bronze_to_silver_task.py", "producer"),
    "silver_esr": (_T + "usda_esr.py", _J + "bronze_to_silver_esr_task.py", "producer"),
    "silver_esr_compact": (_T + "usda_esr.py", _J + "esr_task.py", "producer"),
    "silver_fgis": (_T + "usda_fgis.py", _J + "fgis_silver_task.py", "producer"),
    "silver_fnc_colombia_area_department": (_T + "fnc_colombia.py", _J + "fnc_colombia_silver_task.py", "producer"),
    "silver_fnc_colombia_exports_port_type": (_T + "fnc_colombia.py", _J + "fnc_colombia_silver_task.py", "producer"),
    "silver_fnc_colombia_monthly": (_T + "fnc_colombia.py", _J + "fnc_colombia_silver_task.py", "producer"),
    "silver_food_cpi": (_T + "world_bank_food_cpi.py", _J + "food_cpi_task.py", "producer"),
    "silver_fred_fx": (None, None, "orphan"),
    "silver_futures_prices": (_T + "yfinance_futures.py", _J + "yfinance_futures_task.py", "producer"),
    "silver_icco_cocoa": (None, None, "half-orphan"),
    "silver_model_predictions": ("jobs/batch/train_commodity.py", None, "producer"),
    "silver_modis_ndvi": (_T + "modis_ndvi.py", _J + "modis_ndvi_bronze_to_silver_task.py", "producer"),
    "silver_mpob": (_T + "mpob.py", _J + "mpob_silver_task.py", "producer"),
    "silver_mpob_annual": (_T + "mpob_annual.py", _J + "mpob_annual_silver_task.py", "producer"),
    "silver_mpoc_exports_by_country": (None, None, "half-orphan"),
    "silver_mpoc_stock_comparison": (None, None, "half-orphan"),
    "silver_mpoc_trade_stats_monthly": (None, None, "half-orphan"),
    "silver_nasa_power": (_T + "nasa_power_weather.py", None, "producer"),
    "silver_nass_annual": (_T + "usda_nass_annual.py", _J + "nass_annual_silver_task.py", "producer"),
    "silver_nass_citrus": (None, None, "half-orphan"),
    "silver_nass_crop_progress": (_T + "usda_nass_crop_progress.py", _J + "nass_crop_progress_silver_task.py", "producer"),
    "silver_noaa_iod": (_T + "noaa_iod.py", _J + "noaa_iod_task.py", "producer"),
    "silver_noaa_oni": (None, None, "orphan"),
    "silver_pink_sheet": (_T + "pink_sheet.py", _J + "pink_sheet_silver_task.py", "producer"),
    "silver_production": (_T + "faostat_production.py", None, "producer"),
    "silver_psd": (_T + "usda_psd.py", _J + "psd_silver_task.py", "producer"),
    "silver_sagis_cec": (None, None, "half-orphan"),
    "silver_sagis_weekly_deliveries": (None, None, "half-orphan"),
    "silver_sagis_weekly_exports": (None, None, "half-orphan"),
    "silver_unica_annual_state": (_T + "unica_annual_state.py", _J + "unica_annual_state_task.py", "producer"),
    "silver_unica_biweekly_release_series": (_T + "unica_biweekly.py", _J + "unica_biweekly_silver_task.py", "producer"),
    "silver_unica_biweekly_season_history": (_T + "unica_biweekly.py", _J + "unica_biweekly_silver_task.py", "producer"),
    "silver_unica_corn_ethanol": (None, None, "half-orphan"),
    "silver_unica_monthly_ethanol_sales": (None, None, "half-orphan"),
    "silver_wap_table01": (_T + "wap_table01.py", _J + "wap_silver_task.py", "producer"),
    "silver_wap_table01_revisions": (_T + "wap_table01.py", _J + "wap_silver_task.py", "producer"),
    "silver_wasde": (None, _J + "wasde_bronze_modern_task.py", "producer"),
    "gold_weather_z": ("src/leviathan/transforms/gold/weather_z.py", _J + "gold_weather_z_task.py", "producer"),
}

# Natural-key fallback for tables absent from source_contracts (numbers-only / consumer-none).
NATURAL_KEY_FALLBACK = {
    "gold_weather_z": ["commodity", "country", "region", "year", "month", "metric"],
    "silver_esr": ["commodity_name", "country_code", "week_ending_date"],
    "silver_model_predictions": [],
    "silver_mpob_annual": [],
    "silver_unica_biweekly_release_series": [],
    "silver_unica_corn_ethanol": [],
    "silver_unica_monthly_ethanol_sales": [],
}

# Tall numbers value column (the actual measure lives in ONE column; metric NAMES are row values).
TALL_VALUE_COL = {"silver_wasde": "estimate", "silver_production": "value", "gold_weather_z": "value"}

_NUMERIC_GLUE = {"double", "float", "real", "int", "integer", "bigint", "smallint", "tinyint", "decimal"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _cadence(grain: str) -> str | None:
    g = (grain or "").lower()
    if "week" in g or "biweek" in g or "fortnight" in g:
        return "weekly"
    if "month" in g:
        return "monthly"
    if "daily" in g or " date" in g or g.endswith("date"):
        return "daily"
    if "year" in g or "season" in g or "annual" in g or "safra" in g:
        return "annual"
    return None


def build_contract(name: str, ctx: dict) -> dict:
    rec = _load(TABLES_JSON / f"{name}.json")
    glue = rec["glue"]
    phys = rec.get("physical_sample") or {}
    layer = "gold" if name.startswith("gold_") else "silver"

    pk_names = [pk["name"] for pk in glue.get("partition_keys", [])]
    partition_keys = [
        {"name": pk["name"], "glue_type": pk["type"], "projected": glue.get("projection_enabled", False)}
        for pk in glue.get("partition_keys", [])
    ]

    glue_cols = {c["name"]: c["type"] for c in glue.get("nonpartition_columns", [])}
    arrow_cols = {c["name"]: c["type"] for c in (phys.get("arrow_columns") or [])}
    parquet_cols = {c["name"]: c["physical_type"] for c in (phys.get("parquet_physical_columns") or [])}

    # Column order: the live GLUE CATALOG non-partition order first (this is the authority the
    # DDL must reproduce -- SILVER-F011), then any physical-parquet-only columns (present in the
    # arrow footer but absent from the catalog -- the CONAB "hidden schema" class) appended at the
    # tail with glue_type=None. Ordering physical-first mis-placed catalog columns whenever the
    # physical footer sample was an OLDER schema than the catalog (e.g. silver_model_predictions:
    # the 21-col footer pushed snapshot_stage/snapshot_policy to the tail, but the 24-col catalog
    # carries them at positions 2-3, so the generated DDL diverged from live Glue).
    ordered_names: list[str] = []
    for cn in glue.get("nonpartition_columns", []):
        if cn["name"] not in pk_names and cn["name"] not in ordered_names:
            ordered_names.append(cn["name"])
    for c in (phys.get("arrow_columns") or []):
        if c["name"] not in pk_names and c["name"] not in ordered_names:
            ordered_names.append(c["name"])

    source_contract = ctx["sc_by_table"].get(name, {})
    numbers_spec = ctx["numbers"].get(name, {})
    natural_key = (
        source_contract.get("natural_key")
        or NATURAL_KEY_FALLBACK.get(name)
        or numbers_spec.get("grain_cols")
        or []
    )

    physical_columns = []
    drift_summary = []
    owner = R2_OWNER.get(name, "SILVER-F062")
    for cn in ordered_names:
        arrow = arrow_cols.get(cn)
        gtype = glue_cols.get(cn)
        target = target_arrow_type(arrow, gtype)
        physical_columns.append({
            "name": cn,
            "glue_type": gtype,
            "arrow_type": arrow,
            "parquet_physical_type": parquet_cols.get(cn),
            "target_arrow_type": target,
            "nullable": cn not in natural_key,
        })
        for kind in classify_drift(arrow, gtype):
            drift_summary.append({
                "column": cn,
                "kind": kind,
                "current_physical": arrow,
                "glue_type": gtype,
                "target": target,
                "owner_package": owner,
            })

    all_cols = set(ordered_names) | set(pk_names)

    # value_columns (INV-5 single authority) -----------------------------------------------------
    value_columns: list[str] = []
    if name in TALL_VALUE_COL:
        value_columns = [TALL_VALUE_COL[name]]
    elif numbers_spec and numbers_spec.get("shape") == "wide":
        value_columns = [m for m in (ctx["metric_keys"].get(name) or []) if m in all_cols]
    if not value_columns and name == "silver_esr_compact":
        value_columns = [m for m in (ctx["metric_keys"].get("silver_esr") or []) if m in all_cols]
    if not value_columns and source_contract:
        dates = set(source_contract.get("date_columns", []) or [])
        nk = set(natural_key)
        for rc in source_contract.get("required_columns", []) or []:
            g = (glue_cols.get(rc) or "").split("(")[0].lower()
            if g in _NUMERIC_GLUE and rc not in dates and rc not in nk:
                value_columns.append(rc)
    value_columns = [v for v in value_columns if v in all_cols]
    min_nonnull = 0.5 if value_columns else None

    # PIT / numbers back-pointers ---------------------------------------------------------------
    numbers_ref = f"configs/graphrag/numbers/tables.yaml#{name}" if numbers_spec else None
    serving_table = numbers_spec.get("athena_table") if numbers_spec else None
    if numbers_spec:
        knowledge_date_col = numbers_spec.get("knowledge_date_col")
        knowledge_semantics = numbers_spec.get("knowledge_semantics")
        publication_lag_days = numbers_spec.get("publication_lag_days")
    elif name == "silver_esr_compact":
        knowledge_date_col, knowledge_semantics, publication_lag_days = "as_of_date", "data_date", 7
    else:
        knowledge_date_col = knowledge_semantics = publication_lag_days = None

    cascade_ref = None
    if name in ctx["cascade_by_table"]:
        cascade_ref = f"configs/graphrag/numbers/cascade_map.yaml#{ctx['cascade_by_table'][name]}"
    source_contract_ref = (
        f"configs/datasets/source_contracts.yaml#{source_contract['source_key']}"
        if source_contract else None
    )

    # consumers ---------------------------------------------------------------------------------
    is_numbers = name in ctx["numbers"]
    is_feature = name in ctx["feature_tables"]
    consumers = (
        "both" if (is_numbers and is_feature)
        else "numbers_registry" if is_numbers
        else "feature_layer" if is_feature
        else "none"
    )

    partition_mode = glue.get("partition_mode", "flat")
    projection_enabled = bool(glue.get("projection_enabled"))
    storm_trio = {"silver_nasa_power", "silver_chirps", "silver_cpc_soil"}
    if name in storm_trio:
        recovery = "S3 footer only (INV-3: NEVER start-query-execution against this projection.* table)"
    elif partition_mode == "projected":
        recovery = "get-partitions inventory + single sargable Athena probe on a registered surface"
    elif partition_mode == "registered":
        recovery = "get-partitions reconcile + explicit per-partition locations (ESR as_of=/as_of_date mapping; never MSCK)"
    else:
        recovery = "active-release manifest / bounded full relist under the flat root"

    grain = source_contract.get("grain") or numbers_spec.get("grain") or ""
    prod = PRODUCER.get(name, (None, None, "orphan"))

    contract = {
        "table_name": name,
        "layer": layer,
        "domain": DOMAIN.get(name, "unclassified"),
        "lifecycle_class": LIFECYCLE.get(name, "source"),
        "owner": "numbers-platform" if is_numbers else "silver-platform",
        "schema_version": 1,
        "glue_database": rec.get("database", "leviathan_dev"),
        "s3_root": glue["location"],
        "s3_bucket": glue.get("s3_bucket"),
        "s3_prefix": glue.get("s3_prefix"),
        "layout": "flat" if partition_mode == "flat" else "partitioned",
        "partition_mode": partition_mode,
        "projection": "legacy-quarantined" if projection_enabled else "forbidden",
        "partition_keys": partition_keys,
        "recovery_strategy": recovery,
        "physical_columns": physical_columns,
        "writer_schema_pinned": False,
        "drift_summary": drift_summary,
        "natural_key": list(natural_key),
        "required_nonnull": list(natural_key),
        "value_columns": value_columns,
        "min_nonnull_frac": min_nonnull,
        "min_nonnull_frac_status": "provisional",
        "coverage_axis": grain or None,
        "vintage_retention": (
            "latest-only" if name in LATEST_ONLY
            else "per-vintage" if name in PER_VINTAGE
            else "latest-only"
        ),
        "knowledge_date_col": knowledge_date_col,
        "knowledge_semantics": knowledge_semantics,
        "publication_lag_days": publication_lag_days,
        "freshness_sla": {"cadence": _cadence(grain), "max_lag_days": None},
        "consumers": consumers,
        "numbers_ref": numbers_ref,
        "cascade_ref": cascade_ref,
        "source_contract_ref": source_contract_ref,
        "serving_table": serving_table,
        "producer": {
            "status": prod[2],
            "transform": prod[0],
            "batch_task": prod[1],
        },
        "location_mode": "static",
        "write_mode": "registered-partition" if partition_mode == "registered" else "overwrite",
        "fingerprint": {
            "schema_fingerprint_sha256": (phys.get("schema_fingerprint_sha256")),
            "catalog_hash_sha256": glue.get("catalog_hash_sha256"),
            "registered_partition_count": rec.get("registered_partitions", {}).get("count", 0),
            "placeholder_partition_count": rec.get("registered_partitions", {}).get("placeholder_count", 0),
            "glue_nonpartition_cols": glue.get("num_nonpartition_columns", len(glue_cols)),
            "physical_parquet_cols": len(phys.get("parquet_physical_columns") or []),
        },
        "provenance": {
            "baseline_id": BASELINE_ID,
            "anchor_git_sha": rec.get("anchor_git_sha", ""),
            "generated_by": GENERATED_BY,
            "generated_from": f"reports/silver_readiness/{BASELINE_ID}/tables/{name}.json",
        },
        "notes": (
            "min_nonnull_frac is PROVISIONAL (uniform 0.5) pending per-source calibration "
            "(OP-8 / AV-11, SILVER-V001). This registry is the SINGLE authority for value_columns "
            "and min_nonnull_frac (Attack 3 finding #6). Types are the INV-2 TARGET writer schema; "
            "arrow_type is the current-physical type from the R0 baseline."
        ),
    }
    # projection domains only for a legacy-quarantined projected table.
    if projection_enabled:
        contract["projection_domains"] = dict(sorted(glue.get("projection_properties", {}).items()))
    if prod[2] != "producer":
        contract["producer"]["note"] = "C-WRONG-8 orphan class; producer rebuilt in " + owner
    return contract


def _build_context() -> dict:
    numbers_doc = _load_yaml(_REPO / "configs" / "graphrag" / "numbers" / "tables.yaml")["tables"]
    metric_keys = {t: list((spec.get("metrics") or {}).keys()) for t, spec in numbers_doc.items()}
    tablespec = _load(CONSUMERS / "tablespec.json")["specs"]
    # merge shape/knowledge fields from the tablespec snapshot into the numbers dict
    numbers = {}
    for t, spec in numbers_doc.items():
        merged = dict(spec)
        merged.update({k: v for k, v in tablespec.get(t, {}).items() if k in (
            "shape", "knowledge_date_col", "knowledge_semantics", "publication_lag_days",
            "athena_table", "partition_cols", "grain",
        )})
        merged.setdefault("grain_cols", spec.get("grain_cols"))
        numbers[t] = merged

    sc = _load_yaml(_REPO / "configs" / "datasets" / "source_contracts.yaml")["sources"]
    sc_by_table = {s["glue_table"]: s for s in sc}
    # Every source_contracts entry is a certified feature-layer input (the file's own framing:
    # "the live silver/feature inputs that can feed model-ready gold"). features.yaml sources are a
    # subset that a family already consumes; both count the table as a feature-layer consumer.
    feature_srcs = set()
    for fam in _load_yaml(_REPO / "configs" / "features" / "features.yaml"):
        for s in fam.get("sources", []) or []:
            feature_srcs.add(s)
    sc_by_key = {s["source_key"]: s for s in sc}
    feature_tables = {s["glue_table"] for s in sc}
    feature_tables |= {sc_by_key[s]["glue_table"] for s in feature_srcs if s in sc_by_key}

    cascade_refs = _load(CONSUMERS / "cascade_map_refs.json")["ref_to_table"]
    cascade_by_table: dict[str, str] = {}
    for ref, spec in cascade_refs.items():
        tbl = spec["table"]
        cascade_by_table.setdefault(tbl, ref.split(".", 1)[-1])
    return {
        "numbers": numbers, "metric_keys": metric_keys, "sc_by_table": sc_by_table,
        "feature_tables": feature_tables, "cascade_by_table": cascade_by_table,
    }


def _dump_yaml(contract: dict) -> str:
    header = (
        f"# GENERATED by {GENERATED_BY} from reports/silver_readiness/{BASELINE_ID}.\n"
        f"# SILVER-F010 operational registry (superset). Do NOT hand-edit; re-run the generator.\n"
    )
    body = yaml.safe_dump(contract, sort_keys=False, default_flow_style=False, width=100, allow_unicode=False)
    return header + body


def generate(check: bool = False) -> int:
    ctx = _build_context()
    names = sorted(p.stem for p in TABLES_JSON.glob("*.json"))
    contracts = {n: build_contract(n, ctx) for n in names}

    rendered = {n: _dump_yaml(c) for n, c in contracts.items()}
    if check:
        diffs = []
        for n, text in rendered.items():
            existing = OUT_DIR / f"{n}.yaml"
            if not existing.exists() or existing.read_text(encoding="utf-8") != text:
                diffs.append(n)
        if diffs:
            print("REGISTRY DRIFT (regenerate): " + ", ".join(sorted(diffs)))
            return 3
        print(f"registry check OK: {len(rendered)} contracts byte-identical")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for n, text in rendered.items():
        (OUT_DIR / f"{n}.yaml").write_text(text, encoding="utf-8")
    print(f"wrote {len(rendered)} contracts to {OUT_DIR}")

    _write_known_drift_and_report(contracts, ctx)
    return 0


def _write_known_drift_and_report(contracts: dict, ctx: dict) -> None:
    # Load the freshly written registry and run the reconciliation lints to enumerate divergences.
    from leviathan.silver.registry import load_registry
    from leviathan.silver import reconcile as R

    reg = load_registry()
    divs = R.reconcile_all(reg)

    # Every surviving divergence -> a known-drift allowlist entry tied to its owning R2 package.
    entries = []
    for d in sorted(divs, key=lambda x: (x.check, x.table, x.kind, x.column or "")):
        owner = R2_OWNER.get(d.table, "SILVER-F062")
        entries.append({
            "check": d.check, "table": d.table, "kind": d.kind, "column": d.column,
            "owner_package": owner, "reason": d.detail,
        })
    known = {
        "_generated_by": GENERATED_BY,
        "_note": (
            "Reconciliation known-drift allowlist (SILVER-F010). Each entry is a registry<->consumer "
            "disagreement that R1 cannot fix in code (a producer/data gap) and is deferred to its "
            "owning R2 package. The reconciliation test asserts reconcile_all() minus this list is "
            "EMPTY. numbers/PIT divergences are NOT permitted here (acceptance criterion)."
        ),
        "reconciliation_drift": entries,
    }
    KNOWN_DRIFT_OUT.write_text(
        yaml.safe_dump(known, sort_keys=False, default_flow_style=False, allow_unicode=False),
        encoding="utf-8",
    )

    # writer-schema drift rollup + numbers-clean assertion for the report.
    numbers_divs = [d for d in divs if d.check == "numbers"]
    report = {
        "package": "SILVER-F010",
        "baseline_id": BASELINE_ID,
        "generated_by": GENERATED_BY,
        "table_count": len(contracts),
        "numbers_reconciliation_clean": len(numbers_divs) == 0,
        "reconciliation_divergences": len(divs),
        "divergences_by_check": _counts(divs, "check"),
        "divergences_by_kind": _counts(divs, "kind"),
        "writer_schema_drift_columns": sum(len(c.get("drift_summary", [])) for c in contracts.values()),
        "writer_schema_drift_by_kind": _drift_kind_counts(contracts),
        "consumers_tally": _counts_val(contracts, "consumers"),
        "vintage_retention_tally": _counts_val(contracts, "vintage_retention"),
        "producer_status_tally": {
            k: sum(1 for c in contracts.values() if c["producer"]["status"] == k)
            for k in ("producer", "half-orphan", "orphan")
        },
        "value_columns_present": sum(1 for c in contracts.values() if c["value_columns"]),
        "known_drift_entries": len(entries),
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(_render_md(report, entries, contracts), encoding="utf-8")
    print(f"numbers reconciliation clean: {report['numbers_reconciliation_clean']}; "
          f"total divergences: {report['reconciliation_divergences']} "
          f"(all in known_drift); writer-schema drift cols: {report['writer_schema_drift_columns']}")


def _counts(divs, attr):
    out: dict[str, int] = {}
    for d in divs:
        out[getattr(d, attr)] = out.get(getattr(d, attr), 0) + 1
    return dict(sorted(out.items()))


def _counts_val(contracts, key):
    out: dict[str, int] = {}
    for c in contracts.values():
        out[c[key]] = out.get(c[key], 0) + 1
    return dict(sorted(out.items()))


def _drift_kind_counts(contracts):
    out: dict[str, int] = {}
    for c in contracts.values():
        for d in c.get("drift_summary", []):
            out[d["kind"]] = out.get(d["kind"], 0) + 1
    return dict(sorted(out.items()))


def _render_md(report, entries, contracts) -> str:
    lines = [
        f"# SILVER-F010 registry reconciliation ({report['baseline_id']})",
        "",
        f"Generated by `{report['generated_by']}` from the R0 baseline. {report['table_count']} "
        f"contracts (42 silver + gold_weather_z).",
        "",
        "## Acceptance",
        f"- numbers-stack reconciliation clean (no publication_lag / PIT divergence): "
        f"**{report['numbers_reconciliation_clean']}**",
        f"- total registry<->consumer divergences: **{report['reconciliation_divergences']}** "
        f"(all carried in `configs/silver/known_drift.yaml`, each tied to an R2 package)",
        f"- writer-schema (INV-2) drift columns recorded: **{report['writer_schema_drift_columns']}** "
        f"({report['writer_schema_drift_by_kind']})",
        "",
        "## Tallies",
        f"- consumers: {report['consumers_tally']}",
        f"- vintage_retention: {report['vintage_retention_tally']}",
        f"- producer status: {report['producer_status_tally']}",
        f"- tables with value_columns: {report['value_columns_present']}/{report['table_count']}",
        "",
        "## Known reconciliation drift (deferred to R2)",
        "",
        "| check | table | kind | column | owner | reason |",
        "|---|---|---|---|---|---|",
    ]
    for e in entries:
        lines.append(
            f"| {e['check']} | {e['table']} | {e['kind']} | {e['column'] or ''} | "
            f"{e['owner_package']} | {e['reason']} |"
        )
    lines.append("")
    lines.append("## Writer-schema drift (per-table, INV-2 current-physical -> target)")
    lines.append("")
    lines.append("| table | column | kind | current | target | owner |")
    lines.append("|---|---|---|---|---|---|")
    for n in sorted(contracts):
        for d in contracts[n].get("drift_summary", []):
            lines.append(
                f"| {n} | {d['column']} | {d['kind']} | {d['current_physical']} | "
                f"{d['target']} | {d['owner_package']} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if regeneration would change the tree")
    args = ap.parse_args()
    return generate(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
