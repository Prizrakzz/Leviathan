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
    "silver_fred_fx": "macro", "silver_futures_eod": "prices",
    "silver_futures_prices": "prices",
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
    # T2B pattern-records ledger (docs/private/T2B_PATTERN_RECORDS_PLAN.md): the durable, PIT-safe
    # record of the deterministic engine's OWN fired/declined verdicts. Not a data source -- an
    # observability surface the serving numbers agent reads as an ordinary observed table.
    "gold_pattern_records": "observability",
}

LIFECYCLE = {
    "silver_esr_compact": "serving_copy", "gold_weather_z": "derived",
    # generated daily by the pattern-records sweep (an engine replay), like model_predictions.
    "gold_pattern_records": "generated",
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
    "silver_fred_fx": "SILVER-F040", "silver_futures_eod": "SILVER-F062",
    "silver_futures_prices": "SILVER-F062",
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
    # PRICE_AND_PLAYBOOKS W1.0: the registry DECLARES the mandated bronze->silver entrypoint ahead of
    # the producers (W1a D3 lands jobs/batch/futures_eod_task.py with --source {czce,jse_safex,cepea,
    # ...}). transform stays null on purpose -- it is per-source and lands with each leg -- so the
    # readiness PRODUCER track stays honestly BLOCKED until the first leg ships (evaluate_producer
    # blocks on a null transform), rather than a status flip papering over an unbuilt producer.
    "silver_futures_eod": (None, _J + "futures_eod_task.py", "producer"),
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
    # DSG-TAIL F2 (2026-08-16, owner-ratified): the BF-W3 half-orphan deferral's premise is
    # DEAD BY MEASUREMENT -- unica_biweekly_silver_task.py's _TABLE_MAP writes all FOUR
    # biweekly tables including these two (transform_corn_ethanol /
    # transform_monthly_ethanol_sales), proven twice on 2026-08-16: the manual canonical
    # bridge (09:27Z) and the armed-promote proof fire (11:04Z) both advanced their
    # canonical parquets. The deferral was ratified when no producer existed; recording the
    # producer that now demonstrably exists closes it rather than re-litigates it. Same
    # shape as the release_series/season_history siblings above.
    "silver_unica_corn_ethanol": (_T + "unica_biweekly.py", _J + "unica_biweekly_silver_task.py", "producer"),
    "silver_unica_monthly_ethanol_sales": (_T + "unica_biweekly.py", _J + "unica_biweekly_silver_task.py", "producer"),
    "silver_wap_table01": (_T + "wap_table01.py", _J + "wap_silver_task.py", "producer"),
    "silver_wap_table01_revisions": (_T + "wap_table01.py", _J + "wap_silver_task.py", "producer"),
    "silver_wasde": (None, _J + "wasde_bronze_modern_task.py", "producer"),
    "gold_weather_z": ("src/leviathan/transforms/gold/weather_z.py", _J + "gold_weather_z_task.py", "producer"),
    # T2B: the sweep IS the producer (no bronze->silver transform -- it replays the engine over the
    # mapped catalog and publishes the verdict ledger through F015 registered).
    "gold_pattern_records": (None, _J + "pattern_records_sweep_task.py", "producer"),
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
    # SILVER-F059: the derived week_ending_date (CURATION_OVERRIDES additive_columns_hidden below)
    # makes SAGIS weekly exports a data_date table. +5d ratified: SAGIS posts the cumulative file a
    # few days after the week's end, so a small positive lag applies (unlike ESR's 0 -- its as_of IS
    # the release; the MPOB nonzero-lag precedent). Pre-step home; superseded 1:1 by the numbers
    # TableSpec once the Integrate wave adds the silver_sagis_weekly_exports card (numbers_spec wins).
    "silver_sagis_weekly_exports": ("week_ending_date", "data_date", 5),
    # T2B ledger (plan sec 4.1): the serving numbers card reads this table point-in-time on
    # written_at (knowledge_semantics=ingest) -- a row written in 2026 was NOT "known at" a 2019
    # asof, exactly the PIT semantics that confine backfill_grid rows to the labeled engine-replay
    # base-rate path (F7). No numbers TableSpec exists yet (Writer B's serving card); this override
    # is the pre-card home and is superseded 1:1 by the numbers_spec once the card lands
    # (numbers_spec wins, build_contract), mirroring the SAGIS week_ending_date precedent above.
    "gold_pattern_records": ("written_at", "ingest", None),
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
    # T2B ledger: one row per (record_kind, contract, driver_or_chain_id, asof_date). asof_date IS the
    # registered partition key (plan sec 2.3 D3); listing it here makes record_kind/contract/
    # driver_or_chain_id the non-null key columns (nullable = cn not in natural_key). counterparty
    # stays NULLABLE (reserved for the deferred fork kinds, plan sec 1.1 / F4).
    "gold_pattern_records": ["record_kind", "contract", "driver_or_chain_id", "as_of_date"],
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


# PRICE_AND_PLAYBOOKS W1.0 provenance note (disjoint assignment, the house convention).
EXTRA_NOTES["silver_futures_eod"] = (
    " PRICE_AND_PLAYBOOKS W1.0 (docs/private/PRICE_AND_PLAYBOOKS_PLAN.md, lines 98-148): the "
    "PER-DELIVERY-MONTH futures EOD table, ADDITIVE to the flat silver_futures_prices -- which stays "
    "untouched and served throughout W1/W2 and W3's soak. vintage_retention=latest-only because "
    "PRICES DO NOT REVISE -> latest IS only; the table is append-only in practice and PIT-trivial. "
    "projection is FORBIDDEN and partition_mode is REGISTERED: the Jul-2026 26.8M-LIST / $134 storm "
    "was Athena partition-projection enumeration, and ~31 slugs x ~25 years is under 800 registered "
    "partitions (WASDE already runs 463), with a nightly run touching only the 31 current-year ones. "
    "instrument_kind (futures | cash_index) is the discriminator that makes a NULL contract_month "
    "LEGAL rather than a defect -- it is null only for the two CEPEA cash references. settle_kind "
    "(settlement | mark_to_market | cash_index | close) is the honesty label riding the row, the "
    "direct descendant of the W4.2 futures-lite lint, so no prose can mislabel the value. "
    "unit/currency are SOURCE-FAITHFUL from the SINGLE-SOURCE per-contract map "
    "(src/leviathan/silver/futures_eod_contracts.py CONTRACT_MAP); there is NO FX conversion at "
    "ingest, ever. raw_symbol is verbatim and is NEVER parsed into meaning at ingest; expiry_date is "
    "recorded only where published and is never derived. ROLL AND CONTINUOUS STAY OUT: no "
    "is_front_month, no is_roll_date, no log_return, no adjusted series -- a stored front-month flag "
    "IS roll policy, and roll policy is a QUERY-TIME decision; a continuous series would be a "
    "separate derived gold_futures_continuous with its own roll_policy_version. writer_schema_pinned "
    "is deliberately FALSE until the first producer lands (W1a): the INV-2 route is mandated "
    "(leviathan.silver.partitioned_producer -> pa_schema_from_contract -> F015 ShadowPublisher "
    "REGISTERED), but the flag states an observed producer fact, not an intention. SERVING FENCE: "
    "the numbers card is registered and linted (config_check.check_futures_eod) but the table is "
    "WHITELIST-ABSENT from serving (numbers.registry.WHITELIST_ABSENT_DEFAULT) for all of "
    "W1.0/W1/W2 -- it vanishes from the agent tool enum and every build_sql lookup raises KeyError."
    " COVERAGE FACT, W1a JSE/SAFEX (PRICE_AND_PLAYBOOKS_PLAN.md lines 241-245): JSE PRICE HISTORY "
    "STARTS THE DAY THE PRODUCER FIRST RUNS -- there is no backfill and none can be built. The "
    "portal serves ONE object (/Safex/amdmtm/NEW DAYAGR.xls) that is OVERWRITTEN IN PLACE, and the "
    "Wayback CDX holds exactly one capture of it ever (20240714021022), so the house "
    "wayback-backfill pattern is unavailable; the producer's --mode backfill raises "
    "NotImplementedError BY DESIGN rather than returning a silent empty result. An absent "
    "south_african_white_maize_jse / south_african_yellow_maize_jse row before that first-run date "
    "is NOT a gap in the series -- the series does not exist before it, and no re-run recovers it."
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
        # D-LD (2026-08-18): the WRITER contract is what the producer WRITES, not what serving
        # exposes -- coupling value_columns to card metrics silently narrows the F010 contract
        # whenever a card EXCLUDES a metric on a serving decision, which is exactly the class
        # test_mpoc_trade_card_reconciles pins against. The one live case: silver_mpoc_trade's
        # imports_mt is excluded from the card because it is MEASURED CORRUPT (prior-year
        # exports on data years 2020-2022, mechanism = _group_year_column's first-column
        # fallback), but the producer still writes it and the contract must keep declaring it
        # until the producer fix lands and the card re-adds the metric.
        _WRITER_EXTRAS = {"silver_mpoc_trade_stats_monthly": ["imports_mt"]}
        for extra in _WRITER_EXTRAS.get(name, []):
            if extra in all_cols and extra not in value_columns:
                value_columns.append(extra)
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
        # SILVER-F047 catch-up (2026-07-28): BF-W1 (2026-07-21) deprojected the trio to REGISTERED
        # [commodity, year]. INV-3 outlives the projection it was written against: these are
        # feature-layer tables read via S3 footers / get-partitions, and an Athena query against
        # them is never the recovery path (numbers-serving is quarantined to gold_weather_z).
        recovery = ("get-partitions reconcile + S3 footer reads (INV-3, post-F047 deprojection: "
                    "NEVER start-query-execution against this weather table; serving is "
                    "quarantined to gold_weather_z)")
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

# -- SILVER-F047 REGISTRY CATCH-UP (2026-07-28). BF-W1 (2026-07-21) deprojected the weather
# storm-trio's 5-key projected layout to REGISTERED [commodity, year] partitions; the hand DDLs
# were synced the same day, but the R0 baseline (20260712) PREDATED the migration, so the registry
# kept emitting the projected shape -- surfaced as chirps hand-vs-generated drift during
# PRICE_AND_PLAYBOOKS W1.0. Fixed by the sanctioned apply-then-refresh discipline (the F024 CONAB /
# F036 WASDE precedent, test_generated_matches_live_glue_for_every_table): the three baseline
# records under 20260712_p65impl/tables/ were RE-CAPTURED from live Glue via run_census.census_one
# on 2026-07-28 (registered partitions: chirps/nasa 1,426 each, cpc_soil 837; zero placeholders;
# country/region/month declared in-file at the END of the column list -- the parquet always
# carried them, and all three are natural-key members so the nullability heuristic lands non-null).
# The notes_append below is the only curation this needs: everything else regenerates from the
# refreshed snapshot.
_F047_WEATHER_NOTE: dict = {
    "notes_append": (
        " SILVER-F047 registry catch-up (2026-07-28): BF-W1 deprojection (2026-07-21) reflected via "
        "baseline re-capture -- REGISTERED [commodity, year]; country/region/month declared in-file "
        "(non-null natural-key members; the in-file year -- and commodity where present -- stay "
        "undeclared to avoid partition-key collisions); write_mode registered-partition (the F047 "
        "compaction writer publishes via the F015 shadow + F013 registered path). Projection grid "
        "removed; INV-3 stands: recovery never starts an Athena query."
    ),
}

CURATION_OVERRIDES: dict = {
    "silver_chirps": _F047_WEATHER_NOTE,
    "silver_nasa_power": _F047_WEATHER_NOTE,
    "silver_cpc_soil": _F047_WEATHER_NOTE,
    # D-LD TRANCHE 2 (2026-08-18): the derived PIT anchor year_ending_date. Was staged HIDDEN
    # (the SILVER-F059 sagis precedent) so the producer could encode it while the catalog still
    # rendered four columns == live Glue; the gated ADD COLUMNS was applied the SAME DAY after the
    # canonical re-run (runbook order; verify SELECT read d0=2009-12-31 d1=2023-12-31
    # null_anchors=0), the R0 snapshot refreshed to the five-column truth, and the hidden staging
    # retired -- the column now resolves from the glue section like any other. nullable_overrides
    # stays: the anchor derives from the page year and can never be missing, and a null would
    # silently defeat the PIT guard (null <= asof is UNKNOWN, so the row drops).
    "silver_mpoc_exports_by_country": {
        "nullable_overrides": {"year_ending_date": False},
    },
    # D-LD TRANCHE 2 (2026-08-18) -- silver_food_cpi, and this one is REGISTERED rather than hidden
    # because its Glue migration is APPLIED, not gated. PROVENANCE: the entry is the food_cpi card
    # package's own runbook step, transcribed verbatim; the live catalog change was a REPLACE COLUMNS
    # (not an ADD) that SUCCEEDED 2026-08-18, and the R0 snapshot
    # reports/silver_readiness/20260712_p65impl/tables/silver_food_cpi.json was refreshed to the
    # 10-column post-REPLACE shape in the same change (the CONAB apply-then-refresh precedent, and the
    # same refresh the four Tranche-2 siblings took today).
    #
    # TWO THINGS AT ONCE, and both are corrections of a LIVE DEFECT rather than bookkeeping:
    #  (1) additive_columns (+ additive_columns_registered) -- the producer-derived PIT anchors. The
    #      table had NO date column of any kind, so every as-of-guarded lookup raised "table
    #      silver_food_cpi has no knowledge/date column to anchor the as-of guard". `data_date` is the
    #      year-end OBSERVATION date 'YYYY-12-31' (the card's knowledge_date_col/date_col); `release_date`
    #      is the World Bank API's own `lastupdated` release stamp, which the bronze parser already read
    #      and discarded (the card's provenance_col -> the `revision_stamp` alias). REGISTERED, so the
    #      contract carries concrete Glue/arrow types and the generated DDL renders all ten columns ==
    #      live Glue -- the WASDE F036 post-apply resolution, not the SILVER-F059 hidden staging above.
    #      nullable_overrides pins BOTH non-null: each is derived (from the observation year and from the
    #      release metadata) and can never be missing, and a null would silently defeat the PIT guard
    #      (null <= asof is UNKNOWN, so the row drops).
    #  (2) type_overrides -- the SILVER-F062 widen landed in the WRITER (F010 target_arrow_type float64)
    #      and NEVER in the CATALOG. cpi_yoy_pct / cpi_yoy_z_5yr / cpi_yoy_z_10yr were declared `float`
    #      (Athena `real`) over DOUBLE parquet, so Athena REFUSED to read them: "HIVE_BAD_DATA: Malformed
    #      Parquet file. Field cpi_yoy_pct's type DOUBLE in parquet file ... is incompatible with type
    #      real defined in table schema". Strings, `year`, `cpi_available` and count(*) all succeeded, so
    #      the table looked alive while EVERY served metric was unreadable. cpi_available is corrected
    #      int32/tinyint -> bigint for truthfulness (Athena widens that one silently; it was never broken).
    "silver_food_cpi": {
        "additive_columns": [("data_date", "string"), ("release_date", "string")],
        "additive_columns_registered": True,
        "nullable_overrides": {"data_date": False, "release_date": False},
        "type_overrides": {"cpi_yoy_pct": "double", "cpi_yoy_z_5yr": "double",
                           "cpi_yoy_z_10yr": "double", "cpi_available": "bigint"},
    },
    # ── R4 cadence calibration: _cadence(grain) infers RELEASE cadence from DATA grain, which is
    # wrong wherever the two differ (a daily-grain table from a weekly/monthly release). These
    # cadences feed only the interim F082 freshness-alarm ceilings (dag_catalog); max_lag_days
    # calibration proper stays OP-8 / AV-11. publication_lag_days is deliberately NOT set here:
    # it is reconciled 1:1 against the numbers TableSpec (F010), so a COT Tue-positions/Fri-release
    # lag (3d) or MPOB ~10th-of-month lag belongs in a numbers-stack change with its own eval gate.
    # CFTC COT is a weekly release (Tue positions, Fri publish). max_lag_days=10 is the interim F082
    # freshness-alarm ceiling (weekly cadence + a few days' slack). It was hand-tweaked directly into the
    # checked-in card during COT registration, breaking the generated-never-hand-written invariant
    # (test_checked_in_tree_matches_fresh_render); moved to its reproducible home here so render ==
    # checked-in. Mirrors the silver_nass_crop_progress max_lag_days curation precedent.
    "silver_cot": {"freshness_sla": {"cadence": "weekly", "max_lag_days": 10}},
    # SEAM-C prerequisite (2026-07-22): the yfinance futures chain runs on a MON-FRI 23:00 cron
    # (configs/silver/dags/futures_prices.json). The bare daily cadence default (3d, dag_catalog
    # CADENCE_DEFAULT_LAG_DAYS) false-fires over a normal weekend: a Friday-close write is already
    # ~3 days old by the Monday-evening run, and any single skipped weekday pushes it past 3. The
    # market is dark Sat/Sun, so 5d is the sane interim ceiling -- it spans a weekend + one missed
    # weekday yet still trips on a genuine multi-day stall (the 2026-06-05 stall ran 6+ weeks dark
    # with NO freshness alarm because max_lag_days was null and no cert emitted). Root-caused to the
    # worker image never installing yfinance (now in the pyproject [batch] extra); this ceiling is the
    # detection backstop. Same reproducible-override home as the silver_cot precedent above.
    # ── FUTURES v1.5 W1+W2 (ratified 2026-07-23, docs/private/FUTURES_V15_PLAN.md). W1 unit widen:
    # the R0 snapshot (tables/silver_futures_prices.json) is PATCHED with the 11th additive `unit`
    # string column + the catalog/schema fingerprints recomputed by the EXACT census algorithms
    # (scratch/silver_f001/common.py catalog_hash / footer_fingerprint; both re-verified to reproduce
    # the stored 10-col hashes byte-for-byte before patching), so the contract REGENERATES rather than
    # being hand-edited (D1). schema_version 1 -> 2 is the ADDITIVE widen bump; D6 grep confirmed no
    # consumer pins the registry schema_version (the F015 publisher manifest only RECORDS it). The
    # producer emits `unit` from the SINGLE-SOURCE UNIT_MAP (transforms/raw_to_bronze/
    # yfinance_futures.py, beside TICKER_MAP); config_check.check_futures_lite binds card
    # unit_overrides == _FUTURES_UNIT_OVERRIDES == UNIT_MAP == this contract's unit column (D2 KEEP
    # unit_overrides as the serving contract, redundant-but-consistent by lint). W2.2 roll policy:
    # versioned splice-policy note in provenance.roll_policy + notes (the numbers card notes carry the
    # SAME versioned note; the lint pins both). levels_only stays true (D3); curve stays deferred (D5).
    "silver_futures_prices": {
        "freshness_sla": {"cadence": "daily", "max_lag_days": 5},
        "schema_version": 2,
        "provenance_extra": {"roll_policy": {
            "roll_policy_version": 1,
            "policy": ("yfinance continuous front-month, chained UNADJUSTED; roll rule "
                       "vendor-undocumented; rolls detected empirically at |close pct change| > 5% "
                       "(src/leviathan/transforms/raw_to_bronze/yfinance_futures.py _ROLL_THRESHOLD); "
                       "derived/return columns are NaN-masked at rolls and are NEVER served."),
        }},
        "notes_append": (
            " FUTURES v1.5 (2026-07-23): additive `unit` column (schema_version 2) carries the "
            "per-contract exchange unit from the single-source UNIT_MAP "
            "(transforms/raw_to_bronze/yfinance_futures.py); lint-bound equal to the numbers card "
            "unit_overrides (check_futures_lite three-way, D2 KEEP). roll_policy_version=1 "
            "(provenance.roll_policy): yfinance continuous front-month, chained UNADJUSTED; roll rule "
            "vendor-undocumented; rolls detected empirically at |close pct change| > 5%; derived/return "
            "columns are NaN-masked at rolls and are NEVER served (levels_only stays true, D3). "
            "Provenance label (W4.2, D4a card-text): the served number is the Yahoo Finance continuous "
            "front-month close (not official exchange settlement), never an official settle."
        ),
    },
    # -- PRICE_AND_PLAYBOOKS W1.0 (RATIFIED 2026-07-28): silver_futures_eod, the per-delivery-month
    # futures EOD table. Everything here is a fact build_contract cannot derive from the R0 record:
    #   * freshness_sla -- LOAD-BEARING, not cosmetic. _cadence(grain) tests "month" BEFORE "date",
    #     so ANY grain string containing `contract_month` renders cadence=monthly; the table is
    #     DAILY. max_lag_days=5 matches the flat futures table's ratified weekend-grace ceiling
    #     (a Fri close is ~3d old by Monday, so the bare daily default of 3 false-fires).
    #   * natural_key -- the whole point of the wave: (leviathan_slug, contract_month, trade_date).
    #     The pre-override key comes from the source contract; the curated form is identical, so
    #     this entry is the reproducible statement of record rather than a change.
    #   * required_nonnull -- deliberately NOT the natural key (the WASDE precedent, 7 of 9):
    #     contract_month is a KEY member that is legitimately NULL on the two CEPEA cash rows, so
    #     the honest non-null set is the key minus contract_month PLUS the four contract-non-null
    #     labels (instrument_kind / settle_kind / unit / source).
    #   * nullable_overrides -- see _apply_curation_overrides; this is the INV-2 writer-schema
    #     nullability the plan pins verbatim (lines 114-133).
    "silver_futures_eod": {
        "freshness_sla": {"cadence": "daily", "max_lag_days": 5},
        "natural_key": ["leviathan_slug", "contract_month", "trade_date"],
        "required_nonnull": ["leviathan_slug", "trade_date", "instrument_kind", "settle_kind",
                             "unit", "source"],
        "coverage_axis": "leviathan_slug x contract_month x trade_date",
        "nullable_overrides": {
            "contract_month": True,     # NULL only where instrument_kind=cash_index (2 CEPEA refs)
            "instrument_kind": False,   # the futures | cash_index discriminator
            "settle_kind": False,       # the honesty label rides every row
            "unit": False,              # from the single-source CONTRACT_MAP; never guessed
            "source": False,            # the publication channel; makes settle_kind auditable
        },
    },
    # ── IOD SOURCE SWITCH (ADR_IOD_SOURCE_SWITCH, RATIFIED 2026-07-24, Option B). The served DMI
    # re-bases from the FROZEN NOAA PSL HadISST1.1 file (last real month 2025-04; the file has not
    # regenerated since 2025-06-16) onto the LIVE NOAA CPC ERSSTv5 IODMI record. Same table, same
    # 8 columns, same s3_root (decision 6.4), so the ONLY registry-visible moves are the freshness
    # guard and the contract notes -- both land here so the checked-in YAML stays a reproducible
    # render (the F011 idempotency gate, test_checked_in_tree_matches_fresh_render). The R0-derived
    # fingerprints are untouched by design: they regenerate from the R0 snapshot at publish time.
    # max_lag_days=45 is the ADR's ratified staleness ceiling (Section 5 "freshness guard"). It is
    # numerically the same as the monthly cadence default it replaces, but as an EXPLICIT value it
    # survives a cadence re-derivation and states the SLA the alarm is justified from -- this table
    # is the one that ran ~13 months stale-green, so the ceiling is a decision, not a default.
    # publication_lag_days is deliberately NOT set (see the notes): it is inert under year_month PIT
    # and would be ADDED as freshness grace, loosening this very ceiling to 90.
    "silver_noaa_iod": {
        "freshness_sla": {"cadence": "monthly", "max_lag_days": 45},
        "notes_append": (
            " IOD SOURCE SWITCH (ADR_IOD_SOURCE_SWITCH, RATIFIED 2026-07-24, Option B): the served "
            "DMI is re-baselined from the FROZEN NOAA PSL HadISST1.1 long file (last real "
            "observation 2025-04, file stamp 2025-06-16) onto the LIVE NOAA CPC IODMI record "
            "(ERSSTv5; https://www.cpc.ncep.noaa.gov/products/international/ocean_monitoring/IODMI/"
            "mnth.ersstv5.clim19912020.dmi_current.txt; monthly). Key range moves 1870-01..2025-04 "
            "-> 1950-01..present: 960 pre-1950 keys DROPPED (no NAMED positive-IOD analogue is "
            "pre-1950), 904 keys RESTATED, forward months added. Table name, 8-column schema and "
            "s3_root are UNCHANGED (decision 6.4, legacy stable identifier -- ADR-003 rule 6); the "
            "`source` column carries the truthful provider stamp `cpc_iodmi` (ADR-003 rule 2), so "
            "the path is a legacy misnomer and the column is the provenance authority. UNITS "
            "(EDA-SEMANTIC-UNIT-001): dmi_value and iod_dmi_3month_avg are degC SST anomalies "
            "against the FIXED 1991-2020 climatology, served exactly as published -- never "
            "re-anomalized to HadISST's full-record mean (decision 5), so historical magnitudes are "
            "RESTATED rather than continued (1997-11 peak 1.28 -> 1.55; 2019-10 0.96 -> 1.78). PIT "
            "(EDA-PIT-002): CPC publishes a completed month ~30-45 days after month end. That lag is "
            "governed HERE and on the numbers card as TEXT, and publication_lag_days stays null on "
            "purpose -- under year_month semantics the as-of guard is month-grain and never applies "
            "the lag shift (graphrag/numbers/query.py `_guard` returns before it), so a numeric "
            "value would declare an enforcement that does not happen, AND dag_catalog."
            "effective_sla_lag_days ADDS publication_lag_days as freshness grace, which would "
            "loosen the ratified 45d ceiling to 90. Residual, disclosed: an as-of inside the "
            "publication window can therefore see a month CPC has not yet released; closing it "
            "needs a year_month lag shift in the numbers stack, not a registry field. FRESHNESS: "
            "freshness_sla.max_lag_days=45 + the F082 staleness alarm are the guard that a future "
            "upstream pause is caught in weeks rather than the ~13 months this one ran "
            "unremediated. PROVENANCE: the pre-switch HadISST series is retained as an immutable "
            "`_hadisst_frozen` snapshot (never served; rollback = repoint to it)."
        ),
    },
    # ── BF-W3 lane COTTON (user-gated 2026-07-15): OP-8 per-column floor calibration.
    # samples_classed is structurally ABSENT from the AMS national extraction scope before season
    # 2018 (19/27 seasons null; bronze cross-check: the metric row is absent at source for every
    # null season -- B3_wave/cotton/null_evidence.json). The rebuild is byte-identical to the
    # physical golden, so the uniform provisional floor 0.5 can NEVER pass (deterministic 0.296).
    # Calibrated floor 0.25 keeps the gate live: an all-null regression still hard-fails
    # (KIND_ALL_NAN), and a fall below 0.25 (losing the 2018+ populated seasons) still trips.
    "silver_ams_cotton_quality": {"min_nonnull_frac_overrides": {"samples_classed": 0.25}},
    # ── Pink Sheet first-fire calibration (2026-08-04, world_bank-firstfire-smoke): the WB CMO
    # rapeseed-oil series starts mid-history, so its all-time non-null fraction can never reach the
    # uniform provisional 0.5 -- MEASURED at the first real fetch: rapeseed_oil_usd_t 0.3672, its 5yr
    # zscore 0.3233 (warmup on top). Floors set measured-minus-margin per the ams-cotton precedent
    # above: a REAL coverage regression (losing populated years) still refuses the publish, and
    # KIND_ALL_NAN still hard-fails an all-null column. Every other column stays at the table floor.
    "silver_pink_sheet": {"min_nonnull_frac_overrides": {
        "rapeseed_oil_usd_t": 0.30,
        "rapeseed_oil_usd_t_zscore_5yr": 0.26,
    }},
    # ── ESR changes_1000mt UPSTREAM TERMINATION (2026-07-23 gate FAIL triage): the FAS ESR
    # /allCountries response DROPPED the `changes` field entirely between the 20260524 and
    # 20260712 fetches -- immutable raw proof: every record of as_of=20260712/17/23 for
    # commodity_code=101 carries NO changes-like key (0/6863 records), while the 20260524
    # vintage in silver is 100% non-null. The column was ALREADY deprecated-nullable by the
    # SILVER-F030 ADR (INV-4: absent stays NULL, never synthesized 0.0), so the transform is
    # CORRECT; each new all-null vintage now dilutes the mixed non-null fraction below the
    # provisional 0.5 floor (canonical 0.4933 -> shadow 0.3300, monotonically falling forever).
    # Floor 0.0 = tolerate the dead field while KEEPING the gate live: KIND_ALL_NAN still
    # hard-fails if even the historical vintages go null (real corruption), and every other
    # value column stays at the table floor.
    # -- D-SG G1-6 (owner-gated 2026-08-16): the FULL per-partition silver_esr surface
    # (silver/production/source=usda_esr) was SUPERSEDED by silver_esr_compact at Phase D. Nothing
    # writes it: the esr_weekly chain's only silver producer is bronze_to_silver_esr_task.py
    # (the COMPACT writer), and backfill_silver_usda_esr.py is on no schedule. Measured
    # 2026-08-16: commodity_code=101 holds 37 market_year prefixes, EVERY one carrying the single
    # as_of=20260524 re-baseline. So distinct(as_of_date)==1 is a PERMANENT property of an
    # abandoned surface, and the V001 single_vintage row exit-1'd the one gate job that covers the
    # whole usda_esr family -- blocking [Promote] for silver_esr_compact too (2026-08-06 and
    # 2026-08-13 FAILED; bronze meanwhile holds as_of=20260806 and 20260813). The waiver DEMOTES
    # that row to a WARN carrying this approval (never silently green) and leaves every other
    # V001 kind hard: KIND_ALL_NAN still refuses, the per-column floors still refuse. PIT adequacy
    # for ESR is served by silver_esr_compact, which carries the real per-week vintages and is
    # what tables.yaml:311 `athena_table` and this contract's `serving_table` both name.
    "silver_esr": {
        "min_nonnull_frac_overrides": {"changes_1000mt": 0.0},
        "vintage_waiver": {
            "reason": ("The FULL per-partition silver_esr surface at "
                       "silver/production/source=usda_esr was superseded by silver_esr_compact at "
                       "Phase D and has no writer on any schedule, so its as_of_date is frozen at "
                       "the 20260524 re-baseline and a second vintage cannot arise. Per-week PIT "
                       "vintages live on silver_esr_compact (the numbers athena_table and this "
                       "contract's serving_table); this surface is read by nothing."),
            "approved": "2026-08-16 D-SG G1-6 (user gate)",
        },
    },
    "silver_esr_compact": {"min_nonnull_frac_overrides": {"changes_1000mt": 0.0}},
    # ── Wave-3 conab canary forensics (2026-07-17): the production_revision_thousand_bags min_nonnull
    # override is RETIRED by WIRING WAVE-1 (2026-07-23). Wiring silver_conab_coffee into the numbers
    # registry makes value_columns the NUMBERS-METRIC set (production_thousand_bags / area_in_production_ha
    # / yield_bags_per_ha) -- the exact sibling behavior of silver_sagis_cec (a "both" table whose revision
    # deltas are likewise non-value). production_revision_thousand_bags therefore drops OUT of value_columns,
    # so a min_nonnull_frac_override keyed on it is orphaned (override keys must be value_columns) and the
    # census no longer floors that derived-diff column at all -- exactly as for sagis_cec's revision fields.
    # (No curation entry needed; left as a note so the forensic rationale is not lost.)
    # ── SILVER-F059 / WIRING WAVE-1 Card C (2026-07-24): the numbers wave needs a sargable point-in-time
    # anchor; the producer derives an ISO week_ending_date (date32) that week_ending (free-text ranges)
    # cannot serve. The pre-step staged it as a HIDDEN/physical-only additive column (glue_type=None);
    # the main loop has since APPLIED the gated Glue ADD COLUMNS migration (live catalog now = 9 cols,
    # week_ending_date DATE), so the R0 glue snapshot carries the 9th column and the column resolves
    # from the glue section directly -- no additive_columns_hidden override remains (mirrors the CONAB
    # survey_release_date apply-then-refresh: registry + R0 snapshot + hand DDL carry the derived date
    # together). Card C wires the numbers TableSpec (configs/graphrag/numbers/tables.yaml), which now
    # OWNS the knowledge fields (data_date / +5d); the KNOWLEDGE_DATE_OVERRIDE entry above is the dead
    # pre-step fallback (numbers_spec wins, build_contract:495).
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
        #
        # D-CW-2a (2026-08-07) -- THREE MORE COLUMNS, because wiring the numbers card MOVED THE
        # VALUE SET. value_columns for a "both" table is the NUMBERS-METRIC set (build_contract:545),
        # so landing configs/graphrag/numbers/tables.yaml#silver_nass_crop_progress promotes
        # pct_poor_very_poor / pct_planted / pct_emerged into value_columns (and drops week_of_year,
        # which was never a value anyway) -- and a promoted column with no floor inherits the uniform
        # provisional 0.5, which these three can NEVER reach for exactly the reason the two above
        # cannot: the progress/condition row is absent from source for most weeks of the year. Left
        # unset, the next NASS write (the D-CW-2a catch-up run) fails the publish gate on a column
        # nobody changed. That is a landmine the card lays, so the card discharges it.
        # DERIVATION, from the in-repo EDA artifact (eda/silver_nass_crop_progress/summary.json,
        # missingness_validity.column_missingness, EXACT over 141,714 rows -- not a guess, and not a
        # new measurement either): pooled non-null rates are pct_poor_very_poor 0.5057,
        # pct_planted 0.3267, pct_emerged 0.2049. The two RATIFIED floors above calibrate against the
        # WORST COMMODITY, whose structural fraction is ~0.5x the pooled rate on both measured
        # columns (0.303 vs 0.568; 0.171 vs 0.334), and then sit ~15% under that. Applying the same
        # two steps to the pooled rates gives 0.21 / 0.14 / 0.085 -> floored to 0.20 / 0.13 / 0.08.
        # PROVISIONAL and deliberately conservative (the per-commodity worst case is INFERRED here,
        # not measured): OP-8 recalibrates from a real per-partition census. The gate stays LIVE --
        # KIND_ALL_NAN still hard-fails an all-null column, and losing the populated weeks still trips.
        # D-LD gate-red RECALIBRATION (2026-08-18): pct_emerged 0.08 -> 0.05, the per-partition
        # census this comment always owed (OP-8). Full-scan truth, cotton (the worst commodity),
        # completed years: 2018 0.0681, 2019 0.0762, 2020 0.0933, 2021 0.0826, 2022 0.0827,
        # 2023 0.0872, 2024 0.1025 -- TWO completed years sit BELOW the inferred 0.08, so a
        # 2018-shaped year could never pass, and the gate's 18-file sample additionally read
        # 0.059 against a live 2026 YTD truth of 0.2078 (the sampler undershoots). 0.05 clears
        # every measured end-state plus sampler noise; a real emptying still trips it and
        # KIND_ALL_NAN still hard-fails an all-null column.
        "min_nonnull_frac_overrides": {"pct_good_excellent": 0.25, "pct_harvested": 0.15,
                                       "pct_poor_very_poor": 0.20, "pct_planted": 0.13,
                                       "pct_emerged": 0.05},
        #
        # D-SG G1-5 (user-gated 2026-08-16) -- THE FLOOR THAT REFUSED AUGUST. The usda_nass gate
        # failed on 2026-08-11 (job 90b65749) with "[commodity=corn_cbot] 'pct_harvested' non-null
        # fraction 0.141 < floor 0.15". Nothing was wrong with the data: NASS publishes no harvested
        # row until harvest begins, so the current crop year contributes planted / emerged /
        # condition weeks and NO harvest weeks, and the pooled non-null fraction falls all season
        # until the first harvest report. 0.141 measured in mid-August is the source telling the
        # truth, and a season-blind floor turns that into an annual refusal window -- the same
        # refusal, at the same point in the calendar, every year.
        #
        # WINDOW, derived from the crop-progress reporting season rather than from the failure:
        # harvested is reported from the first harvest weeks (corn / soybeans / rice from early
        # September, cotton later, spring wheat from August) to the report's close on the last
        # Monday in November. Months 1-9 are therefore the months in which the current crop year has
        # accrued few or no harvested rows; from October the harvest weeks are landing and by the
        # report's close the crop year is complete, so a shortfall in 10-12 is a REAL regression and
        # keeps the full 0.15.
        # FLOOR 0.10, the value the D-SG plan itself names for this column: it clears the measured
        # 0.141 with headroom for the deeper trough in late August / early September (the fraction
        # keeps falling until the first harvest report), and it stays far enough above zero that
        # KIND_ALL_NAN and a genuine collapse still hard-fail in EVERY month.
        # pct_harvested ALONE carries a season window: it is the only value column whose absence is
        # calendar-structural in the direction that bites. planted / emerged report April-June and
        # condition May-November, so their dilution peaks in the winter months their existing
        # full-year floors were already calibrated across.
        "min_nonnull_frac_season_overrides": {"pct_harvested": {"1-9": 0.10}},
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
        # WASDE-restoration W2 (2026-07-22): the range-era ("LOW - HIGH") price-band pair. The restoration
        # bronze parser stores the midpoint in `estimate` and the printed bounds here; the F034 producer now
        # threads them (usda_wasde_silver.ADDITIVE_COLUMNS). HIDDEN-schema (glue_type null) -- a NEW additive
        # pair the live catalog has not registered yet, awaiting its own gated ADD COLUMNS migration; excluded
        # from the generated DDL until then (registry == live-Glue invariant). SPARSE by design (null for
        # every point value) -> deliberately NOT value_columns, so the SILVER-V001 non-null floor never
        # applies (see the publisher-tolerance test).
        "additive_columns_hidden": [("value_low", "float64"), ("value_high", "float64")],
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
    _ARROW_TO_GLUE = {"string": "string", "bool": "boolean", "int64": "bigint", "float64": "double"}
    registered = bool(ov.get("additive_columns_registered"))
    for cn, target in ov.get("additive_columns", []):
        if cn not in by_name:
            entry = {"name": cn,
                     "glue_type": _ARROW_TO_GLUE[target] if registered else None,
                     "arrow_type": target if registered else None,
                     "parquet_physical_type": None, "target_arrow_type": target, "nullable": True}
            cols.append(entry)
            # register in by_name so later override stages (nullable_overrides -- the F047
            # trio's demoted-key columns are natural-key members, hence non-null) can see it.
            by_name[cn] = entry
    # additive_columns_hidden: producer-emitted columns NOT yet in the live catalog -> glue_type=None
    # ("hidden schema": excluded from the DDL, surfaced in physical_only_columns), ALWAYS hidden
    # regardless of additive_columns_registered. A NEW additive column awaiting its own gated catalog
    # migration (the WASDE value_low/value_high price-band pair). The writer arrow schema keys on
    # target_arrow_type, so the F034 producer still emits them into the parquet.
    for cn, target in ov.get("additive_columns_hidden", []):
        if cn not in by_name:
            entry = {"name": cn, "glue_type": None, "arrow_type": None,
                     "parquet_physical_type": None, "target_arrow_type": target, "nullable": True}
            cols.append(entry)
            by_name[cn] = entry
    for cn, gt in (ov.get("type_overrides") or {}).items():
        if cn in by_name:
            by_name[cn]["glue_type"] = gt
    # nullable_overrides (PRICE_AND_PLAYBOOKS W1.0): per-column INV-2 nullability, the ONE column
    # fact build_contract cannot derive. Its default (`nullable = cn not in natural_key`) is a good
    # heuristic but it is only a heuristic: silver_futures_eod's ratified natural key includes
    # contract_month, which is legitimately NULL for the two CEPEA cash references (instrument_kind=
    # cash_index is the discriminator), while instrument_kind / settle_kind / unit / source are
    # NON-NULL by contract yet sit outside the key. The flag is load-bearing, not cosmetic:
    # flat_producer.pa_schema_from_contract turns it into pa.field(..., nullable=...), so a wrong
    # value either fails the pyarrow encode on legal data or silently permits an illegal null.
    # Keys must be declared physical columns (a typo would otherwise be a silent no-op).
    for cn, flag in (ov.get("nullable_overrides") or {}).items():
        if cn not in by_name:
            raise KeyError(f"{name}: nullable_overrides column {cn!r} is not a declared physical column")
        by_name[cn]["nullable"] = bool(flag)
    for row in contract.get("drift_summary") or []:
        note = ov.get("drift_notes", {}).get(row.get("column") or row.get("name") or "")
        if note:
            row["note"] = note
    for key in ("natural_key", "required_nonnull", "coverage_axis", "vintage_waiver",
                "min_nonnull_frac_overrides", "min_nonnull_frac_season_overrides",
                "schema_version"):
        if key in ov:
            contract[key] = ov[key]
    if "freshness_sla" in ov:
        contract["freshness_sla"] = {**(contract.get("freshness_sla") or {}), **ov["freshness_sla"]}
    # provenance_extra: reproducible sub-keys appended to the generated provenance block (FUTURES v1.5
    # roll_policy). dict-update so baseline_id/anchor_git_sha/generated_* stay generator-owned.
    if "provenance_extra" in ov:
        contract["provenance"].update(ov["provenance_extra"])
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
        f"contracts (43 silver + gold_weather_z + gold_pattern_records).",
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
