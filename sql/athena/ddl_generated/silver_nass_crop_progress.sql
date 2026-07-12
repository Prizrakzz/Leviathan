-- silver_nass_crop_progress - crop_condition silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_nass_crop_progress.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = projected. recovery: get-partitions inventory + single sargable Athena probe on a registered surface
--
-- LEGACY-QUARANTINED partition projection (INV-3): the projected grid enumerates every
-- candidate partition (the Jul-2026 S3 LIST-storm class). NEVER DROP+CREATE this into a
-- flat or re-projected shape; recovery reads S3 parquet footers, NEVER Athena.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_nass_crop_progress (
    leviathan_slug     string,
    state              string,
    date               date,
    week_of_year       bigint,
    pct_planted        double,
    pct_emerged        double,
    pct_good_excellent double,
    pct_poor_very_poor double,
    pct_harvested      double,
    source             string
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/nass_crop_progress/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'corn_cbot,soybeans_cbot,rough_rice_cbot,cotton,soft_red_winter_wheat_cbot,hard_red_spring_wheat_mgex',
    'projection.enabled' = 'true',
    'projection.year.range' = '1979,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/nass_crop_progress/commodity=${commodity}/year=${year}'
);
