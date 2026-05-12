-- silver_production: external table with partition projection
-- Partition projection resolves S3 paths from metadata — no MSCK REPAIR TABLE needed.
-- Managed programmatically by jobs/athena_utils.py :: ensure_catalog().
-- This file is the canonical DDL reference.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_production (
    country          STRING,
    country_key      STRING,
    commodity        STRING,
    metric           STRING,
    unit             STRING,
    value            DOUBLE,
    flag             STRING,
    is_official      BOOLEAN,
    note             STRING,
    source           STRING,
    dataset          STRING,
    ingest_date      STRING,
    source_file_name STRING
)
PARTITIONED BY (year INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/production/commodity=cocoa/'
TBLPROPERTIES (
    'projection.enabled'        = 'true',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '1961,2023',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/production/commodity=cocoa/year=${year}'
);
