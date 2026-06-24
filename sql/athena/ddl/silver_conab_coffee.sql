-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_conab_coffee
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_conab_coffee` (
    `country`                           STRING,
    `region`                            STRING,
    `region_raw`                        STRING,
    `area_in_production_ha`             DOUBLE,
    `yield_bags_per_ha`                 DOUBLE,
    `production_thousand_bags`          DOUBLE,
    `area_revision_ha`                  DOUBLE,
    `yield_revision_bags_per_ha`        DOUBLE,
    `production_revision_thousand_bags` DOUBLE,
    `production_revision_pct`           DOUBLE,
    `production_revision_streak`        INT,
    `is_repeated_survey`                BOOLEAN,
    `repeated_from_survey_number`       BIGINT,
    `survey_content_fingerprint`        STRING,
    `source_raw_key`                    STRING,
    `source_file_etag`                  STRING,
    `worksheet`                         STRING,
    `parser_version`                    STRING,
    `source`                            STRING
)
PARTITIONED BY (`commodity` STRING, `safra_year` BIGINT, `survey_number` BIGINT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/conab_coffee/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'arabica_coffee,robusta_coffee',
    'projection.enabled' = 'true',
    'projection.safra_year.range' = '2023,2035',
    'projection.safra_year.type' = 'integer',
    'projection.survey_number.digits' = '2',
    'projection.survey_number.range' = '1,10',
    'projection.survey_number.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/conab_coffee/commodity=${commodity}/safra_year=${safra_year}/survey=${survey_number}'
);
