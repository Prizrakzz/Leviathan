-- silver_fgis - trade_flows silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_fgis.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = projected. recovery: get-partitions inventory + single sargable Athena probe on a registered surface
--
-- LEGACY-QUARANTINED partition projection (INV-3): the projected grid enumerates every
-- candidate partition (the Jul-2026 S3 LIST-storm class). NEVER DROP+CREATE this into a
-- flat or re-projected shape; recovery reads S3 parquet footers, NEVER Athena.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_fgis (
    week_of_marketing_year int,
    week_ending_date       date,
    destination_country    string,
    exports_mt_weekly      double,
    exports_mt_ctd         double,
    source                 string
)
PARTITIONED BY (leviathan_slug string, marketing_year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fgis/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.leviathan_slug.type' = 'enum',
    'projection.leviathan_slug.values' = 'corn_cbot,soybeans_cbot,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot',
    'projection.marketing_year.range' = '1982,2035',
    'projection.marketing_year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/fgis/leviathan_slug=${leviathan_slug}/marketing_year=${marketing_year}'
);
