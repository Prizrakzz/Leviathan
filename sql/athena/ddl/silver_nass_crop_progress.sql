-- silver_nass_crop_progress: wide USDA NASS weekly crop-progress features.
-- This table intentionally lives under silver/nass_crop_progress/ so it cannot
-- collide with annual NASS or the long-form silver_production table projection.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_nass_crop_progress (
    leviathan_slug          STRING,
    state                   STRING,
    date                    DATE,
    week_of_year            INT,
    pct_planted             DOUBLE,
    pct_emerged             DOUBLE,
    pct_good_excellent      DOUBLE,
    pct_poor_very_poor      DOUBLE,
    pct_harvested           DOUBLE,
    source                  STRING
)
PARTITIONED BY (commodity STRING, year INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/nass_crop_progress/'
TBLPROPERTIES (
    'projection.enabled'          = 'true',
    'projection.commodity.type'   = 'enum',
    'projection.commodity.values' = 'corn_cbot,soft_red_winter_wheat_cbot,hard_red_spring_wheat_mgex,rough_rice_cbot,soybeans_cbot,cotton',
    'projection.year.type'        = 'integer',
    'projection.year.range'       = '1979,2035',
    'storage.location.template'   = 's3://leviathan-dev-shahem-001/silver/nass_crop_progress/commodity=${commodity}/year=${year}'
);
