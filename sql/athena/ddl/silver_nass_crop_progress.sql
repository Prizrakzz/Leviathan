-- GENERATED from live Glue table leviathan_dev.silver_nass_crop_progress; keep in sync with the S3 layout.
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
LOCATION 's3://leviathan-dev-shahem-001/silver/nass_crop_progress'
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
