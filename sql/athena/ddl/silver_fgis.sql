-- GENERATED from live Glue table leviathan_dev.silver_fgis; keep in sync with the S3 layout.
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
LOCATION 's3://leviathan-dev-shahem-001/silver/fgis'
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
