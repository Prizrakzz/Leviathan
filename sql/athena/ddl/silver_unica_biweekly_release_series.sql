-- GENERATED from live Glue table leviathan_dev.silver_unica_biweekly_release_series; keep in sync with the S3 layout.
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
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_biweekly_release_series'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
