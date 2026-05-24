-- silver_esr: external table for USDA FAS Export Sales Reporting data.
-- Partition projection resolves S3 paths from metadata — no MSCK REPAIR TABLE needed.
-- Managed programmatically by jobs/athena_utils.py :: ensure_catalog().
-- This file is the canonical DDL reference.
--
-- Data layer: silver (cleaned, unit-normalised bronze).
-- Format:     wide — one row per (country_code, week_ending_date) snapshot.
-- Units:      all quantity columns in 1000 MT (thousands of metric tonnes).
-- Partitions: commodity_code × market_year × as_of_date (point-in-time safe).
--
-- as_of_date projection:
--   Backfill files all share a single as_of_date (the run date, e.g. 20260524).
--   Weekly files carry the Thursday publication date.
--   Range projection (no interval) is used instead of a stepped date projection
--   so that the backfill partition is always resolvable.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_esr (
    commodity_name            STRING,
    country_code              INT,
    week_ending_date          STRING,
    outstanding_sales_1000mt  DOUBLE,
    weekly_exports_1000mt     DOUBLE,
    gross_new_sales_1000mt    DOUBLE,
    changes_1000mt            DOUBLE,
    source_unit_id            INT,
    ingest_date               STRING,
    source                    STRING
)
PARTITIONED BY (commodity_code INT, market_year INT, as_of_date STRING)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/production/source=usda_esr/'
TBLPROPERTIES (
    'projection.enabled'               = 'true',
    'projection.commodity_code.type'   = 'enum',
    'projection.commodity_code.values' = '101,102,103,104,107,401,701,801,901,902',
    'projection.market_year.type'      = 'integer',
    'projection.market_year.range'     = '1990,2030',
    'projection.as_of_date.type'       = 'date',
    'projection.as_of_date.format'     = 'yyyyMMdd',
    'projection.as_of_date.range'      = '19900101,NOW',
    'storage.location.template'        = 's3://leviathan-dev-shahem-001/silver/production/source=usda_esr/commodity_code=${commodity_code}/market_year=${market_year}/as_of=${as_of_date}'
);
