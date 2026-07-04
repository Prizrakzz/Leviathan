-- USDA ESR compact SERVING table — the Jul-2026 S3 LIST-storm fix.
--
-- The original silver_esr table (silver/production/source=usda_esr, partition PROJECTION over
-- as_of_date 1990->NOW x market_year 1990-2035 x commodity_code) made Athena LIST ~130-600K S3
-- prefixes PER QUERY (26.8M LISTs = $134 on Jul 2-3 2026) because projection enumerates every
-- CANDIDATE partition while only ~350 exist (one latest snapshot per commodity x MY, stored under
-- its WRITE date). This table serves the numbers agent instead: the bronze_to_silver_esr_task's
-- one-file-per-commodity layout, REGISTERED partitions (exactly 10), no projection anywhere —
-- a query prunes to ONE ~10MB file (~2-3 LISTs).
--
-- Partitions are registered by the companion migration (Glue batch_create_partition; MSCK cannot
-- discover them if the layout ever changes dir naming). The b2s task OVERWRITES part-000.parquet
-- per commodity, so no new partitions are needed on refresh; only a NEW commodity slug requires
-- ALTER TABLE ADD PARTITION.
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
    as_of_date               string,
    ingest_date              string,
    source                   string
)
PARTITIONED BY (commodity string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/esr'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'classification' = 'parquet'
);
-- then, per commodity prefix:
-- ALTER TABLE silver_esr_compact ADD IF NOT EXISTS PARTITION (commodity='corn_cbot')
--   LOCATION 's3://leviathan-dev-shahem-001/silver/esr/commodity=corn_cbot/';
