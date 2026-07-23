-- silver_conab_coffee - frozen Athena DDL compared by jobs/utils/validate_athena_ddl_drift.py.
--
-- CANONICAL COLUMN ORDER = LIVE GLUE CATALOG ORDER (base-10 producer columns + the 12 SILVER-F024
-- revision/provenance columns ADD COLUMNS-appended). This is HAND-ALIGNED to the live catalog and is
-- deliberately NOT in physical-parquet order.
--
-- DIVERGENCE / DO-NOT-REGENERATE: the deprecated jobs/utils/generate_silver_ddls.py infers column
-- order from the FIRST parquet object's footer (physical producer order), in which the 12 F024
-- columns are interleaved (region_raw after region; the *_revision_* fields beside their bases;
-- source last). Live Glue instead holds them in registry ADD-COLUMNS order (10 base + 12 appended).
-- The two orderings carry the SAME 22 columns; the drift tripwire is order-sensitive, so this file is
-- pinned to the live-catalog order. Do NOT re-run generate_silver_ddls.py against this table (it would
-- reintroduce the parquet-order drift). SILVER-F024 widen was applied out-of-band 2026-07-14; see
-- sql/athena/migrations/silver/20260714T201146Z_silver_conab_coffee_additive_update.json.
--
-- WIRING_WAVE1 pre-step (ADDITIVE, 2026-07-23): survey_release_date (string) HAND-APPENDED LAST as the
-- 23rd column -- the derived vintage knowledge anchor the numbers card reads as knowledge_date_col. Live
-- Glue catches up via a gated ADD COLUMNS (survey_release_date string), mirroring the append here; see
-- sql/athena/migrations/silver/20260723T000000Z_silver_conab_coffee_survey_release_date_additive.json.
--
-- Flat table over silver/conab_coffee/ (hive partition keys are also in-file data columns).
CREATE EXTERNAL TABLE IF NOT EXISTS silver_conab_coffee (
    commodity                         string,
    country                           string,
    safra_year                        bigint,
    survey_number                     bigint,
    region                            string,
    area_in_production_ha             double,
    yield_bags_per_ha                 double,
    production_thousand_bags          double,
    production_revision_thousand_bags double,
    source                            string,
    region_raw                        string,
    area_revision_ha                  double,
    yield_revision_bags_per_ha        double,
    production_revision_pct           double,
    production_revision_streak        bigint,
    is_repeated_survey                boolean,
    repeated_from_survey_number       bigint,
    survey_content_fingerprint        string,
    source_raw_key                    string,
    source_file_etag                  string,
    worksheet                         string,
    parser_version                    string,
    survey_release_date               string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/conab_coffee/'
TBLPROPERTIES ('parquet.compression' = 'SNAPPY');
