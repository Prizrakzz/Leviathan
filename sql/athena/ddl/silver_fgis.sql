-- silver_fgis: weekly USDA FGIS export inspection volumes with cumulative CTD.
-- Lives under silver/fgis/ to avoid schema collision with silver_production.
-- Partition projection resolves S3 paths from metadata — no MSCK REPAIR needed.
-- Managed programmatically by jobs/run_athena_ddl.py :: ensure_catalog().
--
-- Data layer:  silver (aggregated from per-shipment bronze).
-- Granularity: one row per (leviathan_slug, marketing_year, week_of_marketing_year,
--              destination_country).
-- Units:       metric tonnes (MT), matching FGIS source data.
-- Partitions:  leviathan_slug × marketing_year (no as_of — FGIS is a legal
--              record, not a survey; no revision risk).
--
-- Week alignment:
--   corn / soybeans : week 1 = Sep 1 of marketing_year
--   wheat classes   : week 1 = Jun 1 of marketing_year
--
-- CTD scope: cumulative within (leviathan_slug, marketing_year, destination_country).
-- Total-across-destinations aggregation is deferred to the gold layer.
--
-- Note on column layout: leviathan_slug and marketing_year are partition columns
-- and are therefore NOT listed in the table body; Athena injects them from the
-- Hive path.  The Parquet files may also contain these columns — Athena will
-- use the partition value (which is always identical).

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_fgis (
    week_of_marketing_year    INT,
    week_ending_date          STRING,
    destination_country       STRING,
    exports_mt_weekly         DOUBLE,
    exports_mt_ctd            DOUBLE,
    source                    STRING
)
PARTITIONED BY (leviathan_slug STRING, marketing_year INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fgis/'
TBLPROPERTIES (
    'projection.enabled'                = 'true',
    'projection.leviathan_slug.type'    = 'enum',
    'projection.leviathan_slug.values'  = 'corn_cbot,soybeans_cbot,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot',
    'projection.marketing_year.type'    = 'integer',
    'projection.marketing_year.range'   = '1983,2035',
    'storage.location.template'         = 's3://leviathan-dev-shahem-001/silver/fgis/leviathan_slug=${leviathan_slug}/marketing_year=${marketing_year}'
);
