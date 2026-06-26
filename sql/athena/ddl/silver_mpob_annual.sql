-- GENERATED from live Glue table leviathan_dev.silver_mpob_annual; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_mpob_annual (
    year                       bigint,
    production_cpo_mt          double,
    closing_stocks_palm_oil_mt double,
    exports_palm_oil_mt        double,
    imports_palm_oil_mt        double,
    ffb_price_myr_per_mt       double,
    su_ratio                   double,
    source                     string,
    commodity                  string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/mpob_annual'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
