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
# BF-W2 SILVER-F031 option-b: ESR retains one weekly as_of vintage per (slug, week) -- the serving
# compact gains a REGISTERED as_of_date partition dimension (never re-projection). Flipped from the
# pre-BF-W2 latest-only override in the step-1 serving PR (runbook B2_phase0, ESR-R2/R3/R4).
PER_WEEK = {"silver_esr", "silver_esr_compact"}

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
    # BF-W3 step 0.5 (2026-07-15, user-ratified): the R3 producer-repoint. The six core orphan
    # families flip to status=producer pointing at the R2/R3-built artifacts (OA-F050/51/56/57,
    # SB-F040, OB/SB-F042). readiness.evaluate_producer returns BLOCKED on status alone (GATE-02),
    # so the STATUS flip -- not just the transform path -- is load-bearing for the R4 recert.
    "silver_ams_cotton_quality": (_T + "ams_cotton_quality.py", _J + "ams_cotton_quality_task.py", "producer"),
    "silver_chirps": (_T + "chirps_weather.py", _J + "bronze_to_silver_chirps_task.py", "producer"),
    "silver_conab_coffee": (_T + "conab_coffee.py", _J + "conab_coffee_silver_task.py", "producer"),
    "silver_cot": (_T + "cftc_cot.py", _J + "cftc_cot_silver_task.py", "producer"),
    "silver_cpc_soil": (_T + "cpc_soil.py", _J + "cpc_bronze_to_silver_task.py", "producer"),
    # SILVER-F031/F032: bronze_to_silver_esr_task.py is the COMPACT (silver/esr) producer;
    # backfill_silver_usda_esr.py writes the CANONICAL per-partition silver_esr
    # (silver/production/source=usda_esr); esr_task.py is raw->bronze (not a silver producer).
    "silver_esr": (_T + "usda_esr.py", "jobs/ingest/backfill_silver_usda_esr.py", "producer"),
    "silver_esr_compact": (_T + "usda_esr.py", _J + "bronze_to_silver_esr_task.py", "producer"),
    "silver_fgis": (_T + "usda_fgis.py", _J + "fgis_silver_task.py", "producer"),
    "silver_fnc_colombia_area_department": (_T + "fnc_colombia.py", _J + "fnc_colombia_silver_task.py", "producer"),
    "silver_fnc_colombia_exports_port_type": (_T + "fnc_colombia.py", _J + "fnc_colombia_silver_task.py", "producer"),
    "silver_fnc_colombia_monthly": (_T + "fnc_colombia.py", _J + "fnc_colombia_silver_task.py", "producer"),
    "silver_food_cpi": (_T + "world_bank_food_cpi.py", _J + "food_cpi_task.py", "producer"),
    "silver_fred_fx": (_T + "frankfurter_fx.py", _J + "frankfurter_fx_task.py", "producer"),
    "silver_futures_prices": (_T + "yfinance_futures.py", _J + "yfinance_futures_task.py", "producer"),
    "silver_icco_cocoa": (_T + "icco_cocoa.py", _J + "icco_cocoa_task.py", "producer"),
    "silver_model_predictions": ("jobs/batch/train_commodity.py", None, "producer"),
    "silver_modis_ndvi": (_T + "modis_ndvi.py", _J + "modis_ndvi_bronze_to_silver_task.py", "producer"),
    "silver_mpob": (_T + "mpob.py", _J + "mpob_silver_task.py", "producer"),
    "silver_mpob_annual": (_T + "mpob_annual.py", _J + "mpob_annual_silver_task.py", "producer"),
    "silver_mpoc_exports_by_country": (_T + "mpoc_exports_by_country.py", _J + "mpoc_exports_by_country_silver_task.py", "producer"),
    "silver_mpoc_stock_comparison": (_T + "mpoc_stock_comparison.py", _J + "mpoc_stock_comparison_silver_task.py", "producer"),
    "silver_mpoc_trade_stats_monthly": (_T + "mpoc_trade_stats_monthly.py", _J + "mpoc_trade_stats_monthly_silver_task.py", "producer"),
    "silver_nasa_power": (_T + "nasa_power_weather.py", None, "producer"),
    "silver_nass_annual": (_T + "usda_nass_annual.py", _J + "nass_annual_silver_task.py", "producer"),
    "silver_nass_citrus": (_T + "nass_citrus.py", _J + "nass_citrus_task.py", "producer"),
    "silver_nass_crop_progress": (_T + "usda_nass_crop_progress.py", _J + "nass_crop_progress_silver_task.py", "producer"),
    "silver_noaa_iod": (_T + "noaa_iod.py", _J + "noaa_iod_task.py", "producer"),
    "silver_noaa_oni": (_T + "noaa_oni.py", _J + "noaa_oni_task.py", "producer"),
    "silver_pink_sheet": (_T + "pink_sheet.py", _J + "pink_sheet_silver_task.py", "producer"),
    "silver_production": (_T + "faostat_production.py", None, "producer"),
    "silver_psd": (_T + "usda_psd.py", _J + "psd_silver_task.py", "producer"),
    "silver_sagis_cec": (_T + "sagis_cec.py", _J + "sagis_cec_silver_task.py", "producer"),
    "silver_sagis_weekly_deliveries": (_T + "sagis_deliveries.py", _J + "sagis_deliveries_task.py", "producer"),
    "silver_sagis_weekly_exports": (_T + "sagis_weekly_exports.py", _J + "sagis_weekly_exports_silver_task.py", "producer"),
    "silver_unica_annual_state": (_T + "unica_annual_state.py", _J + "unica_annual_state_task.py", "producer"),
    "silver_unica_biweekly_release_series": (_T + "unica_biweekly.py", _J + "unica_biweekly_silver_task.py", "producer"),
    "silver_unica_biweekly_season_history": (_T + "unica_biweekly.py", _J + "unica_biweekly_silver_task.py", "producer"),
    # BF-W3 SCOPE DEFERRAL (step 2, user-ratified): no dedicated producer exists for these two
    # (the F062 fetcher is frozen at the 2020-21 season -- new fetch development, not backfill
    # adoption). They stay half-orphan until an F062 sweep builds their lane.
    "silver_unica_corn_ethanol": (None, None, "half-orphan"),
    "silver_unica_monthly_ethanol_sales": (None, None, "half-orphan"),
    "silver_wap_table01": (_T + "wap_table01.py", _J + "wap_silver_task.py", "producer"),
    "silver_wap_table01_revisions": (_T + "wap_table01.py", _J + "wap_silver_task.py", "producer"),
    "silver_wasde": (None, _J + "wasde_bronze_modern_task.py", "producer"),
    "gold_weather_z": ("src/leviathan/transforms/gold/weather_z.py", _J + "gold_weather_z_task.py", "producer"),
}

# Tables whose producer emits an EXPLICIT pa.schema (INV-2) through the SILVER-F015 common publisher
# (leviathan.silver.flat_producer) -> writer_schema_pinned=True. Each R2/R3 producer lane appends
# ITS OWN restored/adopted tables here (keys are disjoint across lanes). LANE OB
# (SILVER-F052/F053/F054/F055/F058/F059 + the F062 MPOB adoption):
WRITER_SCHEMA_PINNED = {
    "silver_mpoc_exports_by_country", "silver_mpoc_trade_stats_monthly",
    "silver_mpoc_stock_comparison", "silver_sagis_cec", "silver_sagis_weekly_exports",
    "silver_mpob", "silver_mpob_annual",
}
# LANE SA (SILVER-F022/F023/F024): these producers now pin the INV-2 arrow writer schema from the
# registry contract before every write (leviathan.silver.arrow_schema.cast_to_contract). Appended as
# a disjoint update so the set literal above stays owned by LANE OB.
WRITER_SCHEMA_PINNED |= {"silver_production", "silver_pink_sheet", "silver_conab_coffee"}
# LANE W (SILVER-F021/F045/F046/F047 -- the weather family): the three weather producers now write
# THROUGH the pinned pyarrow schemas in leviathan.transforms.bronze_to_silver._weather_schema
# (NASA_POWER_WIDE_SCHEMA / CHIRPS_LONG_SCHEMA / CPC_SOIL_LONG_SCHEMA). Disjoint |= update so the
# literals above stay owned by LANE OB / LANE SA.
WRITER_SCHEMA_PINNED |= {"silver_nasa_power", "silver_chirps", "silver_cpc_soil"}

# LANE W: the weather serving surface is the tall, non-projected gold_weather_z (Phase D-W4); the three
# silver weather tables are DERIVATION INPUTS only. The generator derives serving_table from the numbers
# athena_table (None for weather), so this override records the F046 decision reproducibly. Keys disjoint
# from every other lane's curation.
SERVING_TABLE_OVERRIDE = {
    "silver_nasa_power": "gold_weather_z",
    "silver_chirps": "gold_weather_z",
    "silver_cpc_soil": "gold_weather_z",
}

# LANE L4 knowledge-date declarations (BF-W3 F2 wave, user-ratified 2026-07-15). Three flat
# feature-layer goldens retain multiple release vintages of the same fact (they are in PER_VINTAGE)
# but have no numbers TableSpec to source a knowledge_date_col from, so the PIT/vintage-adequacy
# census (KIND_SINGLE_VINTAGE) had nothing to key on. The step-0 S3 footer pre-check confirmed each
# carries MANY distinct vintages (nass_citrus release_date=129, sagis_cec release_date=273 with the
# column FULLY populated -- 0/2071 null, wap release_month=226), so arming the census gate stays
# green rather than newly hard-failing. Consulted ONLY in the numbers/esr_compact else-branch below
# (the single-derivation-site invariant: numbers_spec + esr_compact win first). Shape mirrors what a
# numbers-backed table emits: (knowledge_date_col, knowledge_semantics, publication_lag_days). wap's
# publication_lag_days is null -- release_month is the vintage stamp itself, no fixed data-date lag.
KNOWLEDGE_DATE_OVERRIDE = {
    "silver_nass_citrus": ("release_date", "vintage", 0),
    "silver_sagis_cec": ("release_date", "vintage", 0),
    "silver_wap_table01_revisions": ("release_month", "year_month", None),
}

# Natural-key fallback for tables absent from source_contracts (numbers-only / consumer-none).
# silver_esr (SILVER-F030 re-baseline): the TRUE physical natural key is the partition tuple plus
# the weekly grain -- the same (country_code, week_ending_date) recurs across market_years and as_of
# vintages, so market_year + as_of_date belong in the key (mirrors silver_esr_compact + the ESR
# source_contract). The numbers grain_cols [commodity_name, country_code, week_ending_date] is the
# WITHIN-partition grain, not a table-wide key.
NATURAL_KEY_FALLBACK = {
    "gold_weather_z": ["commodity", "country", "region", "year", "month", "metric"],
    "silver_esr": ["commodity_code", "market_year", "as_of_date", "country_code", "week_ending_date"],
    "silver_model_predictions": [],
    "silver_mpob_annual": [],
    "silver_unica_biweekly_release_series": [],
    "silver_unica_corn_ethanol": [],
    "silver_unica_monthly_ethanol_sales": [],
}

# Tall numbers value column (the actual measure lives in ONE column; metric NAMES are row values).
TALL_VALUE_COL = {"silver_wasde": "estimate", "silver_production": "value", "gold_weather_z": "value"}

# Deprecated physical columns (SILVER-F030 ESR semantic ADR): retained as nullable compatibility
# columns, never repurposed and never synthesized. ``changes``/``changes_1000mt`` (weekly revision
# to outstanding sales) is absent in many historical FAS records; INV-4 keeps it NULL rather than
# filling 0.0, so it is DEPRECATED at both ESR contracts. Per {table: {column, ...}}.
DEPRECATED_COLUMNS = {
    "silver_esr": {"changes_1000mt"},
    "silver_esr_compact": {"changes_1000mt"},
}

# Per-table appended provenance/ADR note (SILVER-F030+). ESR: the frozen semantic decision record.
EXTRA_NOTES = {
    "silver_esr": (
        " SILVER-F030 ESR ADR (frozen): changes_1000mt is DEPRECATED + nullable -- an absent source "
        "revision stays NULL, never 0.0 (INV-4). market_year is stored as the FAS START year; the "
        "ending-year label = market_year+1 (numbers period_offset:+1). The ESR partition set carries "
        "USDA GROUPINGS (all_wheat=107, grain_sorghum=701, white_wheat=104) that are NOT contract "
        "slugs -> the esr_exports cascade leg fires only for the 7 slug commodities (corn_cbot, "
        "soybeans_cbot, soybean_meal_cbot, soybean_oil_cbot, hard_red_winter_wheat_kcbt, "
        "soft_red_winter_wheat_cbot, hard_red_spring_wheat_mgex). Target additive net-commitment "
        "columns (accumulated_exports_1000mt, current_my_net_sales_1000mt, "
        "current_my_total_commitment_1000mt, next_my_outstanding_sales_1000mt, "
        "next_my_net_sales_1000mt) are specified for BF-W2 (see reports/silver_readiness/R2_esr/)."
    ),
    "silver_esr_compact": (
        " SILVER-F030/F031 ESR ADR (frozen): changes_1000mt DEPRECATED + nullable (INV-4, never 0.0). "
        "vintage_retention=per-week (BF-W2 step-1 serving PR): the SILVER-F031 option-b path adds an "
        "as_of_date REGISTERED partition dimension for per-week vintages (canonical data/catalog "
        "migration is the gated BF-W2 window -- never re-projection). See "
        "reports/silver_readiness/R2_esr/F031_option_b_path.json and the parity proof under the same "
        "prefix."
    ),
    "silver_mpoc_stock_comparison": (
        " SILVER-F055: producer restored on the shared F052 adapter. The source-as-of provenance is "
        "MANDATORY but lives in the RUN/INPUT MANIFEST (not a row column); adding it as a physical "
        "column is a separate additive registry/DDL/Glue migration + compatibility test (deferred "
        "to BF-W3). Conflicting snapshot cells fail closed."
    ),
}

_NUMERIC_GLUE = {"double", "float", "real", "int", "integer", "bigint", "smallint", "tinyint", "decimal"}

# --- LANE SA curation (SILVER-F020 / F024): registry pins that deliberately diverge from the
# DEFECTIVE live catalog captured in the R0 baseline. Reproducible (re-run the generator) rather
# than hand-edited. Keys are disjoint from the other lanes' curation.

# SILVER-F020: silver_nass_annual has 36 physical commodity=canola_ice parquets (1991-2026) HIDDEN by
# a short projection enum. Per the cross-lane R2 convention (checked-in registry/DDL stay == live
# Glue; the gated migration carries the target), the TARGET enum lives in the F020 migration artifact
# (reports/silver_readiness/R2_SA/F020_canola_migration.json), NOT the checked-in registry. Left empty
# so the projection stays == live Glue until the gated SET TBLPROPERTIES apply.
PROJECTION_ENUM_ADDITIONS: dict = {}

# SILVER-F024 / BF-W2 step 3 (runbook Deviation 9): silver_conab_coffee's 12 revision/provenance
# columns were physical-parquet-only (glue_type=None -> R2-adds, invisible to Athena). The registry
# now carries the F024 ADD COLUMNS TARGET (22 catalog cols, Glue types derived from the INV-2
# target) BECAUSE CatalogMigrator._glue_columns does not drop glue_type-null columns -- an additive
# apply from a null-typed registry would send Type: null x12 to Glue update_table (fail-closed
# reject). The gated F024 migration must apply from a SHA that includes this flip; until it does,
# checked-in registry/DDL deliberately lead live Glue by exactly the F024 additive set
# (F024_conab_additive_migration.json is the consistency authority, pinned in tests).
CATALOG_PROMOTE_HIDDEN: set = {"silver_conab_coffee"}

_ARROW_TO_GLUE = {
    "int64": "bigint", "float64": "double", "string": "string", "bool": "boolean",
    "date32[day]": "date", "timestamp[us]": "timestamp", "timestamp[ms]": "timestamp",
}


def _arrow_to_glue(target: str) -> str:
    """Map an INV-2 target arrow type to the equivalent Glue/Athena catalog type (F024 promotion)."""
    t = (target or "").strip().lower()
    if t in _ARROW_TO_GLUE:
        return _ARROW_TO_GLUE[t]
    if t.startswith("timestamp"):
        return "timestamp"
    if t.startswith("date"):
        return "date"
    return "string"


# LANE SA provenance notes (disjoint dict-assignment so the EXTRA_NOTES literal stays LANE E/OB-owned).
EXTRA_NOTES["silver_nass_annual"] = (
    " SILVER-F020: 36 physical commodity=canola_ice parquets (1991-2026) are HIDDEN because the "
    "projection enum omits canola_ice. The producer already writes canola_ice; the checked-in "
    "projection stays == live Glue and the gated SET TBLPROPERTIES migration "
    "(reports/silver_readiness/R2_SA/F020_canola_migration.json) adds canola_ice. Recovery reads S3 "
    "footers, NEVER Athena (INV-3)."
)
EXTRA_NOTES["silver_conab_coffee"] = (
    " SILVER-F024 (OP-4): the 12 revision/provenance columns (region_raw, *_revision_*, "
    "production_revision_streak, is_repeated_survey, repeated_from_survey_number, "
    "survey_content_fingerprint, source_raw_key, source_file_etag, worksheet, parser_version) were "
    "physical-parquet-only R2-adds; as of BF-W2 step 3 the registry carries their catalog Glue types "
    "(the F024 TARGET, 22 cols) so the gated ADD COLUMNS migration "
    "(reports/silver_readiness/R2_SA/F024_conab_additive_migration.json) can apply via "
    "CatalogMigrator without emitting Type: null (runbook Deviation 9). The F024 widen was APPLIED "
    "OUT-OF-BAND on 2026-07-14 (direct ALTER, not CatalogMigrator); live Glue now carries all 22 "
    "cols and CatalogMigrator.plan_table('silver_conab_coffee') NOOPs (manifest-of-record: "
    "sql/athena/migrations/silver/20260714T201146Z_silver_conab_coffee_additive_update.json). The "
    "widened producer reproduces all 22. The orphan EAV "
    "silver/production/source=conab/ is classified in place (F060), not deleted here."
)

# LANE W provenance notes (SILVER-F021/F044/F045/F046/F047; disjoint assignment).
EXTRA_NOTES["silver_nasa_power"] = (
    " SILVER-F021: WIDE producer (nasa_power_bronze_to_silver) restored to the live wide catalog + "
    "source_file_name; NASA -999 sentinels scrubbed; unknown params fail closed; solar excluded. "
    "SILVER-F046: DERIVATION-INPUT ONLY -- the weather serving surface is gold_weather_z (tall monthly "
    "z). SILVER-F047 freshness gap: nasa_power silver ends at 2024 (no 2025/2026) -- a B1 backfill line "
    "item. SILVER-F047: numbers-serving is quarantined to gold_weather_z (tables.yaml quarantined:true); "
    "the projected month-grain layout is the deproject+compact target (BF-W1, commodity+year registered "
    "grain, year= path segment preserved for the feature extractor)."
)
EXTRA_NOTES["silver_chirps"] = (
    " SILVER-F045: on-S3 silver value is NaN where silver (2026-05-16) predates the re-ingested bronze "
    "(2026-06-16); the BF-W1 rebuild reads real precip and writes THROUGH the F047 registered-compaction "
    "writer (jobs/batch/compact_weather_silver_task.py), never the plain --force-overwrite projected "
    "path. SILVER-F044: a partition is written iff >=1 valid obs exists (classify_availability); a "
    "404/empty date is a typed availability result, never a null-filled map. SILVER-F046: "
    "DERIVATION-INPUT ONLY (drought_z serves from gold_weather_z). SILVER-V002 freshness "
    "(base_jobs.select_partitions_to_write) refreshes any partition whose bronze is newer than silver."
)
EXTRA_NOTES["silver_cpc_soil"] = (
    " SILVER-F046: DERIVATION-INPUT ONLY (weather serves from gold_weather_z); producer pins the LONG "
    "arrow schema. SILVER-F047: projected month-grain is the deproject+compact target (BF-W1, "
    "commodity+year registered grain, year= path segment preserved). OP-5: cpc_soil silver "
    "value-populatedness is an open probe -- the value census (SILVER-V001) is the gate."
)


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
    deprecated_cols = DEPRECATED_COLUMNS.get(name, set())
    promote_hidden = name in CATALOG_PROMOTE_HIDDEN
    for cn in ordered_names:
        arrow = arrow_cols.get(cn)
        gtype = glue_cols.get(cn)
        target = target_arrow_type(arrow, gtype)
        # SILVER-F024: promote a physical-parquet-only (glue_type=None) column into a catalog column
        # by deriving its Glue type from the INV-2 target -- the additive-migration TARGET schema.
        if gtype is None and promote_hidden:
            gtype = _arrow_to_glue(target)
        col: dict = {
            "name": cn,
            "glue_type": gtype,
            "arrow_type": arrow,
            "parquet_physical_type": parquet_cols.get(cn),
            "target_arrow_type": target,
            "nullable": cn not in natural_key,
        }
        if cn in deprecated_cols:
            col["deprecated"] = True
        physical_columns.append(col)
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
        # the compact IS the physical table behind the silver_esr numbers spec -- its PIT fields
        # mirror that spec's BF-W2 vintage flip (per-week as_of vintages; the as_of stamp is the
        # publication event, so no +7d data_date lag).
        knowledge_date_col, knowledge_semantics, publication_lag_days = "as_of_date", "vintage", 0
    else:
        # LANE L4 (BF-W3): a flat feature-layer golden with no numbers TableSpec can still declare
        # its knowledge date reproducibly (arms the value_census vintage-adequacy check). Consulted
        # HERE ONLY so the numbers_spec + esr_compact derivations above always win first.
        kd = KNOWLEDGE_DATE_OVERRIDE.get(name)
        if kd:
            knowledge_date_col, knowledge_semantics, publication_lag_days = kd
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
        "writer_schema_pinned": name in WRITER_SCHEMA_PINNED,
        "drift_summary": drift_summary,
        "natural_key": list(natural_key),
        "required_nonnull": list(natural_key),
        "value_columns": value_columns,
        "min_nonnull_frac": min_nonnull,
        "min_nonnull_frac_status": "provisional",
        "coverage_axis": grain or None,
        "vintage_retention": (
            "per-week" if name in PER_WEEK
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
        "serving_table": SERVING_TABLE_OVERRIDE.get(name, serving_table),
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
            + EXTRA_NOTES.get(name, "")
        ),
    }
    # projection domains only for a legacy-quarantined projected table.
    if projection_enabled:
        contract["projection_domains"] = dict(sorted(glue.get("projection_properties", {}).items()))
        # SILVER-F020: append registry-pinned enum values the DEFECTIVE live catalog omits (canola).
        for pkey, extra_vals in PROJECTION_ENUM_ADDITIONS.get(name, {}).items():
            cur = contract["projection_domains"].get(pkey, "")
            vals = [v for v in cur.split(",") if v]
            for ev in extra_vals:
                if ev not in vals:
                    vals.append(ev)
            contract["projection_domains"][pkey] = ",".join(vals)
    if prod[2] != "producer":
        contract["producer"]["note"] = "C-WRONG-8 orphan class; producer rebuilt in " + owner
    _apply_curation_overrides(name, contract)
    return contract


# ── LANE M curation overrides (R2 verify fix): hand-curation gets a REPRODUCIBLE home here, never in
# the generated YAMLs. The F036 WASDE additive governed columns + natural-key/coverage revisions were
# hand-edited into configs/silver/tables/silver_wasde.yaml and broke the generated-never-hand-written
# invariant (test_checked_in_tree_matches_fresh_render + --check exit 3). Encoding them as generator
# curation (the WRITER_SCHEMA_PINNED / EXTRA_NOTES precedent) makes the contract regenerate
# byte-identically. Additive columns are hidden-schema (glue/arrow/parquet null): the F034 producer
# emits them; the gated B-wave catalog migration registers them (reports/silver_readiness/R2_wasde/).
CURATION_OVERRIDES: dict = {
    # ── R4 cadence calibration: _cadence(grain) infers RELEASE cadence from DATA grain, which is
    # wrong wherever the two differ (a daily-grain table from a weekly/monthly release). These
    # cadences feed only the interim F082 freshness-alarm ceilings (dag_catalog); max_lag_days
    # calibration proper stays OP-8 / AV-11. publication_lag_days is deliberately NOT set here:
    # it is reconciled 1:1 against the numbers TableSpec (F010), so a COT Tue-positions/Fri-release
    # lag (3d) or MPOB ~10th-of-month lag belongs in a numbers-stack change with its own eval gate.
    "silver_cot": {"freshness_sla": {"cadence": "weekly"}},          # CFTC COT is a weekly release
    # ── BF-W3 lane COTTON (user-gated 2026-07-15): OP-8 per-column floor calibration.
    # samples_classed is structurally ABSENT from the AMS national extraction scope before season
    # 2018 (19/27 seasons null; bronze cross-check: the metric row is absent at source for every
    # null season -- B3_wave/cotton/null_evidence.json). The rebuild is byte-identical to the
    # physical golden, so the uniform provisional floor 0.5 can NEVER pass (deterministic 0.296).
    # Calibrated floor 0.25 keeps the gate live: an all-null regression still hard-fails
    # (KIND_ALL_NAN), and a fall below 0.25 (losing the 2018+ populated seasons) still trips.
    "silver_ams_cotton_quality": {"min_nonnull_frac_overrides": {"samples_classed": 0.25}},
    # ── BF-W3 lane ONI T7 (2026-07-15): the INV-2 target for the four ENSO flag columns is int64
    # (target_arrow_type), and the B3 canonical publish wrote them as physical INT64 -- the R0
    # baseline glue_type tinyint described the pre-rebuild int8 object. Catalog + registry follow
    # the physical truth (a WIDEN; apply refuses narrows).
    "silver_noaa_oni": {"type_overrides": {
        "el_nino_flag": "bigint", "la_nina_flag": "bigint",
        "la_nina_brazil_flag": "bigint", "argentina_la_nina_flag": "bigint",
    }},
    # ── BF-W2 rider 6 (user-gated 2026-07-15): FAOSTAT QCL single_vintage waiver. A re-pull CANNOT
    # flip the V001 gate (one global annual release; distinct(ingest_date) stays 1) and would DESTROY
    # the prior raw ZIP (bucket versioning Suspended at that key). PIT adequacy for an annual
    # latest-only source is the release cycle itself; the census demotes the hard gate to a WARN that
    # carries this waiver, and the R4 certificate reports it -- never silently green.
    "silver_production": {"vintage_waiver": {
        "reason": ("FAOSTAT QCL is an annual latest-only source: one global release per year, no "
                   "in-year revisions. A re-pull cannot create a second ingest_date vintage and "
                   "would overwrite the sole raw ZIP (versioning Suspended). Next real vintage = "
                   "the ~Dec 2026 QCL release."),
        "approved": "2026-07-15 BF-W2 rider 6 (user gate)",
    }},
    "silver_psd": {"freshness_sla": {"cadence": "monthly"}},         # PSD refreshes on the WASDE cycle
    "silver_mpob": {"freshness_sla": {"cadence": "monthly"}},        # MPOB monthly palm statistics
    "silver_modis_ndvi": {"freshness_sla": {"cadence": "monthly"}},  # 16-day composite; monthly interim
    "silver_nass_crop_progress": {
        # Weekly in-season (Apr-Nov) but dark all winter: the 170d interim ceiling spans the
        # off-season gap so the alarm never cries wolf; OP-8 replaces it with a seasonal window.
        "freshness_sla": {"cadence": "weekly", "max_lag_days": 170},
        # BF-W3 lane L3 (user-ratified 2026-07-15): OP-8 per-column floor calibration, MERGED into
        # this existing entry (a second top-level "silver_nass_crop_progress" key would be a
        # duplicate-dict-key clobber that silently drops the freshness override above). Mirrors the
        # cotton min_nonnull_frac_overrides pattern (0.296 -> 0.25). The two structural condition/
        # progress metrics fall below the uniform provisional 0.5 in the worst commodity
        # (pct_good_excellent structural frac 0.303, pct_harvested 0.171 -- the progress row is
        # absent for many weeks at source); floors sit ~15pp under so an all-null regression still
        # hard-fails (KIND_ALL_NAN) and a drop below the floor still trips. week_of_year is
        # deliberately unlisted (its populatedness is intrinsic to the weekly grain, not a gap).
        "min_nonnull_frac_overrides": {"pct_good_excellent": 0.25, "pct_harvested": 0.15},
    },
    "silver_wasde": {
        "freshness_sla": {"cadence": "monthly"},  # WASDE releases monthly; the MY grain is not the cadence
        "deprecated_columns": ["months_to_marketing_year_end", "is_final_or_latest"],
        # BF-W2 step 17 APPLIED 2026-07-15 (F036 catalog migration, hash 6c45229d -> 9985cfb0): the
        # live Glue table now carries the 9 additive columns CONCRETELY and months_to_marketing_year_end
        # as bigint. The registry == live-Glue invariant therefore requires concrete types here too --
        # additive_columns_registered resolves them, type_overrides flips months.
        "additive_columns_registered": True,
        "type_overrides": {"months_to_marketing_year_end": "bigint"},
        "additive_columns": [
            ("source_table_id", "string"), ("estimate_role", "string"), ("projection_month", "string"),
            ("is_current_release_estimate", "bool"), ("release_sequence", "int64"),
            ("revision_gap_days", "int64"), ("is_projection", "bool"), ("is_source_final", "bool"),
            ("marketing_year_end_date", "string"),
        ],
        "drift_notes": {
            "months_to_marketing_year_end": (
                "C-WRONG-6 int64 fix APPLIED 2026-07-15 (BF-W2 step 17): glue_type is bigint matching the "
                "LIVE catalog (registry == live-Glue invariant), via the reviewed CatalogMigrator."
                "restore_table apply (plan artifact scripts/silver/wasde_f036_migration_plan.py, "
                "reports/silver_readiness/R2_wasde/) WITH the F013 repair of all 461 registered-partition "
                "SDs. INV-2 target and physical parquet were already int64."
            ),
        },
        "natural_key": ["release_date", "source_table_id", "commodity", "region", "marketing_year",
                        "attribute", "unit", "estimate_role", "projection_month"],
        "required_nonnull": ["release_date", "source_table_id", "commodity", "region", "marketing_year",
                             "attribute", "estimate_role"],
        "coverage_axis": ("release_date x source_table_id x commodity x region x marketing_year x "
                          "attribute x estimate_role/projection_month"),
        "producer": {
            "transform": "src/leviathan/transforms/bronze_to_silver/usda_wasde_silver.py",
            "batch_task": "jobs/batch/wasde_silver_task.py",
            "note": ("F034 restored bronze->silver producer (pure transform + controlled ShadowPublisher "
                     "registered-partition publish, dry-run default). Raw->bronze stays jobs/batch/ "
                     "wasde_bronze_modern_task.py + wasde_bronze_scanned_task.py."),
        },
        "notes_append": (
            " LANE M (F033-F036): the 9 additive governed columns above are the F036 target schema, declared "
            "here as hidden-schema (glue_type null) so the F034 producer emits them and the gated B-wave "
            "catalog migration registers them; the int64 months_to_marketing_year_end correction + the "
            "additive catalog add are both cut as a plan-only migration artifact under "
            "reports/silver_readiness/R2_wasde/. The 19 canonical snake_case attribute terms + the "
            "estimate_role vocabulary live in src/leviathan/transforms/bronze_to_silver/usda_wasde_silver.py "
            "(INV-1). Numbers registry period_sql_type=string (marketing_year \"2023/24\") is unchanged and "
            "consistent with the string marketing_year column here."
        ),
    },
}


def _apply_curation_overrides(name: str, contract: dict) -> None:
    """Merge the per-table CURATION_OVERRIDES into a freshly-built contract (deterministic)."""
    ov = CURATION_OVERRIDES.get(name)
    if not ov:
        return
    cols = contract.get("physical_columns") or []
    by_name = {c.get("name"): c for c in cols}
    for cn in ov.get("deprecated_columns", []):
        if cn in by_name:
            by_name[cn]["deprecated"] = True
    # arrow -> glue for REGISTERED additive columns (additive_columns_registered: the catalog
    # migration has been applied, so the contract carries concrete types -- the same resolution
    # wasde_f036_migration_plan.build_target_contract uses).
    _ARROW_TO_GLUE = {"string": "string", "bool": "boolean", "int64": "bigint"}
    registered = bool(ov.get("additive_columns_registered"))
    for cn, target in ov.get("additive_columns", []):
        if cn not in by_name:
            cols.append({"name": cn,
                         "glue_type": _ARROW_TO_GLUE[target] if registered else None,
                         "arrow_type": target if registered else None,
                         "parquet_physical_type": None, "target_arrow_type": target, "nullable": True})
    for cn, gt in (ov.get("type_overrides") or {}).items():
        if cn in by_name:
            by_name[cn]["glue_type"] = gt
    for row in contract.get("drift_summary") or []:
        note = ov.get("drift_notes", {}).get(row.get("column") or row.get("name") or "")
        if note:
            row["note"] = note
    for key in ("natural_key", "required_nonnull", "coverage_axis", "vintage_waiver",
                "min_nonnull_frac_overrides"):
        if key in ov:
            contract[key] = ov[key]
    if "freshness_sla" in ov:
        contract["freshness_sla"] = {**(contract.get("freshness_sla") or {}), **ov["freshness_sla"]}
    if "producer" in ov:
        contract["producer"].update(ov["producer"])
    if "notes_append" in ov:
        contract["notes"] = contract["notes"] + ov["notes_append"]


def _build_context() -> dict:
    numbers_doc = _load_yaml(_REPO / "configs" / "graphrag" / "numbers" / "tables.yaml")["tables"]
    metric_keys = {t: list((spec.get("metrics") or {}).keys()) for t, spec in numbers_doc.items()}
    tablespec = _load(CONSUMERS / "tablespec.json")["specs"]
    # merge shape/knowledge fields from the tablespec snapshot into the numbers dict. The LIVE
    # tables.yaml wins; the frozen R0 snapshot only FILLS keys the live yaml omits. The snapshot
    # must never override live PIT fields: the F010 reconcile lint compares the registry against
    # the LIVE consumer config, and a PIT divergence is forbidden in known_drift -- a snapshot-wins
    # merge silently pinned the registry to R0-era semantics (caught by the BF-W2 ESR vintage flip,
    # which the old merge re-clobbered to data_date/+7d).
    numbers = {}
    for t, spec in numbers_doc.items():
        merged = dict(spec)
        for k, v in tablespec.get(t, {}).items():
            if k in ("shape", "knowledge_date_col", "knowledge_semantics", "publication_lag_days",
                     "athena_table", "partition_cols", "grain") and k not in merged:
                merged[k] = v
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
