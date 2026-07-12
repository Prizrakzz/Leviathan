-- silver_sagis_cec - production silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_sagis_cec.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_sagis_cec (
    production_year    bigint,
    report_month       bigint,
    release_date       string,
    season_type        string,
    crop               string,
    scope              string,
    estimate_number    bigint,
    area_planted_ha    double,
    current_estimate_t double,
    prior_estimate_t   double,
    prior_year_final_t double,
    revision_t         double,
    revision_pct       double,
    revision_surprise  double,
    source             string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/sagis_cec/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
