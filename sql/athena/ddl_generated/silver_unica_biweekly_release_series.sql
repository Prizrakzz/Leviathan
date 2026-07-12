-- silver_unica_biweekly_release_series - production silver table (derived); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_unica_biweekly_release_series.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_unica_biweekly_release_series (
    harvest_year                 string,
    position_date                string,
    region                       string,
    cane_crushed_current_t       double,
    cane_crushed_prior_t         double,
    sugar_produced_current_t     double,
    sugar_produced_prior_t       double,
    ethanol_total_current_m3     double,
    ethanol_total_prior_m3       double,
    ethanol_anhydrous_current_m3 double,
    ethanol_anhydrous_prior_m3   double,
    ethanol_hydrous_current_m3   double,
    ethanol_hydrous_prior_m3     double
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_biweekly_release_series/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
