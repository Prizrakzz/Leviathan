-- silver_mpob: MPOB (Malaysian Palm Oil Board) monthly CPO supply/demand metrics.
-- Single flat unpartitioned file at silver/mpob/part-000.parquet.
-- Managed programmatically by jobs/run_athena_ddl.py :: ensure_catalog().
--
-- Data layer:  silver (pivoted from annual_summary bronze EAV rows).
-- Granularity: one row per calendar month (YYYY-MM-01).
-- Source:      MPOB BEPI annual summary HTML tables (annual_summary bronze).
-- Units:       metric tonnes (MT) for production/stocks/exports/imports;
--              RM/MT for FFB price; dimensionless ratio for su_ratio.
--
-- su_ratio:    closing_stocks_palm_oil_mt / exports_palm_oil_mt (same month).
--              Proxy for "months of supply at current export pace".
--              Null when exports are zero or either component is missing.
--
-- Coverage:    December 2016 – latest published month (~113 rows as of 2026-05).
--              Grows by 1 row each month as MPOB publishes new data and
--              the bronze + silver pipelines are re-run.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_mpob (
    date                        STRING,
    production_cpo_mt           DOUBLE,
    closing_stocks_palm_oil_mt  DOUBLE,
    exports_palm_oil_mt         DOUBLE,
    imports_palm_oil_mt         DOUBLE,
    ffb_price_myr_per_mt        DOUBLE,
    su_ratio                    DOUBLE,
    source                      STRING,
    commodity                   STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/mpob/'
TBLPROPERTIES (
    'parquet.compress' = 'SNAPPY'
);
