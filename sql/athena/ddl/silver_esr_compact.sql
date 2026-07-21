-- USDA ESR compact SERVING table — the Jul-2026 S3 LIST-storm fix.
--
-- The original silver_esr table (silver/production/source=usda_esr, partition PROJECTION over
-- as_of_date 1990->NOW x market_year 1990-2035 x commodity_code) made Athena LIST ~130-600K S3
-- prefixes PER QUERY (26.8M LISTs = $134 on Jul 2-3 2026) because projection enumerates every
-- CANDIDATE partition while only ~350 exist (one latest snapshot per commodity x MY, stored under
-- its WRITE date). This table serves the numbers agent instead: REGISTERED partitions, no
-- projection anywhere — a query prunes catalog-side.
--
-- SYNCED 2026-07-21 to the BF-W2/E12 canonical ESR window scheme: partitions are
-- [commodity, as_of_date] (one registered partition per commodity x weekly vintage — the
-- all-vintage publish that made true PIT replay possible), so as_of_date moved from an in-file
-- data column to a PARTITION KEY and is deliberately NOT declared as a column (name collision).
-- Partitions are registered by the publisher (Glue batch_create_partition; MSCK cannot discover
-- them if the layout ever changes dir naming).
CREATE EXTERNAL TABLE IF NOT EXISTS silver_esr_compact (
    commodity_code           smallint,
    commodity_name           string,
    market_year              smallint,
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
PARTITIONED BY (commodity string, as_of_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/esr'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'classification' = 'parquet'
);
