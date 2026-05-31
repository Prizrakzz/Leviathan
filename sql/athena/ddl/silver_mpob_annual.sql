-- silver_mpob_annual: MPOB annual CPO supply/demand metrics (2010–2016).
-- Single flat unpartitioned file at silver/mpob_annual/part-000.parquet.
-- Managed programmatically by jobs/run_athena_ddl.py.
--
-- Data layer:  silver (pivoted from overview_pdf bronze EAV rows).
-- Granularity: one row per calendar year (annual national totals).
-- Source:      MPOB Overview of the Malaysian Oil Palm Industry PDFs.
-- Units:       metric tonnes (MT) for production/stocks/exports/imports;
--              RM/MT for FFB price; dimensionless ratio for su_ratio.
--
-- su_ratio:    closing_stocks_palm_oil_mt / exports_palm_oil_mt (same year).
--              Proxy for "years of supply at current export pace".
--              Null when exports are zero or either component is missing.
--
-- Coverage:    2010–2016 (pre-BEPI-HTML era).
--              The monthly HTML-based silver (silver_mpob) covers 2017–present.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_mpob_annual (
    year                        INT,
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
LOCATION 's3://leviathan-dev-shahem-001/silver/mpob_annual/'
TBLPROPERTIES (
    'parquet.compress' = 'SNAPPY'
);
