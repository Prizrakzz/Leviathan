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
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.as_of_date.format' = 'yyyyMMdd',
    'projection.as_of_date.range' = '19900101,NOW',
    'projection.as_of_date.type' = 'date',
    'projection.commodity_code.type' = 'enum',
    'projection.commodity_code.values' = '101,102,103,104,107,401,701,801,901,902',
    'projection.enabled' = 'true',
    'projection.market_year.range' = '1990,2035',
    'projection.market_year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/production/source=usda_esr/commodity_code=${commodity_code}/market_year=${market_year}/as_of=${as_of_date}'
);
