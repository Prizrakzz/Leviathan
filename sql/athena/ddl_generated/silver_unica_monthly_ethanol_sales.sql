-- silver_unica_monthly_ethanol_sales - biofuel silver table (derived); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_unica_monthly_ethanol_sales.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_unica_monthly_ethanol_sales (
    harvest_year         string,
    month_num            bigint,
    month_label          string,
    month_date           string,
    is_partial           boolean,
    total_current_m3     double,
    total_prior_m3       double,
    external_current_m3  double,
    external_prior_m3    double,
    internal_current_m3  double,
    internal_prior_m3    double,
    source_idm           string,
    source_position_date string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_monthly_ethanol_sales/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
