-- USDA AMS Grain Transportation Report (GTR) freight family -- the Black Sea cluster's backbone.
--
-- HAND-AUTHORED against configs/silver/tables/silver_ams_gtr.yaml (there is no live Glue table to
-- generate from yet). Keep the two in sync: the registry is the authority on types and nullability.
-- The generated twin at sql/athena/ddl_generated/silver_ams_gtr.sql is rendered from that registry
-- by scripts/silver/generate_ddls_from_registry.py and must be re-rendered, never hand-edited,
-- whenever a type changes here.
--
-- TYPES: `forward_month_offset` and `rate_month` are bigint because the writer emits arrow int64
-- for both and INV-2's integer target IS int64 -- glue bigint == physical int64, so the catalog is
-- created right on the first run and `drift_summary: []` is a true statement rather than a claim.
-- This is the WASDE C-WRONG-6 closure applied before the table exists instead of after: the first
-- cut declared them `int`, which classify_drift scores as a glue_catalog_mismatch and which would
-- have made the first Athena read hit a mismatch the estate already tracks as debt.
--
-- Long/tidy by design. The family carries THREE units that must never share a column:
--     USD_per_metric_ton   ocean rates (Gulf->Japan, PNW->Japan, Ukrainian ports)
--     USD_per_ton          Mississippi River System barge, per-reach benchmark
--     percent_of_tariff    Mississippi River System barge, spot and 1M/3M forward
-- A percent-of-tariff quote runs 600-800 and a USD-per-ton quote 14-17 for the SAME barge move,
-- so `unit` is on every row and any query that aggregates across datasets MUST group by it.
--
-- PIT: `knowledge_date` is DERIVED and `knowledge_date_basis` says by which rule
-- ('derived_gtr_thursday', 'derived_gtr_thursday_month_end',
--  'derived_ams_ukraine_annual_edition', 'observed_snapshot'). `as_of_date` is the OBSERVED fetch
-- date. A consumer that will not accept a derived date filters on the basis and uses as_of_date.
--
-- `dataset` is the partition key ONLY; it is also present in the parquet body (as on silver_fgis),
-- where Athena ignores it in favour of the partition value.
--
-- Partitions are REGISTERED, not projected: the set is closed at seven and enumerable from
-- GTR_DATASETS, so partition projection would buy nothing and INV-3 forbids treating a projected
-- range as evidence of coverage. Register with ALTER TABLE ... ADD PARTITION per dataset; never MSCK.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_ams_gtr (
    series                 string,
    route_or_reach         string,
    period_date            date,
    period_grain           string,
    rate                   double,
    unit                   string,
    forward_month_offset   bigint,
    rate_month             bigint,
    commodity              string,
    vessel_size            string,
    knowledge_date         date,
    knowledge_date_basis   string,
    as_of_date             string,
    ingest_date            string,
    source_attribution     string,
    source                 string
)
PARTITIONED BY (dataset string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/ams_gtr'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);

-- The seven partitions, registered explicitly (run after the first silver write).
-- ALTER TABLE silver_ams_gtr ADD IF NOT EXISTS
--   PARTITION (dataset='ocean_weekly')            LOCATION 's3://leviathan-dev-shahem-001/silver/ams_gtr/dataset=ocean_weekly/'
--   PARTITION (dataset='ocean_monthly')           LOCATION 's3://leviathan-dev-shahem-001/silver/ams_gtr/dataset=ocean_monthly/'
--   PARTITION (dataset='barge_pct_tariff')        LOCATION 's3://leviathan-dev-shahem-001/silver/ams_gtr/dataset=barge_pct_tariff/'
--   PARTITION (dataset='barge_per_ton')           LOCATION 's3://leviathan-dev-shahem-001/silver/ams_gtr/dataset=barge_per_ton/'
--   PARTITION (dataset='barge_fwd_1m')            LOCATION 's3://leviathan-dev-shahem-001/silver/ams_gtr/dataset=barge_fwd_1m/'
--   PARTITION (dataset='barge_fwd_3m')            LOCATION 's3://leviathan-dev-shahem-001/silver/ams_gtr/dataset=barge_fwd_3m/'
--   PARTITION (dataset='ukraine_ocean_quarterly') LOCATION 's3://leviathan-dev-shahem-001/silver/ams_gtr/dataset=ukraine_ocean_quarterly/';
