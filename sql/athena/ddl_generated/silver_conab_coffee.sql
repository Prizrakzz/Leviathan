-- silver_conab_coffee - production silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_conab_coffee.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_conab_coffee (
    commodity                         string,
    country                           string,
    safra_year                        bigint,
    survey_number                     bigint,
    region                            string,
    area_in_production_ha             double,
    yield_bags_per_ha                 double,
    production_thousand_bags          double,
    production_revision_thousand_bags double,
    source                            string,
    region_raw                        string,
    area_revision_ha                  double,
    yield_revision_bags_per_ha        double,
    production_revision_pct           double,
    production_revision_streak        bigint,
    is_repeated_survey                boolean,
    repeated_from_survey_number       bigint,
    survey_content_fingerprint        string,
    source_raw_key                    string,
    source_file_etag                  string,
    worksheet                         string,
    parser_version                    string,
    survey_release_date               string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/conab_coffee/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
