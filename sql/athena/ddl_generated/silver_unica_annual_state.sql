-- silver_unica_annual_state - production silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_unica_annual_state.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_unica_annual_state (
    harvest_year         string,
    state_region         string,
    cane_crushed_t       bigint,
    sugar_produced_t     bigint,
    ethanol_total_m3     bigint,
    ethanol_hydrous_m3   bigint,
    ethanol_anhydrous_m3 double,
    source               string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_annual_state/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
