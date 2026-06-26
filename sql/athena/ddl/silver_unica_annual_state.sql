-- GENERATED from live Glue table leviathan_dev.silver_unica_annual_state; keep in sync with the S3 layout.
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
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_annual_state'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
