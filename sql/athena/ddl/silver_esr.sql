-- GENERATED from live Glue table leviathan_dev.silver_esr; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_esr (
    commodity_name           string,
    country_code             smallint,
    week_ending_date         date,
    outstanding_sales_1000mt float,
    weekly_exports_1000mt    float,
    gross_new_sales_1000mt   float,
    changes_1000mt           float,
    source_unit_id           smallint,
    ingest_date              string,
    source                   string
)
PARTITIONED BY (commodity_code int, market_year int, as_of_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/production/source=usda_esr'
-- REGISTERED partitions since 2026-07 — DO NOT re-add partition projection. The projected
-- code x MY x daily-as_of grid (~6M candidates over 370 real dirs, ~16,000x) was THE Jul-2026 S3 LIST
-- storm ($134/2 days; ~130-600K LISTs per non-sargable query). NOTE the S3 dir key is `as_of=` while the
-- partition COLUMN is as_of_date — partitions carry explicit Locations (MSCK cannot repair this table).
-- After a DROP+CREATE from this DDL, re-register:
--   python jobs/utils/deproject_glue_table.py --register --tables silver_esr
-- New-partition writers must call leviathan.storage.glue_partitions.ensure_partition after the S3 write.
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
