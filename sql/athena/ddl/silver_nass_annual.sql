-- GENERATED from live Glue table leviathan_dev.silver_nass_annual; keep in sync with the S3 layout.
--
-- D-LD pre-step D-LD-9a (ADDITIVE, 2026-08-18): release_date (string) HAND-APPENDED LAST as the 14th
-- catalog column -- the DERIVED vintage knowledge anchor ('<crop year + 1>-02-01') the numbers card
-- reads as knowledge_date_col. Measured 2026-08-18: this table carried NO date, vintage, ingest or
-- month column at all (14 body columns / 593 canonical objects / 14,631 rows), so the as-of guard had
-- nothing to anchor on. The producer
-- (src/leviathan/transforms/bronze_to_silver/usda_nass_annual.py) emits it as the appended tail;
-- live Glue catches up via a gated ADD COLUMNS (release_date string), mirroring the append here --
-- see sql/athena/migrations/silver/20260818T000000Z_silver_nass_annual_release_date_additive.json.
-- Until that ALTER + the producer re-run land, this file deliberately LEADS live Glue by this one
-- column (the WIRING_WAVE1 silver_conab_coffee survey_release_date discipline, column for column).
--
-- SILVER-F020 RESOLVED 2026-08-20 (D-EC wheat-lane flip): the enum below carries the TEN live
-- values -- the canonical promote landed all ten commodity partitions (S3-verified) and the Glue
-- enum was ALTERed to match in the same change, un-hiding canola_ice and retiring the gated
-- canola-only migration (reports/silver_readiness/R2_SA/F020_canola_migration.json, superseded
-- unapplied). The checked-in enum stays == live Glue per the R2 convention; the F020 tests now
-- pin the RESOLVED state (tests/unit/silver/test_f020_nass_projection.py, rewritten same day).
CREATE EXTERNAL TABLE IF NOT EXISTS silver_nass_annual (
    leviathan_slug        string,
    country               string,
    state                 string,
    marketing_year        bigint,
    area_planted_ha       double,
    area_harvested_ha     double,
    yield_t_ha            double,
    production_mt         double,
    area_planted_cv_pct   double,
    area_harvested_cv_pct double,
    yield_cv_pct          double,
    production_cv_pct     double,
    source                string,
    release_date          string
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/nass_annual'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'corn_cbot,soybeans_cbot,rough_rice_cbot,cotton,soft_red_winter_wheat_cbot,hard_red_spring_wheat_mgex,canola_ice,cottonseed,upland_cotton,pima_cotton',
    'projection.enabled' = 'true',
    'projection.year.range' = '1866,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/nass_annual/commodity=${commodity}/year=${year}'
);
